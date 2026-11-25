"""Unit tests for Pydantic v2 domain contracts (`src/domain/schemas.py`)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.schemas import (
    ImageClassification,
    PantryExtraction,
    PantryItem,
    ReceiptExtraction,
    ReceiptItemExtraction,
    UserProfileOutput,
)


def test_image_classification_valid_and_bounds() -> None:
    cls = ImageClassification(image_type="receipt", confidence=0.95, reason="Paragon z Lidla")
    assert cls.image_type == "receipt"

    with pytest.raises(ValidationError):
        ImageClassification(image_type="receipt", confidence=1.5, reason="Too high")

    with pytest.raises(ValidationError):
        ImageClassification(image_type="unknown", confidence=0.5, reason="Bad literal")  # type: ignore[arg-type]


def test_receipt_item_normalizes_name_and_allows_discount() -> None:
    item = ReceiptItemExtraction(
        raw_name="  POM. MALIN. LUZ  ",
        normalized_name="  Pomidor Malinowy ",
        category="warzywa",
        quantity=Decimal("0.452"),
        unit="kg",
        unit_price=Decimal("19.99"),
        discount_amount=Decimal("2.00"),
        total_price=Decimal("7.04"),
    )
    assert item.raw_name == "POM. MALIN. LUZ"
    assert item.normalized_name == "pomidor malinowy"
    assert item.total_price == Decimal("7.04")


def test_receipt_item_negative_price_allowed_only_for_inne() -> None:
    # Basket-level coupon in "inne" is valid.
    basket_discount = ReceiptItemExtraction(
        raw_name="RABAT KOSZYKOWY LIDL PLUS",
        normalized_name="rabat koszykowy",
        category="inne",
        total_price=Decimal("-10.00"),
    )
    assert basket_discount.total_price == Decimal("-10.00")

    # Regular food category cannot have a negative total_price.
    with pytest.raises(ValidationError, match="Negative total_price"):
        ReceiptItemExtraction(
            raw_name="MLEKO 2%",
            normalized_name="mleko 2%",
            category="nabial",
            total_price=Decimal("-3.50"),
        )


def test_receipt_item_rejects_negative_discount_or_zero_quantity() -> None:
    with pytest.raises(ValidationError):
        ReceiptItemExtraction(
            raw_name="CHLEB",
            normalized_name="chleb",
            category="pieczywo",
            discount_amount=Decimal("-1.00"),
            total_price=Decimal("5.00"),
        )

    with pytest.raises(ValidationError):
        ReceiptItemExtraction(
            raw_name="CHLEB",
            normalized_name="chleb",
            category="pieczywo",
            quantity=Decimal("0"),
            total_price=Decimal("5.00"),
        )


def test_receipt_extraction_strips_blank_store_to_none() -> None:
    receipt = ReceiptExtraction(store_name="   ", store_normalized="  LIDL  ")
    assert receipt.store_name is None
    assert receipt.store_normalized == "lidl"


def test_pantry_and_profile_schemas() -> None:
    pantry = PantryExtraction(
        source_type="fridge",
        items=[PantryItem(name="  Mleko 2% ", category=" Nabial ", level="low")],
        summary_note="Kończy się mleko.",
    )
    assert pantry.items[0].name == "mleko 2%"
    assert pantry.items[0].category == "nabial"

    profile = UserProfileOutput(
        profile_markdown="Kupuje głównie w Lidlu.",
        preferred_stores=["lidl"],
        avoided_stores=["biedronka"],
        custom_rules=["bez słodyczy"],
    )
    assert profile.preferred_stores == ["lidl"]
