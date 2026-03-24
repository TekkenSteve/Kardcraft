"""
Card Repository - Single source of truth for card operations.
Handles versioning, locking, and integrates with Redis for fast locking.
"""

import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.models import Card, CardVersion, EditStatus, CardModel
from ..services.redis import redis
from ..utils.logger import logger


class CardRepository:
    """
    Repository for card operations.
    Uses PostgreSQL as source of truth, Redis for fast lock acquisition.
    """

    LOCK_TTL_AI = 120  # 2 minutes for AI
    LOCK_TTL_USER = 300  # 5 minutes for user

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    def _normalize_card_model(self, model: Any) -> CardModel:
        """Normalize model input to CardModel enum."""
        if isinstance(model, CardModel):
            return model
        if not model:
            return CardModel.BASIC

        if isinstance(model, str):
            raw = model.strip()
            if not raw:
                return CardModel.BASIC

            # Match by enum value (case-insensitive)
            raw_lower = raw.lower()
            for item in CardModel:
                if item.value.lower() == raw_lower:
                    return item

            # Match by enum name (case-insensitive)
            try:
                return CardModel[raw.upper()]
            except KeyError:
                return CardModel.BASIC

        return CardModel.BASIC

    # ========== Redis Lock Operations ==========

    async def _acquire_redis_lock(self, card_id: str, actor: str, ttl: int) -> bool:
        """Fast path: acquire lock in Redis."""
        lock_key = f"card:lock:{card_id}"

        # Try to acquire with NX (only if not exists)
        acquired = await redis.set(lock_key, actor, ex=ttl, nx=True)
        return bool(acquired)

    async def _release_redis_lock(self, card_id: str, actor: str) -> bool:
        """Release Redis lock (only if owned by actor)."""
        lock_key = f"card:lock:{card_id}"

        # Lua script for atomic check-and-delete
        # Only delete if the value matches
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            client = await redis.get_client()
            result = await client.eval(script, 1, lock_key, actor)
            return bool(result)
        except Exception as e:
            logger.warning(f"Redis lock release failed: {e}")
            # Fallback: just delete
            await redis.delete(lock_key)
            return False

    async def _refresh_redis_lock(self, card_id: str, actor: str, ttl: int) -> bool:
        """Extend lock TTL if we own it."""
        lock_key = f"card:lock:{card_id}"

        # Lua script for atomic check-and-extend
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            client = await redis.get_client()
            result = await client.eval(script, 1, lock_key, actor, ttl)
            return bool(result)
        except Exception:
            return False

    # ========== Card CRUD ==========

    async def create_card(
        self,
        user_id: str,
        model: str,
        data: Dict[str, Any],
        concepts: List[str] = None,
        media: List[Dict] = None,
        comment: str = "Initial version",
    ) -> Card:
        """Create a new card."""
        card_id = f"c-{uuid.uuid4()}"
        now = datetime.utcnow()

        card = Card(
            user_id=user_id,
            card_id=card_id,
            version=1,
            model=self._normalize_card_model(model),
            data=data,
            media=media or [],
            concepts=concepts or [],
            edit_status=EditStatus.DRAFT,
            created_at=now,
            modified_at=now,
        )

        self.db.add(card)
        await self.db.flush()

        # Create initial version record
        version = CardVersion(
            card_id=card.id,
            version=1,
            diff=data,  # Initial version has full data as diff
            data_snapshot=data,
            changed_by="system",
            change_comment=comment,
            created_at=now,
        )
        self.db.add(version)

        logger.info(f"Created card {card_id} for user {user_id}")
        return card

    async def get_card(self, card_id: str, user_id: str) -> Optional[Card]:
        """Get a card by card_id."""
        result = await self.db.execute(
            select(Card).where(
                and_(
                    Card.card_id == card_id,
                    Card.user_id == user_id,
                    Card.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_cards(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> List[Card]:
        """Get user's cards with pagination."""
        result = await self.db.execute(
            select(Card)
            .where(and_(Card.user_id == user_id, Card.deleted_at.is_(None)))
            .order_by(Card.modified_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_cards(self, user_id: Optional[str] = None) -> int:
        """Count non-deleted cards, optionally scoped to a user."""
        stmt = select(func.count(Card.id)).where(Card.deleted_at.is_(None))
        if user_id:
            stmt = stmt.where(Card.user_id == user_id)
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    # ========== Lock Operations ==========

    async def acquire_lock(
        self, card_id: str, user_id: str, actor: str, is_ai: bool = False
    ) -> bool:
        """
        Acquire editing lock for a card.
        Returns True if lock acquired, False if already locked.
        """
        ttl = self.LOCK_TTL_AI if is_ai else self.LOCK_TTL_USER
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl)

        # 1. Fast path: Try Redis first
        redis_acquired = await self._acquire_redis_lock(card_id, actor, ttl)

        if not redis_acquired:
            # Check if it's our own lock (refreshing)
            current_lock = await redis.get(f"card:lock:{card_id}")
            if current_lock != actor:
                logger.debug(f"Card {card_id} locked by {current_lock}")
                return False

        # 2. Persist to PostgreSQL
        result = await self.db.execute(
            update(Card)
            .where(
                and_(
                    Card.card_id == card_id,
                    Card.user_id == user_id,
                    or_(Card.locked_by.is_(None), Card.expires_at < now),
                    Card.deleted_at.is_(None),
                )
            )
            .values(
                edit_status=EditStatus.AI_EDITING if is_ai else EditStatus.USER_EDITING,
                locked_by=actor,
                locked_at=now,
                expires_at=expires_at,
            )
        )

        if result.rowcount == 0:
            # PostgreSQL says no, release Redis
            await self._release_redis_lock(card_id, actor)
            logger.debug(f"Card {card_id} lock denied by PostgreSQL")
            return False

        logger.info(f"Lock acquired on {card_id} by {actor}")
        return True

    async def release_lock(self, card_id: str, user_id: str, actor: str) -> bool:
        """Release editing lock."""
        # 1. Release Redis
        redis_released = await self._release_redis_lock(card_id, actor)

        # 2. Update PostgreSQL (only if we own it)
        result = await self.db.execute(
            update(Card)
            .where(
                and_(
                    Card.card_id == card_id,
                    Card.user_id == user_id,
                    Card.locked_by == actor,
                )
            )
            .values(
                edit_status=EditStatus.CONFIRMED,
                locked_by=None,
                locked_at=None,
                expires_at=None,
            )
        )

        released = result.rowcount > 0
        if released:
            logger.info(f"Lock released on {card_id} by {actor}")
        return released

    async def refresh_lock(self, card_id: str, actor: str, is_ai: bool = True) -> bool:
        """Extend lock TTL."""
        ttl = self.LOCK_TTL_AI if is_ai else self.LOCK_TTL_USER

        # Refresh Redis
        redis_refreshed = await self._refresh_redis_lock(card_id, actor, ttl)

        if not redis_refreshed:
            return False

        # Extend PostgreSQL
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl)

        result = await self.db.execute(
            update(Card)
            .where(and_(Card.card_id == card_id, Card.locked_by == actor))
            .values(expires_at=expires_at)
        )

        return result.rowcount > 0

    # ========== Version & Change Operations ==========

    async def apply_change(
        self,
        card_id: str,
        user_id: str,
        actor: str,
        new_data: Dict[str, Any],
        comment: str = "",
    ) -> Card:
        """
        Apply a change to a card with optimistic locking.
        Increments version and creates history entry.
        """
        # Get current card
        card = await self.get_card(card_id, user_id)
        if not card:
            raise ValueError(f"Card {card_id} not found")

        # Verify lock
        now = datetime.utcnow()
        if card.locked_by != actor:
            if card.expires_at and card.expires_at > now:
                raise PermissionError(f"Card is locked by {card.locked_by}")
            # Lock expired, proceed

        # Calculate diff (simple version - just store new data)
        old_data = card.data

        # Increment version
        new_version = card.version + 1
        is_ai = actor.startswith("ai:")

        # Update card
        card.version = new_version
        card.data = new_data
        card.modified_at = now
        card.edit_status = EditStatus.CONFIRMED

        if not is_ai:
            card.manual_edits += 1

        # Create version history
        version_entry = CardVersion(
            card_id=card.id,
            version=new_version,
            diff={"old": old_data, "new": new_data},  # Simple diff
            data_snapshot=new_data,
            changed_by=actor,
            change_comment=comment,
            created_at=now,
        )
        self.db.add(version_entry)

        # Release lock after successful update
        await self.release_lock(card_id, user_id, actor)

        logger.info(f"Applied change to {card_id}: v{new_version} by {actor}")
        return card

    async def get_version_history(
        self, card_id: str, user_id: str, limit: int = 10
    ) -> List[CardVersion]:
        """Get version history for a card."""
        card = await self.get_card(card_id, user_id)
        if not card:
            return []

        result = await self.db.execute(
            select(CardVersion)
            .where(CardVersion.card_id == card.id)
            .order_by(CardVersion.version.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def soft_delete(self, card_id: str, user_id: str) -> bool:
        """Soft delete a card."""
        result = await self.db.execute(
            update(Card)
            .where(
                and_(
                    Card.card_id == card_id,
                    Card.user_id == user_id,
                    Card.deleted_at.is_(None),
                )
            )
            .values(deleted_at=datetime.utcnow())
        )

        if result.rowcount > 0:
            # Release any locks
            await self._release_redis_lock(card_id, "*")

        return result.rowcount > 0


# ========== Helper Functions ==========


async def get_card_repository() -> CardRepository:
    """Get a card repository instance with DB session."""
    from ..db.postgres import postgres

    async with postgres.session() as session:
        yield CardRepository(session)


__all__ = ["CardRepository"]
