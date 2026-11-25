"""Zero-cost unit tests for PydanticAI agents & model registry (`TestModel` / `FunctionModel`).

Never makes real Gemini/Anthropic API calls.
"""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from src.agents.classifier import classify_image
from src.agents.pantry_vision import analyze_pantry
from src.agents.profiler import synthesize_profile, update_profile_from_message
from src.agents.receipt_ocr import extract_receipt, reflect_receipt
from src.core.config import Settings
from src.core.models_registry import (
    get_embedding_model,
    get_fast_model,
    get_reasoning_model,
    resolve_model,
)
from src.domain.receipt_math import validate_receipt
from src.domain.schemas import (
    ImageClassification,
    PantryExtraction,
    ReceiptExtraction,
    ReceiptItemExtraction,
    UserProfileOutput,
)

_FAKE_JPEG = b"\xff\xd8\xff\xe0fake-receipt-image-bytes"


def _extract_user_parts(messages: list[ModelMessage]) -> tuple[str, list[BinaryContent]]:
    """Collect text chunks and BinaryContent parts sent in user prompts."""
    texts: list[str] = []
    binaries: list[BinaryContent] = []
    for msg in messages:
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                if isinstance(part.content, str):
                    texts.append(part.content)
                else:
                    for item in part.content:
                        if isinstance(item, str):
                            texts.append(item)
                        elif isinstance(item, BinaryContent):
                            binaries.append(item)
    return "\n".join(texts), binaries


def _output_tool_response(info: AgentInfo, payload: dict[str, object]) -> ModelResponse:
    """Build a synthetic structured-output tool call response for `FunctionModel`."""
    assert info.output_tools, "Expected structured output tool on agent"
    tool_name = info.output_tools[0].name
    return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=payload)])


def test_models_registry_reads_from_settings_and_respects_override() -> None:
    custom = Settings(
        _env_file=None,  # type: ignore[call-arg]
        model_fast="google-gla:custom-fast",
        model_reasoning="anthropic:custom-reasoning",
        model_embedding="custom-embed-001",
    )
    assert get_fast_model(custom) == "google-gla:custom-fast"
    assert get_reasoning_model(custom) == "anthropic:custom-reasoning"
    assert get_embedding_model(custom) == "custom-embed-001"

    assert resolve_model(tier="fast", settings=custom) == "google-gla:custom-fast"
    assert resolve_model(tier="reasoning", settings=custom) == "anthropic:custom-reasoning"

    override = TestModel()
    assert resolve_model(override, tier="fast", settings=custom) is override


