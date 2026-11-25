"""Unit tests for deterministic purchase cadence (`src/domain/cadence.py`)."""

from datetime import UTC, datetime

import pytest

from src.domain.cadence import (
    RESTOCK_URGENCY_THRESHOLD,
    PurchaseRecord,
    calculate_cadence,
    get_restock_candidates,
)


def _rec(name: str, day: int, *, hour: int = 12, category: str = "nabial") -> PurchaseRecord:
    return PurchaseRecord(
        normalized_name=name,
        category=category,
        purchased_at=datetime(2026, 11, day, hour, 0, tzinfo=UTC),
    )


def test_single_purchase_is_excluded() -> None:
    records = [_rec("mleko 2%", day=1)]
    assert calculate_cadence(records, now=datetime(2026, 11, 10, 12, 0, tzinfo=UTC)) == []


def test_same_day_duplicate_purchases_count_as_one_day() -> None:
    # Two milk cartons on the same day (or two receipts on the same day) -> still 1 day.
    records = [
        _rec("mleko 2%", day=5, hour=9),
        _rec("mleko 2%", day=5, hour=18),
    ]
    assert calculate_cadence(records, now=datetime(2026, 11, 10, 12, 0, tzinfo=UTC)) == []


def test_avg_interval_and_urgency_ratio_calculation() -> None:
    # Bought on Nov 1, Nov 5 (4 days), Nov 11 (6 days) -> avg_interval = 5.0 days.
    # Duplicate on Nov 5 should not distort the interval.
    records = [
        _rec("mleko 2%", day=1),
        _rec("mleko 2%", day=5, hour=10),
        _rec("Mleko 2% ", day=5, hour=17),
        _rec("mleko 2%", day=11, hour=12),
    ]
    now = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)  # 4.5 days after Nov 11 12:00

    items = calculate_cadence(records, now=now)
    assert len(items) == 1
    milk = items[0]
    assert milk.normalized_name == "mleko 2%"
    assert milk.purchase_count == 3
    assert milk.avg_interval_days == pytest.approx(5.0)
    assert milk.days_since_last == pytest.approx(4.5)
    assert milk.urgency_ratio == pytest.approx(0.9)  # 4.5 / 5.0 >= 0.85
    assert milk.last_purchased_at == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def test_restock_candidates_and_sorting_by_urgency() -> None:
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    records = [
        # Bananas: bought every 4 days (Nov 10, Nov 14), last 6 days ago -> urgency = 1.5
        _rec("banan", day=10, category="owoce"),
        _rec("banan", day=14, category="owoce"),
        # Bread: bought every 2 days (Nov 16, Nov 18), last 2 days ago -> urgency = 1.0
        _rec("chleb", day=16, category="pieczywo"),
        _rec("chleb", day=18, category="pieczywo"),
        # Olive oil: bought every 10 days (Nov 8, Nov 18), last 2 days ago -> urgency = 0.2
        _rec("oliwa", day=8, category="inne"),
        _rec("oliwa", day=18, category="inne"),
    ]

    all_items = calculate_cadence(records, now=now)
    assert [i.normalized_name for i in all_items] == ["banan", "chleb", "oliwa"]

    candidates = get_restock_candidates(all_items)
    assert [c.normalized_name for c in candidates] == ["banan", "chleb"]
    assert all(c.urgency_ratio >= RESTOCK_URGENCY_THRESHOLD for c in candidates)


def test_naive_datetimes_are_handled_as_utc_without_type_error() -> None:
    records = [
        PurchaseRecord(
            normalized_name="jajka",
            category="nabial",
            purchased_at=datetime(2026, 11, 1, 10, 0),  # naive
        ),
        PurchaseRecord(
            normalized_name="jajka",
            category="nabial",
            purchased_at=datetime(2026, 11, 8, 10, 0),  # naive
        ),
    ]
    items = calculate_cadence(records, now=datetime(2026, 11, 15, 10, 0, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].avg_interval_days == pytest.approx(7.0)
    assert items[0].urgency_ratio == pytest.approx(1.0)
