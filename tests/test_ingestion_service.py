"""Unit & DB-backed pipeline tests for telemetry, embeddings, and IngestionService.

All LLM calls use PydanticAI `FunctionModel` (zero real Gemini API calls).
DB-backed tests wrap each test in a rolled-back transaction (leaving zero test rows behind)
and skip cleanly if PostgreSQL is not reachable.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.config import Settings, get_settings
from src.db.models import AgentRun, PantrySnapshot, Receipt, ReceiptItem, User, UserProfile
from src.db.repositories import UserRepository
from src.services.embeddings import EmbeddingService
from src.services.ingestion_service import IngestionService
from src.services.telemetry import estimate_cost_usd

_FAKE_JPEG = b"\xff\xd8\xff\xe0fake-photo-bytes"


def _tool_reply(info: AgentInfo, payload: dict[str, object]) -> ModelResponse:
    tool_name = info.output_tools[0].name
    return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=payload)])


def _offline_settings() -> Settings:
    return Settings(_env_file=None, embeddings_enabled=False)  # type: ignore[call-arg]


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession bound to a rolled-back transaction on the local PostgreSQL."""
    engine = create_async_engine(get_settings().database_url)
    try:
        try:
            conn = await engine.connect()
        except (OSError, TimeoutError) as exc:
            pytest.skip(f"PostgreSQL not reachable: {exc.__class__.__name__}")

        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
            await conn.close()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Pure unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_estimate_cost_usd_known_and_unknown_models() -> None:
    # 1M input @ $0.30 + 1M output @ $2.50 = $2.80
    assert estimate_cost_usd("google-gla:gemini-3.8-flash", 1_000_000, 1_000_000) == Decimal(
        "2.800000"
    )
    assert estimate_cost_usd("test", 500, 200) == Decimal("0.000000")


async def test_embedding_service_returns_none_when_disabled() -> None:
    service = EmbeddingService(settings=_offline_settings())
    assert service.enabled is False
    assert await service.embed_texts(["mleko 2%", "chleb"]) == [None, None]
    assert await service.embed_texts([]) == []


# ---------------------------------------------------------------------------
# End-to-end IngestionService tests (real PostgreSQL + FunctionModel, $0 API)
# ---------------------------------------------------------------------------


async def _create_test_user(session: AsyncSession, *, telegram_id: int, limit: int = 15) -> User:
    user, _ = await UserRepository(session).get_or_create(
        telegram_id=telegram_id,
        display_name="Test User",
        is_active=True,
    )
    user.daily_image_limit = limit
    await session.flush()
    return user


