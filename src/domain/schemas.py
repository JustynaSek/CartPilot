"""Pydantic v2 domain contracts (DTOs shared between agents, services, and domain logic).

Mirrors Section 2 of `docs/PHASE_1_SPEC.md`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ImageType = Literal["receipt", "fridge", "pantry", "groceries", "unsupported"]

ProductCategory = Literal[
    "owoce",
    "warzywa",
    "ryby",
    "mieso",
    "nabial",
    "pieczywo",
    "makarony_i_zboza",
    "slodycze_i_przekaski",
    "napoje",
    "chemia_i_dom",
    "inne",
]

ProductUnit = Literal["szt", "kg", "g", "l", "ml"]

PantryLevel = Literal["high", "medium", "low", "empty"]

PantrySourceType = Literal["fridge", "pantry", "groceries"]


class ImageClassification(BaseModel):
    """Output of the image router agent (`classifier`)."""

    image_type: ImageType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)


class ReceiptItemExtraction(BaseModel):
    """Single line item extracted from a Polish fiscal receipt."""

    raw_name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    category: ProductCategory
    quantity: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))
    unit: ProductUnit = "szt"
    unit_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"))
    total_price: Decimal

    @field_validator("raw_name", mode="before")
    @classmethod
    def _strip_raw_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("normalized_name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate_negative_price_only_for_basket_discount(self) -> "ReceiptItemExtraction":
        # Per PHASE_1_SPEC: regular items must have total_price >= 0; a negative line
        # is only permitted for basket-wide discounts stored under category "inne".
        if self.total_price < Decimal("0") and self.category != "inne":
            raise ValueError(
                "Negative total_price is only allowed for basket-level discounts "
                "in category 'inne'."
            )
        return self


class ReceiptExtraction(BaseModel):
    """Structured output of the receipt OCR agent."""

    store_name: str | None = None
    store_normalized: str | None = None
    purchased_at: datetime | None = None
    total_amount: Decimal | None = None
    items: list[ReceiptItemExtraction] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("store_name", mode="before")
    @classmethod
    def _strip_store_name(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("store_normalized", mode="before")
    @classmethod
    def _normalize_store(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip().lower()
            return stripped or None
        return value


class PantryItem(BaseModel):
    """Single item spotted in a fridge, pantry, or groceries photo."""

    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    level: PantryLevel

    @field_validator("name", "category", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class PantryExtraction(BaseModel):
    """Structured output of the pantry vision agent."""

    source_type: PantrySourceType
    items: list[PantryItem] = Field(default_factory=list)
    summary_note: str


class CadenceItem(BaseModel):
    """Purchase frequency statistics for a single normalized product."""

    normalized_name: str
    category: str
    purchase_count: int = Field(ge=2)
    avg_interval_days: float = Field(gt=0.0)
    days_since_last: float = Field(ge=0.0)
    urgency_ratio: float = Field(ge=0.0)
    last_purchased_at: datetime


class UserProfileOutput(BaseModel):
    """Structured output of the profiler agent."""

    profile_markdown: str
    preferred_stores: list[str] = Field(default_factory=list)
    avoided_stores: list[str] = Field(default_factory=list)
    custom_rules: list[str] = Field(default_factory=list)