async def test_classify_image_with_test_model_and_binary_content() -> None:
    # 1. Smoke test with TestModel + usage telemetry
    result = await classify_image(_FAKE_JPEG, model=TestModel())
    assert isinstance(result.output, ImageClassification)
    assert result.usage.requests == 1

    # 2. Verify raw bytes are passed in memory via BinaryContent (never written to disk)
    seen_binaries: list[BinaryContent] = []

    def fake_classifier(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        _, binaries = _extract_user_parts(messages)
        seen_binaries.extend(binaries)
        return _output_tool_response(
            info,
            {
                "image_type": "receipt",
                "confidence": 0.98,
                "reason": "Widoczny polski paragon fiskalny.",
            },
        )

    res = await classify_image(
        _FAKE_JPEG, media_type="image/png", model=FunctionModel(fake_classifier)
    )
    assert res.output.image_type == "receipt"
    assert res.output.confidence == 0.98
    assert len(seen_binaries) == 1
    assert seen_binaries[0].data == _FAKE_JPEG
    assert seen_binaries[0].media_type == "image/png"


async def test_receipt_extract_and_reflection_flow() -> None:
    # Pass 1 smoke test with TestModel
    pass1 = await extract_receipt(_FAKE_JPEG, model=TestModel())
    assert isinstance(pass1.output, ReceiptExtraction)

    # Simulate Pass 1 returning a receipt with a missed 5.50 PLN OPUST discount
    broken = ReceiptExtraction(
        store_name="Lidl",
        store_normalized="lidl",
        purchased_at=datetime(2026, 11, 20, 14, 30, tzinfo=UTC),
        total_amount=Decimal("108.70"),
        items=[
            ReceiptItemExtraction(
                raw_name="SER GOUDA",
                normalized_name="ser gouda",
                category="nabial",
                total_price=Decimal("64.20"),
            ),
            ReceiptItemExtraction(
                raw_name="OLIWA Z OLIWEK",
                normalized_name="oliwa z oliwek",
                category="inne",
                total_price=Decimal("50.00"),
            ),
        ],
    )
    validation = validate_receipt(broken)
    assert validation.needs_reflection is True
    assert validation.reflection_feedback is not None

    # Pass 2 (Reflection): verify prompt includes image + previous JSON + feedback
    captured_prompt = ""
    captured_binaries: list[BinaryContent] = []

    def fake_reflection(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal captured_prompt
        text, binaries = _extract_user_parts(messages)
        captured_prompt = text
        captured_binaries.extend(binaries)
        return _output_tool_response(
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
                        "raw_name": "OLIWA Z OLIWEK",
                        "normalized_name": "oliwa z oliwek",
                        "category": "inne",
                        "total_price": "50.00",
                    },
                ],
            },
        )

    pass2 = await reflect_receipt(
        _FAKE_JPEG,
        previous_extraction=broken,
        validation_feedback=validation.reflection_feedback,
        model=FunctionModel(fake_reflection),
    )
    assert len(captured_binaries) == 1
    assert captured_binaries[0].data == _FAKE_JPEG
    assert "OPUST/RABAT" in captured_prompt
    assert "SER GOUDA" in captured_prompt

    # After reflection, deterministic math validation must succeed
    revalidated = validate_receipt(pass2.output)
    assert revalidated.is_valid is True
    assert revalidated.sum_diff == Decimal("0.00")


async def test_pantry_vision_passes_source_hint_and_image() -> None:
    captured_text = ""
    captured_binaries: list[BinaryContent] = []

    def fake_pantry(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal captured_text
        text, binaries = _extract_user_parts(messages)
        captured_text = text
        captured_binaries.extend(binaries)
        return _output_tool_response(
            info,
            {
                "source_type": "fridge",
                "items": [{"name": "mleko 2%", "category": "nabial", "level": "low"}],
                "summary_note": "Kończy się mleko.",
            },
        )

    res = await analyze_pantry(
        _FAKE_JPEG,
        source_hint="fridge",
        model=FunctionModel(fake_pantry),
    )
    assert isinstance(res.output, PantryExtraction)
    assert res.output.source_type == "fridge"
    assert res.output.items[0].level == "low"
    assert "fridge" in captured_text
    assert len(captured_binaries) == 1


async def test_profiler_synthesis_and_chat_update() -> None:
    # 1. Initial synthesis with TestModel
    synth = await synthesize_profile(
        stats_summary="Top sklepy: lidl (6 wizyt, śr. 120 PLN). Top produkty: mleko 2%, banan.",
        model=TestModel(),
    )
    assert isinstance(synth.output, UserProfileOutput)

    # 2. Manual chat preference update with FunctionModel
    current = UserProfileOutput(
        profile_markdown="Kupuje głównie w Lidlu.",
        preferred_stores=["lidl"],
        avoided_stores=[],
        custom_rules=[],
    )
    captured_text = ""

    def fake_profiler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal captured_text
        text, _ = _extract_user_parts(messages)
        captured_text = text
        return _output_tool_response(
            info,
            {
                "profile_markdown": "Kupuje głównie w Lidlu, unika Biedronki.",
                "preferred_stores": ["lidl"],
                "avoided_stores": ["biedronka"],
                "custom_rules": ["bez słodyczy"],
            },
        )

    updated = await update_profile_from_message(
        user_message="Unikam Biedronki i nie kupujmy już słodyczy.",
        current_profile=current,
        model=FunctionModel(fake_profiler),
    )
    assert "Unikam Biedronki" in captured_text
    assert "lidl" in captured_text
    assert updated.output.avoided_stores == ["biedronka"]
    assert "bez słodyczy" in updated.output.custom_rules
