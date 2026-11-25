"""User profile repository (`user_profiles` table, multi-tenant)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import UserProfile
from src.domain.schemas import UserProfileOutput


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, user_id: uuid.UUID) -> UserProfile:
        profile = await self._session.get(UserProfile, user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self._session.add(profile)
            await self._session.flush()
        return profile

    async def save_profile(
        self,
        user_id: uuid.UUID,
        output: UserProfileOutput,
        *,
        reset_counter: bool = True,
    ) -> UserProfile:
        profile = await self.get_or_create(user_id)
        profile.profile_markdown = output.profile_markdown
        profile.preferred_stores = list(output.preferred_stores)
        profile.avoided_stores = list(output.avoided_stores)
        profile.custom_rules = list(output.custom_rules)
        if reset_counter:
            profile.receipts_since_last_update = 0
        await self._session.flush()
        return profile

    async def increment_receipts_counter(self, user_id: uuid.UUID) -> int:
        profile = await self.get_or_create(user_id)
        profile.receipts_since_last_update += 1
        await self._session.flush()
        return profile.receipts_since_last_update
