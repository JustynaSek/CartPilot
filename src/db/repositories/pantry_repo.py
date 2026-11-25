"""Pantry snapshot repository (`pantry_snapshots` table, multi-tenant)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PantrySnapshot
from src.domain.schemas import PantryExtraction


class PantryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_snapshot(
        self,
        *,
        user_id: uuid.UUID,
        extraction: PantryExtraction,
    ) -> PantrySnapshot:
        snapshot = PantrySnapshot(
            user_id=user_id,
            source_type=extraction.source_type,
            detected_items=[item.model_dump(mode="json") for item in extraction.items],
            summary_note=extraction.summary_note,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def get_latest(self, user_id: uuid.UUID) -> PantrySnapshot | None:
        stmt = (
            select(PantrySnapshot)
            .where(PantrySnapshot.user_id == user_id)
            .order_by(PantrySnapshot.captured_at.desc())
            .limit(1)
        )
        return await self._session.scalar(stmt)
