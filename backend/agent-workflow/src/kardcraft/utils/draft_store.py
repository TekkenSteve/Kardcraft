"""Draft Card Store for Redis-based transient storage.

Provides a middle layer between raw generation and final persistence.
Allows for:
1. Streaming partial results to persistent but fast storage.
2. User-in-the-loop editing of semi-finished cards.
3. Iterative optimization by subsequent agents.
"""

import json
from typing import List, Dict, Any, Optional
from kardcraft.services.redis import redis
from kardcraft.utils.logger import logger
from datetime import datetime

class DraftCardStore:
    """Manager for card drafts in Redis."""
    
    def __init__(self, session_id: str, user_id: Optional[str] = None):
        self.session_id = session_id
        self.user_id = user_id
        self.base_key = f"draft:cards:{session_id}"

    async def add_cards(self, cards: List[Dict[str, Any]], ttl: int = 3600):
        """Add cards to the draft store (Redis Hash)."""
        if not cards:
            return
            
        client = await redis.get_client()
        mapping = {
            card["id"]: json.dumps(card) 
            for card in cards
        }
        
        # Use HSET to store multiple cards in one session hash
        await client.hset(self.base_key, mapping=mapping)
        await client.expire(self.base_key, ttl)
        logger.info(f"Added {len(cards)} drafts to Redis", session_id=self.session_id)

        # Mirror drafts into pack workspace so the frontend can fetch via /sessions/{id}/cards
        try:
            from kardcraft.services.pack_workspace import pack_workspace, WorkspaceCard

            pack = await pack_workspace.get_workspace(self.session_id)
            if not pack:
                await pack_workspace.create_workspace(self.session_id)

            workspace_cards: List[WorkspaceCard] = []
            for card in cards:
                workspace_cards.append(
                    WorkspaceCard(
                        temp_id=card.get("id", ""),
                        order=0,
                        model=card.get("model") or card.get("type") or "default",
                        content={
                            "front": card.get("front", ""),
                            "back": card.get("back", ""),
                            "tags": card.get("tags", []),
                            "concepts": card.get("concepts", []),
                        },
                        media=card.get("media", []),
                        version=1,
                        modified_at=datetime.utcnow().isoformat(),
                        status=card.get("status", "draft"),
                    )
                )

            pack = await pack_workspace.add_cards(self.session_id, workspace_cards, source="ai")

            # Publish card updates to user stream for real-time UI updates
            if self.user_id:
                from kardcraft.services.redis import redis as redis_service
                now = datetime.utcnow().isoformat()
                stream_key = f"stream:events:user:{self.user_id}"
                pack_index = {c.get("temp_id"): c for c in (pack.cards or [])}
                for card in workspace_cards:
                    stored = pack_index.get(card.temp_id, {})
                    payload = {
                        "id": card.temp_id,
                        "user_id": self.user_id,
                        "card_id": card.temp_id,
                        "content": {
                            "version": int(stored.get("version", card.version)),
                            "model": stored.get("model", card.model),
                            "data": stored.get("content", card.content),
                            "media": stored.get("media", card.media),
                        },
                        "edit_state": {
                            "status": stored.get("status", card.status),
                            "locked_by": stored.get("locked_by", card.locked_by),
                        },
                        "concepts": [],
                        "meta": {
                            "created_at": stored.get("modified_at", now),
                            "modified_at": stored.get("modified_at", now),
                            "manual_edits": 0,
                        },
                    }
                    await redis_service.stream_add(
                        stream_key=stream_key,
                        fields={
                            "event_type": "CARD_UPDATED",
                            "data": json.dumps(payload),
                        },
                        maxlen=1000,
                        approximate=True,
                        fail_silently=True,
                    )
        except Exception as e:
            logger.warning("Failed to sync drafts to pack workspace", error=str(e))

    async def get_all_cards(self) -> List[Dict[str, Any]]:
        """Get all draft cards for the session."""
        client = await redis.get_client()
        raw_drafts = await client.hgetall(self.base_key)
        
        cards = []
        for card_id, data in raw_drafts.items():
            try:
                cards.append(json.loads(data))
            except Exception as e:
                logger.error(f"Failed to parse draft card {card_id}", error=str(e))
        return cards

    async def update_card(self, card_id: str, updates: Dict[str, Any]):
        """Update a specific card in the draft store."""
        client = await redis.get_client()
        raw_card = await client.hget(self.base_key, card_id)
        if not raw_card:
            return False
            
        card = json.loads(raw_card)
        card.update(updates)
        await client.hset(self.base_key, card_id, json.dumps(card))
        return True

    async def clear(self):
        """Clear all drafts for the session."""
        await redis.delete(self.base_key)
