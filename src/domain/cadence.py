"""Deterministic purchase cadence calculator (pure Python, zero DB coupling).

Implements Section 3B of `docs/PHASE_1_SPEC.md`:
- Groups confirmed purchases by `normalized_name` and calendar day (same-day duplicates count as 1).
- Computes `avg_interval_days`, `days_since_last`, and `urgency_ratio` for products bought on >= 2
  distinct days.
- Flags items with `urgency_ratio >= 0.85` as likely running low / due for restock.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict

from src.domain.schemas import CadenceItem

RESTOCK_URGENCY_THRESHOLD = 0.85
_SECONDS_PER_DAY = 86_400.0


class PurchaseRecord(BaseModel):
    """Minimal confirmed purchase input needed for cadence calculation."""

    model_config = ConfigDict(frozen=True)

    normalized_name: str
    category: str
    purchased_at: datetime


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def calculate_cadence(
    records: Sequence[PurchaseRecord],
    *,
    now: datetime | None = None,
) -> list[CadenceItem]:
    """Calculate purchase intervals and restock urgency from confirmed purchase records.

    Results are sorted by `urgency_ratio` descending, then `purchase_count` descending,
    then `normalized_name` ascending.
    """
    reference_now = _ensure_utc(now) if now is not None else datetime.now(UTC)

    # Map: normalized_name -> {calendar_date -> (latest_dt_that_day, category)}
    grouped: dict[str, dict[date, tuple[datetime, str]]] = defaultdict(dict)

    for record in records:
        name = record.normalized_name.strip().lower()
        if not name:
            continue
        dt_utc = _ensure_utc(record.purchased_at)
        purchase_day = dt_utc.date()
        existing = grouped[name].get(purchase_day)
        if existing is None or dt_utc >= existing[0]:
            grouped[name][purchase_day] = (dt_utc, record.category)

    items: list[CadenceItem] = []

    for name, day_map in grouped.items():
        if len(day_map) < 2:
            continue

        sorted_days = sorted(day_map.keys())
        intervals = [(sorted_days[i] - sorted_days[i - 1]).days for i in range(1, len(sorted_days))]
        avg_interval_days = sum(intervals) / len(intervals)

        last_purchased_at, latest_category = day_map[sorted_days[-1]]
        elapsed_seconds = (reference_now - last_purchased_at).total_seconds()
        days_since_last = max(elapsed_seconds / _SECONDS_PER_DAY, 0.0)
        urgency_ratio = days_since_last / max(avg_interval_days, 1.0)

        items.append(
            CadenceItem(
                normalized_name=name,
                category=latest_category,
                purchase_count=len(sorted_days),
                avg_interval_days=avg_interval_days,
                days_since_last=days_since_last,
                urgency_ratio=urgency_ratio,
                last_purchased_at=last_purchased_at,
            )
        )

    items.sort(key=lambda item: (-item.urgency_ratio, -item.purchase_count, item.normalized_name))
    return items


def get_restock_candidates(
    items: Sequence[CadenceItem],
    *,
    threshold: float = RESTOCK_URGENCY_THRESHOLD,
) -> list[CadenceItem]:
    """Filter cadence items that are likely running low (`urgency_ratio >= threshold`)."""
    return [item for item in items if item.urgency_ratio >= threshold]
