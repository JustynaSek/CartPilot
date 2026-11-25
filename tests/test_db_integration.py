"""Integration smoke test against the real Docker PostgreSQL.

Skipped automatically when the database is not reachable, so `uv run pytest`
stays green on machines without Docker. Run `docker compose up -d` and
`uv run alembic upgrade head` first to exercise it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import get_settings

pytestmark = pytest.mark.integration


async def test_migrated_schema_and_pgvector() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        try:
            conn_cm = await engine.connect().start()
        except (OSError, TimeoutError) as exc:  # connection refused / host unreachable
            pytest.skip(f"PostgreSQL not reachable: {exc.__class__.__name__}")

        async with conn_cm as conn:
            ext = await conn.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
            assert ext is not None, "pgvector extension missing — run `alembic upgrade head`"

            tables = set(
                (
                    await conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    )
                ).scalars()
            )
            assert {"users", "receipts", "receipt_items", "agent_runs"} <= tables

            distance = await conn.scalar(text("SELECT '[1,0]'::vector <=> '[0,1]'::vector"))
            assert distance == pytest.approx(1.0)  # orthogonal vectors -> cosine distance 1
    finally:
        await engine.dispose()
