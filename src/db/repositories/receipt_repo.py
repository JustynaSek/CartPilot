"""Receipt & receipt item repository (multi-tenant, SQLAlchemy 2.0 async)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Receipt, ReceiptItem
from src.domain.cadence import PurchaseRecord
from src.domain.receipt_math import ReceiptValidationResult
from src.domain.schemas import ReceiptExtraction

ReceiptStatus = Literal["pending_review", "confirmed", "rejected"]


class ReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_with_items(
        self,
        *,
        user_id: uuid.UUID,
        extraction: ReceiptExtraction,
        validation: ReceiptValidationResult,
        status: ReceiptStatus,
        embeddings: Sequence[list[float] | None] | None = None,
    ) -> Receipt:
        """Persist a receipt header and all line items (with optional 768-dim embeddings)."""
        receipt = Receipt(
            user_id=user_id,
            store_name=(extraction.store_name or "Nieznany sklep")[:120],
            store_normalized=(extraction.store_normalized or "inne")[:80],
            purchased_at=extraction.purchased_at or datetime.now(UTC),
            total_amount=(
                extraction.total_amount
                if extraction.total_amount is not None
                else validation.computed_sum
            ),
            computed_sum=validation.computed_sum,
            sum_diff=validation.sum_diff,
            needs_review=status == "pending_review",
            review_reason=validation.reflection_feedback if status == "pending_review" else None,
            status=status,
            raw_extraction=extraction.model_dump(mode="json"),
        )
        self._session.add(receipt)
        await self._session.flush()  # populate receipt.id before creating items

        item_embeddings = (
            list(embeddings) if embeddings is not None else [None] * len(extraction.items)
        )
        for item, vector in zip(extraction.items, item_embeddings, strict=True):
            self._session.add(
                ReceiptItem(
                    receipt_id=receipt.id,
                    user_id=user_id,
                    raw_name=item.raw_name[:255],
                    normalized_name=item.normalized_name[:160],
                    category=item.category[:60],
                    quantity=item.quantity,
                    unit=item.unit[:20],
                    unit_price=item.unit_price,
                    discount_amount=item.discount_amount,
                    total_price=item.total_price,
                    embedding=vector,
                )
            )
        await self._session.flush()
        return receipt

    async def get_by_id_for_user(
        self,
        receipt_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Receipt | None:
        stmt = select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user_id)
        return await self._session.scalar(stmt)

    async def update_status(
        self,
        receipt_id: uuid.UUID,
        user_id: uuid.UUID,
        status: ReceiptStatus,
    ) -> Receipt | None:
        receipt = await self.get_by_id_for_user(receipt_id, user_id)
        if receipt is None:
            return None
        receipt.status = status
        receipt.needs_review = status == "pending_review"
        await self._session.flush()
        return receipt

    async def list_confirmed_purchase_records(self, user_id: uuid.UUID) -> list[PurchaseRecord]:
        """Return confirmed line items formatted for `src.domain.cadence.calculate_cadence`."""
        stmt = (
            select(ReceiptItem.normalized_name, ReceiptItem.category, Receipt.purchased_at)
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .where(
                ReceiptItem.user_id == user_id,
                Receipt.user_id == user_id,
                Receipt.status == "confirmed",
            )
            .order_by(Receipt.purchased_at.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            PurchaseRecord(
                normalized_name=row.normalized_name,
                category=row.category,
                purchased_at=row.purchased_at,
            )
            for row in rows
        ]

    async def sum_confirmed_spend_last_days(
        self,
        user_id: uuid.UUID,
        *,
        since: datetime,
    ) -> Decimal:
        from sqlalchemy import func

        stmt = select(func.coalesce(func.sum(Receipt.total_amount), 0)).where(
            Receipt.user_id == user_id,
            Receipt.status == "confirmed",
            Receipt.purchased_at >= since,
        )
        total = await self._session.scalar(stmt)
        return Decimal(str(total))
