"""Deterministic receipt math & validation (feeds the Reflection loop in IngestionService).

Never delegates arithmetic to an LLM: all sums and tolerances use exact `Decimal`.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.schemas import ReceiptExtraction

SUM_TOLERANCE_PLN = Decimal("0.50")
_TWO_PLACES = Decimal("0.01")


class ReceiptValidationResult(BaseModel):
    """Outcome of deterministic validation for a single `ReceiptExtraction`."""

    model_config = ConfigDict(frozen=True)

    is_valid: bool
    computed_sum: Decimal
    sum_diff: Decimal
    errors: list[str] = Field(default_factory=list)
    reflection_feedback: str | None = None

    @property
    def needs_reflection(self) -> bool:
        return not self.is_valid


def validate_receipt(
    extraction: ReceiptExtraction,
    *,
    tolerance: Decimal = SUM_TOLERANCE_PLN,
) -> ReceiptValidationResult:
    """Validate receipt totals and required header fields.

    Returns a `ReceiptValidationResult` with exact `Decimal` sums and, when invalid,
    a Polish diagnostic prompt (`reflection_feedback`) ready for the Reflection retry.
    """
    computed_sum = sum(
        (item.total_price for item in extraction.items),
        Decimal("0.00"),
    ).quantize(_TWO_PLACES)

    errors: list[str] = []

    if not extraction.items:
        errors.append("Brak odczytanych pozycji na paragonie.")

    if not extraction.store_name:
        errors.append("Brak nazwy sklepu na paragonie.")

    if extraction.purchased_at is None:
        errors.append("Brak daty i godziny zakupu na paragonie.")

    if extraction.total_amount is None:
        sum_diff = Decimal("0.00")
        errors.append("Brak kwoty końcowej (SUMA PLN) na paragonie.")
    else:
        total_amount = extraction.total_amount.quantize(_TWO_PLACES)
        sum_diff = abs(total_amount - computed_sum).quantize(_TWO_PLACES)
        if sum_diff > tolerance:
            errors.append(
                f"Suma Twoich pozycji to {computed_sum:.2f} PLN, ale SUMA PLN na paragonie "
                f"to {total_amount:.2f} PLN. Różnica wynosi {sum_diff:.2f} PLN "
                f"(próg tolerancji: {tolerance:.2f} PLN). Sprawdź pominięte linie "
                f"OPUST/RABAT lub błędnie odczytane kwoty."
            )

    is_valid = len(errors) == 0
    reflection_feedback = " ".join(errors) if errors else None

    return ReceiptValidationResult(
        is_valid=is_valid,
        computed_sum=computed_sum,
        sum_diff=sum_diff,
        errors=errors,
        reflection_feedback=reflection_feedback,
    )
