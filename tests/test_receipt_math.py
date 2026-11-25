"""Unit tests for deterministic receipt math & validation (`src/domain/receipt_math.py`)."""

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.receipt_math import SUM_TOLERANCE_PLN, validate_receipt
from src.domain.schemas import ReceiptExtraction, ReceiptItemExtraction

_NOW = datetime(2026, 11, 20, 14, 30, tzinfo=UTC)


def _item(
    name: str,
    total: str,
    *,
    category: str = "inne",
    discount: str = "0.00",
) -> ReceiptItemExtraction:
    return ReceiptItemExtraction(
        raw_name=name.upper(),
        normalized_name=name,
        category=category,  # type: ignore[arg-type]
        discount_amount=Decimal(discount),
        total_price=Decimal(total),
    )


def test_valid_receipt_exact_match_with_item_discounts() -> None:
    receipt = ReceiptExtraction(
        store_name="Lidl",
        store_normalized="lidl",
        purchased_at=_NOW,
        total_amount=Decimal("21.49"),
        items=[
            # 12.99 minus 3.50 OPUST = 9.49
            _item("filet z łososia", "9.49", category="ryby", discount="3.50"),
            _item("pomidor malinowy", "9.04", category="warzywa"),
            _item("mleko 2%", "2.96", category="nabial"),
        ],
    )
    result = validate_receipt(receipt)
    assert result.is_valid is True
    assert result.needs_reflection is False
    assert result.computed_sum == Decimal("21.49")
    assert result.sum_diff == Decimal("0.00")
    assert result.errors == []
    assert result.reflection_feedback is None


def test_valid_receipt_with_basket_level_discount() -> None:
    receipt = ReceiptExtraction(
        store_name="Lidl",
        store_normalized="lidl",
        purchased_at=_NOW,
        total_amount=Decimal("40.00"),
        items=[
            _item("kawa ziarnista", "50.00", category="napoje"),
            _item("rabat koszykowy lidl plus", "-10.00", category="inne"),
        ],
    )
    result = validate_receipt(receipt)
    assert result.is_valid is True
    assert result.computed_sum == Decimal("40.00")
    assert result.sum_diff == Decimal("0.00")


def test_sum_diff_within_tolerance_is_valid() -> None:
    receipt = ReceiptExtraction(
        store_name="Aldi",
        store_normalized="aldi",
        purchased_at=_NOW,
        total_amount=Decimal("20.00"),
        items=[_item("chleb", "19.50", category="pieczywo")],
    )
    result = validate_receipt(receipt)
    assert result.sum_diff == SUM_TOLERANCE_PLN
    assert result.is_valid is True


def test_sum_diff_above_tolerance_triggers_reflection_feedback() -> None:
    # Classic Polish receipt bug: LLM missed a 5.50 PLN OPUST line.
    receipt = ReceiptExtraction(
        store_name="Lidl",
        store_normalized="lidl",
        purchased_at=_NOW,
        total_amount=Decimal("108.70"),
        items=[
            _item("ser żółty", "64.20", category="nabial"),
            _item("oliwa", "50.00", category="inne"),
        ],
    )
    result = validate_receipt(receipt)
    assert result.is_valid is False
    assert result.needs_reflection is True
    assert result.computed_sum == Decimal("114.20")
    assert result.sum_diff == Decimal("5.50")
    assert result.reflection_feedback is not None
    assert "114.20 PLN" in result.reflection_feedback
    assert "108.70 PLN" in result.reflection_feedback
    assert "5.50 PLN" in result.reflection_feedback
    assert "OPUST/RABAT" in result.reflection_feedback


def test_missing_required_fields_reported_all_at_once() -> None:
    empty_receipt = ReceiptExtraction()
    result = validate_receipt(empty_receipt)
    assert result.is_valid is False
    assert result.computed_sum == Decimal("0.00")
    assert len(result.errors) == 4
    assert result.reflection_feedback is not None
    assert "Brak odczytanych pozycji" in result.reflection_feedback
    assert "Brak nazwy sklepu" in result.reflection_feedback
    assert "Brak daty" in result.reflection_feedback
    assert "Brak kwoty końcowej" in result.reflection_feedback
