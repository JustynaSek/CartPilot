"""User repository (SQLAlchemy 2.0 async) — whitelist & daily image limit queries."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentRun, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self._session.scalar(stmt)

    async def get_or_create(
        self,
        telegram_id: int,
        display_name: str,
        *,
        is_active: bool = False,
    ) -> tuple[User, bool]:
        """Return `(user, created)`. If user exists and `is_active` is True, activates them."""
        existing = await self.get_by_telegram_id(telegram_id)
        if existing is not None:
            if is_active and not existing.is_active:
                existing.is_active = True
                await self._session.flush()
            return existing, False

        user = User(
            telegram_id=telegram_id,
            display_name=display_name[:120],
            is_active=is_active,
        )
        self._session.add(user)
        await self._session.flush()
        return user, True

    async def count_photos_today(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> int:
        """Count photo ingestion attempts today (UTC) via classifier runs in `agent_runs`."""
        reference_now = now or datetime.now(UTC)
        day_start = reference_now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user_id,
            AgentRun.trigger_type == "telegram_photo",
            AgentRun.agent_name == "classifier",
            AgentRun.created_at >= day_start,
        )
        count = await self._session.scalar(stmt)
        return int(count or 0)
