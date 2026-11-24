"""initial schema: users, profiles, receipts, items, pantry, offers, agent_runs

Mirrors `docs/SCHEMA.sql` (source of truth), including the pgvector extension,
vector(768) embedding columns and HNSW cosine indexes.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-24 13:15:00

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # Extensions must exist before any `vector` column / gen_random_uuid() default.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1. users
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("daily_image_limit", sa.Integer(), server_default=sa.text("15"), nullable=False),
        sa.Column(
            "notification_prefs",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        sa.UniqueConstraint("telegram_id", name="users_telegram_id_key"),
    )

    # 2. user_profiles
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("profile_markdown", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "preferred_stores",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "avoided_stores",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "custom_rules",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "receipts_since_last_update", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="user_profiles_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name="user_profiles_pkey"),
    )

    # 3. receipts
    op.create_table(
        "receipts",
        _uuid_pk(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_name", sa.String(120), nullable=False),
        sa.Column("store_normalized", sa.String(80), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.CHAR(3), server_default=sa.text("'PLN'"), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("computed_sum", sa.Numeric(10, 2), nullable=False),
        sa.Column("sum_diff", sa.Numeric(10, 2), server_default=sa.text("0.00"), nullable=False),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), server_default=sa.text("'confirmed'"), nullable=False),
        sa.Column(
            "raw_extraction",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('pending_review', 'confirmed', 'rejected')",
            name=op.f("receipts_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="receipts_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="receipts_pkey"),
    )
    op.create_index("idx_receipts_user_date", "receipts", ["user_id", sa.text("purchased_at DESC")])
    op.create_index("idx_receipts_user_status", "receipts", ["user_id", "status"])

    # 4. receipt_items (+ vector layer)
    op.create_table(
        "receipt_items",
        _uuid_pk(),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("raw_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 3), server_default=sa.text("1.000"), nullable=False),
        sa.Column("unit", sa.String(20), server_default=sa.text("'szt'"), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "discount_amount", sa.Numeric(10, 2), server_default=sa.text("0.00"), nullable=False
        ),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            name="receipt_items_receipt_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="receipt_items_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="receipt_items_pkey"),
    )
    op.create_index("idx_receipt_items_user_norm", "receipt_items", ["user_id", "normalized_name"])
    op.create_index("idx_receipt_items_user_cat", "receipt_items", ["user_id", "category"])
    op.create_index("idx_receipt_items_receipt", "receipt_items", ["receipt_id"])
    op.create_index(
        "idx_receipt_items_embedding",
        "receipt_items",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # 5. pantry_snapshots
    op.create_table(
        "pantry_snapshots",
        _uuid_pk(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(24), server_default=sa.text("'fridge'"), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "detected_items",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("summary_note", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "source_type IN ('fridge', 'pantry', 'groceries')",
            name=op.f("pantry_snapshots_source_type_check"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="pantry_snapshots_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pantry_snapshots_pkey"),
    )
    op.create_index(
        "idx_pantry_user_captured", "pantry_snapshots", ["user_id", sa.text("captured_at DESC")]
    )

    # 6. offers [Phase 2 — table created now, populated later]
    op.create_table(
        "offers",
        _uuid_pk(),
        sa.Column("store_name", sa.String(80), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("promo_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("regular_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit_price_normalized", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit", sa.String(20), server_default=sa.text("'szt'"), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="offers_pkey"),
        sa.UniqueConstraint("source_hash", name="offers_source_hash_key"),
    )
    op.create_index("idx_offers_store_dates", "offers", ["store_name", "valid_from", "valid_to"])
    op.create_index(
        "idx_offers_embedding",
        "offers",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # 7. agent_runs
    op.create_table(
        "agent_runs",
        _uuid_pk(),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(80), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(10, 6),
            server_default=sa.text("0.000000"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(24), server_default=sa.text("'success'"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('success', 'retry', 'error')", name=op.f("agent_runs_status_check")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="agent_runs_user_id_fkey", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="agent_runs_pkey"),
    )
    op.create_index(
        "idx_agent_runs_user_date", "agent_runs", ["user_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    # Reverse dependency order. Extensions are intentionally left installed
    # (they may be shared with other schemas and dropping them is not reversible-safe).
    op.drop_table("agent_runs")
    op.drop_table("offers")
    op.drop_table("pantry_snapshots")
    op.drop_table("receipt_items")
    op.drop_table("receipts")
    op.drop_table("user_profiles")
    op.drop_table("users")