async def test_ingestion_receipt_reflection_fixes_mismatch_and_confirms(
    db_session: AsyncSession,
) -> None:
    user = await _create_test_user(db_session, telegram_id=900_001)

    classifier_fn = FunctionModel(
        lambda _m, info: _tool_reply(
            info,
            {"image_type": "receipt", "confidence": 0.99, "reason": "Paragon z Lidla"},
        )
    )

    ocr_calls = 0

    def ocr_with_reflection(_m: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal ocr_calls
        ocr_calls += 1
        if ocr_calls == 1:
            # Pass 1: missed 5.50 PLN OPUST -> sum is 114.20 vs total 108.70
            return _tool_reply(
                info,
                {
                    "store_name": "Lidl",
                    "store_normalized": "lidl",
                    "purchased_at": "2026-11-20T14:30:00Z",
                    "total_amount": "108.70",
                    "items": [
                        {
                            "raw_name": "SER GOUDA",
                            "normalized_name": "ser gouda",
                            "category": "nabial",
                            "total_price": "64.20",
                        },
                        {
                            "raw_name": "OLIWA",
                            "normalized_name": "oliwa",
                            "category": "inne",
                            "total_price": "50.00",
                        },
                    ],
                },
            )
        # Pass 2 (Reflection): fixed 5.50 PLN discount
        return _tool_reply(
            info,
            {
                "store_name": "Lidl",
                "store_normalized": "lidl",
                "purchased_at": "2026-11-20T14:30:00Z",
                "total_amount": "108.70",
                "items": [
                    {
                        "raw_name": "SER GOUDA",
                        "normalized_name": "ser gouda",
                        "category": "nabial",
                        "discount_amount": "5.50",
                        "total_price": "58.70",
                    },
                    {
                        "raw_name": "OLIWA",
                        "normalized_name": "oliwa",
                        "category": "inne",
                        "total_price": "50.00",
                    },
                ],
            },
        )

    service = IngestionService(
        db_session,
        settings=_offline_settings(),
        classifier_model=classifier_fn,
        ocr_model=FunctionModel(ocr_with_reflection),
    )

    outcome = await service.process_photo(user, _FAKE_JPEG)

    assert outcome.status == "receipt_confirmed"
    assert outcome.reflection_used is True
    assert outcome.receipt_id is not None
    assert ocr_calls == 2

    db_receipt = await db_session.get(Receipt, outcome.receipt_id)
    assert db_receipt is not None
    assert db_receipt.status == "confirmed"
    assert db_receipt.needs_review is False
    assert db_receipt.sum_diff == Decimal("0.00")

    items = list(
        await db_session.scalars(select(ReceiptItem).where(ReceiptItem.receipt_id == db_receipt.id))
    )
    assert len(items) == 2

    profile = await db_session.get(UserProfile, user.id)
    assert profile is not None
    assert profile.receipts_since_last_update == 1

    runs = list(await db_session.scalars(select(AgentRun).where(AgentRun.user_id == user.id)))
    assert sorted((r.agent_name, r.status) for r in runs) == sorted(
        [
            ("classifier", "success"),
            ("receipt_ocr", "success"),
            ("receipt_ocr", "retry"),
        ]
    )


async def test_ingestion_receipt_persistent_mismatch_marks_pending_review(
    db_session: AsyncSession,
) -> None:
    user = await _create_test_user(db_session, telegram_id=900_002)

    classifier_fn = FunctionModel(
        lambda _m, info: _tool_reply(
            info,
            {"image_type": "receipt", "confidence": 0.95, "reason": "Paragon"},
        )
    )
    always_wrong_ocr = FunctionModel(
        lambda _m, info: _tool_reply(
            info,
            {
                "store_name": "Aldi",
                "store_normalized": "aldi",
                "purchased_at": "2026-11-21T10:00:00Z",
                "total_amount": "50.00",
                "items": [
                    {
                        "raw_name": "CHLEB",
                        "normalized_name": "chleb",
                        "category": "pieczywo",
                        "total_price": "10.00",
                    }
                ],
            },
        )
    )

    service = IngestionService(
        db_session,
        settings=_offline_settings(),
        classifier_model=classifier_fn,
        ocr_model=always_wrong_ocr,
    )
    outcome = await service.process_photo(user, _FAKE_JPEG)

    assert outcome.status == "receipt_pending_review"
    assert outcome.reflection_used is True
    assert outcome.receipt_id is not None

    db_receipt = await db_session.get(Receipt, outcome.receipt_id)
    assert db_receipt is not None
    assert db_receipt.status == "pending_review"
    assert db_receipt.needs_review is True
    assert db_receipt.review_reason is not None
    assert "40.00 PLN" in db_receipt.review_reason


async def test_ingestion_pantry_and_daily_limit_guard(db_session: AsyncSession) -> None:
    user = await _create_test_user(db_session, telegram_id=900_003, limit=1)

    classifier_calls = 0

    def fake_classifier(_m: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal classifier_calls
        classifier_calls += 1
        return _tool_reply(
            info,
            {"image_type": "fridge", "confidence": 0.92, "reason": "Otwarta lodówka"},
        )

    fake_pantry = FunctionModel(
        lambda _m, info: _tool_reply(
            info,
            {
                "source_type": "fridge",
                "items": [{"name": "mleko 2%", "category": "nabial", "level": "low"}],
                "summary_note": "Kończy się mleko.",
            },
        )
    )

    service = IngestionService(
        db_session,
        settings=_offline_settings(),
        classifier_model=FunctionModel(fake_classifier),
        pantry_model=fake_pantry,
    )

    # Photo 1 succeeds and saves a pantry snapshot
    first = await service.process_photo(user, _FAKE_JPEG)
    assert first.status == "pantry_saved"
    assert first.pantry_snapshot_id is not None
    assert first.daily_used == 1
    assert await db_session.get(PantrySnapshot, first.pantry_snapshot_id) is not None

    # Photo 2 hits daily_image_limit=1 BEFORE calling the classifier
    second = await service.process_photo(user, _FAKE_JPEG)
    assert second.status == "daily_limit_exceeded"
    assert second.daily_used == 1
    assert second.daily_limit == 1
    assert classifier_calls == 1
