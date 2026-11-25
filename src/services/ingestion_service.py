"""Photo ingestion pipeline — orchestrates limit checks, vision agents, Reflection, and DB save.

Implements Section 3A of `docs/PHASE_1_SPEC.md`:
1. Daily image limit guard (`users.daily_image_limit`).
2. Image classification (`classifier`).
3. Branch by image type:
   - `unsupported` -> return cleanly without saving.
   - `fridge` / `pantry` / `groceries` -> `pantry_vision` -> save `pantry_snapshots`.
   - `receipt` -> `receipt_ocr` Pass 1 -> deterministic `validate_receipt` ->
     optional Pass 2 (`reflect_receipt`, max 1 retry) -> optional embeddings ->
     save `receipts` + `receipt_items` (`confirmed` or `pending_review`).
4. Every LLM call is logged in `agent_runs`. Raw image bytes stay strictly in RAM.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.classifier import classify_image
from src.agents.pantry_vision import analyze_pantry
from src.agents.receipt_ocr import extract_receipt, reflect_receipt
from src.core.config import Settings, get_settings
from src.core.models_registry import ModelRef, resolve_model
from src.db.models import User
from src.db.repositories import (
    AgentRunRepository,
    PantryRepository,
    ProfileRepository,
    ReceiptRepository,
    ReceiptStatus,
    UserRepository,
)
from src.domain.receipt_math import ReceiptValidationResult, validate_receipt
from src.domain.schemas import (
    ImageClassification,
    PantryExtraction,
    PantrySourceType,
    ReceiptExtraction,
)
from src.services.embeddings import EmbeddingService
from src.services.telemetry import run_tracked_agent

IngestionStatus = Literal[
    "daily_limit_exceeded",
    "unsupported",
    "receipt_confirmed",
    "receipt_pending_review",
    "pantry_saved",
]


class IngestionOutcome(BaseModel):
    """Structured result returned by `IngestionService.process_photo` to Telegram/API layers."""

    model_config = ConfigDict(frozen=True)

    status: IngestionStatus
    classification: ImageClassification | None = None
    receipt_id: uuid.UUID | None = None
    receipt: ReceiptExtraction | None = None
    validation: ReceiptValidationResult | None = None
    reflection_used: bool = False
    pantry_snapshot_id: uuid.UUID | None = None
    pantry: PantryExtraction | None = None
    daily_used: int = 0
    daily_limit: int = 0


class IngestionService:
    """Orchestrates the Phase 1 multimodal photo ingestion workflow."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        embedding_service: EmbeddingService | None = None,
        classifier_model: ModelRef | None = None,
        ocr_model: ModelRef | None = None,
        pantry_model: ModelRef | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._users = UserRepository(session)
        self._receipts = ReceiptRepository(session)
        self._pantry = PantryRepository(session)
        self._profiles = ProfileRepository(session)
        self._agent_runs = AgentRunRepository(session)
        self._embeddings = embedding_service or EmbeddingService(self._settings)
        self._classifier_model = classifier_model
        self._ocr_model = ocr_model
        self._pantry_model = pantry_model

    async def process_photo(
        self,
        user: User,
        image_bytes: bytes,
        *,
        media_type: str = "image/jpeg",
        trigger_type: str = "telegram_photo",
    ) -> IngestionOutcome:
        """Process raw photo bytes in memory for `user`."""
        used_today = await self._users.count_photos_today(user.id)
        if used_today >= user.daily_image_limit:
            return IngestionOutcome(
                status="daily_limit_exceeded",
                daily_used=used_today,
                daily_limit=user.daily_image_limit,
            )

        classifier_model = resolve_model(
            self._classifier_model, tier="fast", settings=self._settings
        )
        cls_result = await run_tracked_agent(
            repo=self._agent_runs,
            user_id=user.id,
            trigger_type=trigger_type,
            agent_name="classifier",
            model=classifier_model,
            call=lambda: classify_image(image_bytes, media_type=media_type, model=classifier_model),
        )
        classification = cls_result.output

        if classification.image_type == "unsupported":
            return IngestionOutcome(
                status="unsupported",
                classification=classification,
                daily_used=used_today + 1,
                daily_limit=user.daily_image_limit,
            )

        if classification.image_type in ("fridge", "pantry", "groceries"):
            return await self._process_pantry(
                user=user,
                image_bytes=image_bytes,
                media_type=media_type,
                trigger_type=trigger_type,
                classification=classification,
                source_hint=classification.image_type,
                daily_used=used_today + 1,
            )

        return await self._process_receipt(
            user=user,
            image_bytes=image_bytes,
            media_type=media_type,
            trigger_type=trigger_type,
            classification=classification,
            daily_used=used_today + 1,
        )

    async def _process_pantry(
        self,
        *,
        user: User,
        image_bytes: bytes,
        media_type: str,
        trigger_type: str,
        classification: ImageClassification,
        source_hint: PantrySourceType,
        daily_used: int,
    ) -> IngestionOutcome:
        pantry_model = resolve_model(self._pantry_model, tier="fast", settings=self._settings)
        pantry_result = await run_tracked_agent(
            repo=self._agent_runs,
            user_id=user.id,
            trigger_type=trigger_type,
            agent_name="pantry_vision",
            model=pantry_model,
            call=lambda: analyze_pantry(
                image_bytes,
                source_hint=source_hint,
                media_type=media_type,
                model=pantry_model,
            ),
        )
        snapshot = await self._pantry.create_snapshot(
            user_id=user.id,
            extraction=pantry_result.output,
        )
        return IngestionOutcome(
            status="pantry_saved",
            classification=classification,
            pantry_snapshot_id=snapshot.id,
            pantry=pantry_result.output,
            daily_used=daily_used,
            daily_limit=user.daily_image_limit,
        )

    async def _process_receipt(
        self,
        *,
        user: User,
        image_bytes: bytes,
        media_type: str,
        trigger_type: str,
        classification: ImageClassification,
        daily_used: int,
    ) -> IngestionOutcome:
        ocr_model = resolve_model(self._ocr_model, tier="fast", settings=self._settings)

        # Pass 1: initial OCR extraction
        pass1 = await run_tracked_agent(
            repo=self._agent_runs,
            user_id=user.id,
            trigger_type=trigger_type,
            agent_name="receipt_ocr",
            model=ocr_model,
            call=lambda: extract_receipt(image_bytes, media_type=media_type, model=ocr_model),
        )
        extraction = pass1.output
        validation = validate_receipt(extraction)
        reflection_used = False

        # Pass 2 (Reflection — max 1 retry when math/completeness check fails)
        if validation.needs_reflection and validation.reflection_feedback is not None:
            reflection_used = True
            feedback = validation.reflection_feedback
            previous = extraction
            pass2 = await run_tracked_agent(
                repo=self._agent_runs,
                user_id=user.id,
                trigger_type=trigger_type,
                agent_name="receipt_ocr",
                model=ocr_model,
                status_on_success="retry",
                call=lambda: reflect_receipt(
                    image_bytes,
                    previous_extraction=previous,
                    validation_feedback=feedback,
                    media_type=media_type,
                    model=ocr_model,
                ),
            )
            extraction = pass2.output
            validation = validate_receipt(extraction)

        db_status: ReceiptStatus = "confirmed" if validation.is_valid else "pending_review"
        outcome_status: IngestionStatus = (
            "receipt_confirmed" if validation.is_valid else "receipt_pending_review"
        )

        embeddings = await self._embeddings.embed_texts(
            [item.normalized_name for item in extraction.items]
        )

        receipt = await self._receipts.create_with_items(
            user_id=user.id,
            extraction=extraction,
            validation=validation,
            status=db_status,
            embeddings=embeddings,
        )

        if db_status == "confirmed":
            await self._profiles.increment_receipts_counter(user.id)

        return IngestionOutcome(
            status=outcome_status,
            classification=classification,
            receipt_id=receipt.id,
            receipt=extraction,
            validation=validation,
            reflection_used=reflection_used,
            daily_used=daily_used,
            daily_limit=user.daily_image_limit,
        )
