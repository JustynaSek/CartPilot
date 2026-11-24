"""Offline checks: ORM metadata mirrors docs/SCHEMA.sql (no database required)."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from src.db.models import Base

EXPECTED_TABLES = {
    "users",
    "user_profiles",
    "receipts",
    "receipt_items",
    "pantry_snapshots",
    "offers",
    "agent_runs",
}


def _ddl(table_name: str) -> str:
    table = Base.metadata.tables[table_name]
    dialect = postgresql.dialect()
    parts = [str(CreateTable(table).compile(dialect=dialect))]
    parts += [str(CreateIndex(ix).compile(dialect=dialect)) for ix in table.indexes]
    return "\n".join(parts)


def test_all_schema_tables_are_mapped() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_receipt_items_has_vector_column_and_hnsw_index() -> None:
    ddl = _ddl("receipt_items")
    assert "embedding VECTOR(768)" in ddl
    assert "USING hnsw (embedding vector_cosine_ops)" in ddl


def test_check_constraint_names_match_postgres_defaults() -> None:
    assert "CONSTRAINT receipts_status_check CHECK" in _ddl("receipts")
    assert "CONSTRAINT pantry_snapshots_source_type_check CHECK" in _ddl("pantry_snapshots")
    assert "CONSTRAINT agent_runs_status_check CHECK" in _ddl("agent_runs")


def test_descending_indexes() -> None:
    assert "(user_id, purchased_at DESC)" in _ddl("receipts")
    assert "(user_id, created_at DESC)" in _ddl("agent_runs")


def test_agent_runs_user_fk_is_set_null() -> None:
    assert "ON DELETE SET NULL" in _ddl("agent_runs")
