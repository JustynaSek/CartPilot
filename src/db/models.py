"""SQLAlchemy 2.0 ORM models — mirror of `docs/SCHEMA.sql` (source of truth)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 768

# Constraint names identical to PostgreSQL defaults, so the ORM metadata matches
# what plain `docs/SCHEMA.sql` would create (and Alembic autogenerate stays quiet).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

RECEIPT_STATUSES = ("pending_review", "confirmed", "rejected")
PANTRY_SOURCE_TYPES = ("fridge", "pantry", "groceries")
AGENT_RUN_STATUSES = ("success", "retry", "error")


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Default Python -> SQL type mapping for `Mapped[...]` annotations.
    type_annotation_map = {
        datetime: DateTime(timezone=True),  # TIMESTAMPTZ
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# 1. Users (multi-tenant + whitelist + cost guard)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(server_default=text("false"))
    daily_image_limit: Mapped[int] = mapped_column(server_default=text("15"))
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # lazy="raise": in async code implicit lazy loading is forbidden anyway;
    # this makes the error explicit — load with `selectinload()` or `awaitable_attrs`.
    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )
    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="user", lazy="raise", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# 2. Semantic memory layer: living shopping profile
# ---------------------------------------------------------------------------
class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    profile_markdown: Mapped[str] = mapped_column(Text, server_default=text("''"))
    preferred_stores: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    avoided_stores: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    custom_rules: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    receipts_since_last_update: Mapped[int] = mapped_column(server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="profile", lazy="raise")


# ---------------------------------------------------------------------------
# 3. Transactional layer: receipt headers
# ---------------------------------------------------------------------------
class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (CheckConstraint(_in_check("status", RECEIPT_STATUSES), name="status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    store_name: Mapped[str] = mapped_column(String(120))
    store_normalized: Mapped[str] = mapped_column(String(80))
    purchased_at: Mapped[datetime]
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'PLN'"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    computed_sum: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    sum_diff: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("0.00"))
    needs_review: Mapped[bool] = mapped_column(server_default=text("false"))
    review_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), server_default=text("'confirmed'"))
    raw_extraction: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()

    user: Mapped[User] = relationship(back_populates="receipts", lazy="raise")
    items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="receipt",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


Index("idx_receipts_user_date", Receipt.user_id, Receipt.purchased_at.desc())
Index("idx_receipts_user_status", Receipt.user_id, Receipt.status)


# ---------------------------------------------------------------------------
# 4. Receipt line items + vector layer (pgvector)
# ---------------------------------------------------------------------------
class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    raw_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), server_default=text("1.000"))
    unit: Mapped[str] = mapped_column(String(20), server_default=text("'szt'"))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("0.00"))
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = _created_at()

    receipt: Mapped[Receipt] = relationship(back_populates="items", lazy="raise")


Index("idx_receipt_items_user_norm", ReceiptItem.user_id, ReceiptItem.normalized_name)
Index("idx_receipt_items_user_cat", ReceiptItem.user_id, ReceiptItem.category)
Index("idx_receipt_items_receipt", ReceiptItem.receipt_id)
Index(
    "idx_receipt_items_embedding",
    ReceiptItem.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)


# ---------------------------------------------------------------------------
# 5. Fridge / pantry / groceries snapshots
# ---------------------------------------------------------------------------
class PantrySnapshot(Base):
    __tablename__ = "pantry_snapshots"
    __table_args__ = (
        CheckConstraint(_in_check("source_type", PANTRY_SOURCE_TYPES), name="source_type"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(24), server_default=text("'fridge'"))
    captured_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Element format: {"name": "mleko", "category": "nabial", "level": "low|medium|high|empty"}
    detected_items: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    summary_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


Index("idx_pantry_user_captured", PantrySnapshot.user_id, PantrySnapshot.captured_at.desc())


# ---------------------------------------------------------------------------
# 6. [PHASE 2] Shared promotions table (created now, populated in Phase 2)
# ---------------------------------------------------------------------------
class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    store_name: Mapped[str] = mapped_column(String(80))
    product_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(60))
    promo_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    regular_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit_price_normalized: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit: Mapped[str] = mapped_column(String(20), server_default=text("'szt'"))
    conditions: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    source_hash: Mapped[str] = mapped_column(String(64), unique=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = _created_at()


Index("idx_offers_store_dates", Offer.store_name, Offer.valid_from, Offer.valid_to)
Index(
    "idx_offers_embedding",
    Offer.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)


# ---------------------------------------------------------------------------
# 7. LLM call telemetry & cost control
# ---------------------------------------------------------------------------
class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (CheckConstraint(_in_check("status", AGENT_RUN_STATUSES), name="status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    trigger_type: Mapped[str] = mapped_column(String(32))
    agent_name: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(80))
    tokens_in: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    tokens_out: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), server_default=text("0.000000")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(24), server_default=text("'success'"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


Index("idx_agent_runs_user_date", AgentRun.user_id, AgentRun.created_at.desc())
