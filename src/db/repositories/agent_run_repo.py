"""Agent run telemetry repository (`agent_runs` table)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentRun


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID | None,
        trigger_type: str,
        agent_name: str,
        model_name: str,
        tokens_in: int,
        tokens_out: int,
        estimated_cost_usd: Decimal,
        latency_ms: int,
        status: str = "success",
        error_message: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            user_id=user_id,
            trigger_type=trigger_type,
            agent_name=agent_name,
            model_name=model_name[:80],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def sum_cost_last_days(
        self,
        user_id: uuid.UUID,
        *,
        days: int = 30,
        now: datetime | None = None,
    ) -> Decimal:
        """Total estimated API spend (USD) for a user in the last `days` days."""
        since = (now or datetime.now(UTC)) - timedelta(days=days)
        stmt = select(func.coalesce(func.sum(AgentRun.estimated_cost_usd), 0)).where(
            AgentRun.user_id == user_id,
            AgentRun.created_at >= since,
        )
        total = await self._session.scalar(stmt)
        return Decimal(str(total))
