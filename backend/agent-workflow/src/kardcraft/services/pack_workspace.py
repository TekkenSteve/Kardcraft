"""
Redis Pack Workspace - Temporal Workflow 的工作区存储

设计原则：
- Workflow 拥有状态，所有操作通过 Activity 修改 Redis
- PostgreSQL 只是最终归档（快照）
- 支持实时协作：WebSocket 订阅 Redis 变更
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from ..services.redis import redis
from ..utils.logger import logger


@dataclass
class WorkspaceCard:
    """工作区中的卡片（Redis 存储格式）"""

    temp_id: str  # 工作区内唯一ID (如 "c-1", "c-2")
    order: int  # 显示顺序

    # 内容
    model: str  # Basic | Cloze | IR | Reverse
    content: Dict[str, Any]  # {front, back, tags, concepts, ...}
    media: List[Dict]  # [{file_id, type, url}]

    # 版本
    version: int  # 乐观锁版本号
    modified_at: str  # ISO timestamp

    # 编辑状态
    status: str = "draft"  # draft | ai_editing | user_editing | confirmed

    # 锁状态
    locked_by: Optional[str] = None  # "ai:session-abc" | "user:socket-xyz"
    locked_at: Optional[str] = None
    lock_expires: Optional[str] = None

    # 标记
    user_modified: bool = False  # 用户是否手动编辑过
    ai_suggestions: int = 0  # AI 建议次数

    # 原始来源（用于追溯）
    source_doc: Optional[str] = None  # 来源文档ID
    source_range: Optional[Dict] = None  # {start, end} 文本范围

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "WorkspaceCard":
        return cls(**data)


@dataclass
class PackWorkspace:
    """
    会话工作区 - Redis 中的 pack 结构

    存储键: pack:session:{session_id}
    """

    session_id: str
    version: int = 0  # 工作区版本（每次变更+1）
    status: str = "active"  # active | paused | finalizing | committed
    created_at: str = ""
    modified_at: str = ""

    # 卡片
    cards: List[Dict[str, Any]] = None

    # 关系图谱（工作区内）
    relations: List[Dict] = None  # [{from, to, type, strength}]

    # AI 状态
    ai_state: Dict[str, Any] = None  # {current_task, pending_suggestions, ...}

    def __post_init__(self):
        if self.cards is None:
            self.cards = []
        if self.relations is None:
            self.relations = []
        if self.ai_state is None:
            self.ai_state = {}
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.modified_at:
            self.modified_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "PackWorkspace":
        return cls(**data)


class PackWorkspaceService:
    """
    Pack 工作区服务 - 操作 Redis 中的工作区

    所有方法都是幂等的，供 Temporal Activity 调用
    """

    def __init__(self):
        self.redis = redis

    def _pack_key(self, session_id: str) -> str:
        return f"pack:session:{session_id}"

    def _pubsub_channel(self, session_id: str) -> str:
        return f"pack:changes:{session_id}"

    # ========== 工作区生命周期 ==========

    async def create_workspace(
        self, session_id: str, initial_cards: Optional[List[Dict]] = None
    ) -> PackWorkspace:
        """创建新工作区"""
        pack = PackWorkspace(
            session_id=session_id, cards=initial_cards or [], version=1
        )

        key = self._pack_key(session_id)
        await self.redis.set(key, json.dumps(pack.to_dict()))

        # 发布创建事件
        await self._publish_change(
            session_id,
            {
                "type": "workspace_created",
                "session_id": session_id,
                "card_count": len(pack.cards),
            },
        )

        logger.info(f"Created pack workspace for session {session_id}")
        return pack

    async def get_workspace(self, session_id: str) -> Optional[PackWorkspace]:
        """获取工作区"""
        key = self._pack_key(session_id)
        data = await self.redis.get(key)

        if not data:
            return None

        return PackWorkspace.from_dict(json.loads(data))

    async def delete_workspace(self, session_id: str) -> bool:
        """删除工作区（会话结束或清理）"""
        key = self._pack_key(session_id)
        deleted = await self.redis.delete(key) > 0

        if deleted:
            logger.info(f"Deleted pack workspace for session {session_id}")

        return bool(deleted)

    # ========== 卡片操作 ==========

    async def add_cards(
        self, session_id: str, cards: List[WorkspaceCard], source: str = "ai"
    ) -> PackWorkspace:
        """批量添加卡片到工作区"""
        pack = await self.get_workspace(session_id)
        if not pack:
            raise ValueError(f"Workspace {session_id} not found")

        # Index existing cards by temp_id to avoid duplicates
        existing_index = {}
        for i, c in enumerate(pack.cards):
            temp_id = c.get("temp_id")
            if temp_id:
                existing_index[temp_id] = i

        # Collapse any existing duplicates (keep last occurrence)
        if existing_index and len(existing_index) != len(pack.cards):
            deduped = {}
            for c in pack.cards:
                tid = c.get("temp_id")
                if not tid:
                    continue
                deduped[tid] = c
            pack.cards = list(deduped.values())
            existing_index = {c.get("temp_id"): i for i, c in enumerate(pack.cards) if c.get("temp_id")}

        # 分配 temp_id 和 order
        start_order = len(pack.cards)
        now = datetime.utcnow().isoformat()
        to_append: List[WorkspaceCard] = []
        seen_in_batch = set()
        for i, card in enumerate(cards):
            if not card.temp_id:
                card.temp_id = f"c-{uuid.uuid4().hex[:8]}"
            card.modified_at = now

            if card.temp_id in seen_in_batch:
                continue
            seen_in_batch.add(card.temp_id)

            existing = existing_index.get(card.temp_id)
            if existing is None:
                card.order = start_order + len(to_append)
                card.version = 1
                to_append.append(card)
            else:
                # Update existing card in place instead of duplicating
                current = pack.cards[existing]
                current["content"] = card.content
                current["media"] = card.media
                current["model"] = card.model
                current["status"] = card.status
                current["version"] = int(current.get("version", 0)) + 1
                current["modified_at"] = now

        # 追加新卡片
        if to_append:
            pack.cards.extend([c.to_dict() for c in to_append])

        # Final safeguard: de-duplicate by temp_id (keep last)
        if pack.cards:
            final_map = {}
            for c in pack.cards:
                tid = c.get("temp_id")
                if not tid:
                    continue
                final_map[tid] = c
            pack.cards = list(final_map.values())
        pack.version += 1
        pack.modified_at = now

        # 原子更新
        await self._save_pack(session_id, pack)

        # 广播
        await self._publish_change(
            session_id,
            {
                "type": "cards_added",
                "count": len(cards),
                "temp_ids": [c.temp_id for c in cards],
                "by": source,
                "version": pack.version,
            },
        )

        return pack

    async def acquire_lock(
        self, session_id: str, temp_id: str, holder: str, ttl_seconds: int = 120
    ) -> bool:
        """
        获取卡片编辑锁

        返回 True 表示成功，False 表示已被锁定
        """
        pack = await self.get_workspace(session_id)
        if not pack:
            return False

        # 找到卡片
        card_idx = None
        for i, c in enumerate(pack.cards):
            if c.get("temp_id") == temp_id:
                card_idx = i
                break

        if card_idx is None:
            return False

        card = pack.cards[card_idx]

        # 检查当前锁
        if card.get("locked_by"):
            expires = card.get("lock_expires")
            if expires and datetime.fromisoformat(expires) > datetime.utcnow():
                # 锁未过期
                return False

        # 获取锁
        now = datetime.utcnow()
        expires = now + timedelta(seconds=ttl_seconds)

        card["locked_by"] = holder
        card["locked_at"] = now.isoformat()
        card["lock_expires"] = expires.isoformat()

        pack.version += 1
        pack.modified_at = now.isoformat()

        await self._save_pack(session_id, pack)

        # 广播锁变更
        await self._publish_change(
            session_id,
            {
                "type": "lock_acquired",
                "temp_id": temp_id,
                "holder": holder,
                "expires_at": expires.isoformat(),
                "version": pack.version,
            },
        )

        return True

    async def release_lock(self, session_id: str, temp_id: str, holder: str) -> bool:
        """释放锁（只能由持有者释放）"""
        pack = await self.get_workspace(session_id)
        if not pack:
            return False

        # 找到卡片
        card_idx = None
        for i, c in enumerate(pack.cards):
            if c.get("temp_id") == temp_id:
                card_idx = i
                break

        if card_idx is None:
            return False

        card = pack.cards[card_idx]

        # 验证持有者
        if card.get("locked_by") != holder:
            return False

        # 释放锁
        card["locked_by"] = None
        card["locked_at"] = None
        card["lock_expires"] = None

        pack.version += 1
        pack.modified_at = datetime.utcnow().isoformat()

        await self._save_pack(session_id, pack)

        # 广播
        await self._publish_change(
            session_id,
            {
                "type": "lock_released",
                "temp_id": temp_id,
                "holder": holder,
                "version": pack.version,
            },
        )

        return True

    async def update_card_content(
        self,
        session_id: str,
        temp_id: str,
        new_content: Dict[str, Any],
        expected_version: int,
        editor: str,
    ) -> Dict[str, Any]:
        """
        更新卡片内容（乐观锁）

        返回: {"success": True/False, "current_version": int, "error": str}
        """
        pack = await self.get_workspace(session_id)
        if not pack:
            return {"success": False, "error": "Workspace not found"}

        # 找到卡片
        card_idx = None
        for i, c in enumerate(pack.cards):
            if c.get("temp_id") == temp_id:
                card_idx = i
                break

        if card_idx is None:
            return {"success": False, "error": "Card not found"}

        card = pack.cards[card_idx]

        # 乐观锁检查
        if card.get("version") != expected_version:
            return {
                "success": False,
                "error": "Version conflict",
                "current_version": card.get("version"),
            }

        # 应用修改
        card["content"] = new_content
        card["version"] = expected_version + 1
        card["modified_at"] = datetime.utcnow().isoformat()

        # 标记修改来源
        if editor.startswith("user:"):
            card["user_modified"] = True
        elif editor.startswith("ai:"):
            card["ai_suggestions"] = card.get("ai_suggestions", 0) + 1

        pack.version += 1
        pack.modified_at = card["modified_at"]

        await self._save_pack(session_id, pack)

        # 广播
        await self._publish_change(
            session_id,
            {
                "type": "card_updated",
                "temp_id": temp_id,
                "version": card["version"],
                "by": editor,
                "pack_version": pack.version,
            },
        )

        return {"success": True, "new_version": card["version"]}

    async def get_card(self, session_id: str, temp_id: str) -> Optional[WorkspaceCard]:
        """获取单张卡片"""
        pack = await self.get_workspace(session_id)
        if not pack:
            return None

        for c in pack.cards:
            if c.get("temp_id") == temp_id:
                return WorkspaceCard.from_dict(c)

        return None

    async def list_cards(
        self, session_id: str, include_content: bool = True
    ) -> List[Dict[str, Any]]:
        """列出工作区所有卡片（瀑布流用）"""
        pack = await self.get_workspace(session_id)
        if not pack:
            return []

        cards = sorted(pack.cards, key=lambda c: c.get("order", 0))

        if not include_content:
            # 只返回摘要（减少传输）
            return [
                {
                    "temp_id": c["temp_id"],
                    "order": c["order"],
                    "version": c["version"],
                    "locked": c.get("locked_by") is not None,
                    "locked_by": c.get("locked_by"),
                    "user_modified": c.get("user_modified", False),
                    "preview": c["content"].get("text", "")[:100]
                    if "text" in c.get("content", {})
                    else "",
                }
                for c in cards
            ]

        return cards

    # ========== 内部方法 ==========

    async def _save_pack(self, session_id: str, pack: PackWorkspace):
        """保存工作区到 Redis"""
        key = self._pack_key(session_id)
        await self.redis.set(key, json.dumps(pack.to_dict()))

    async def _publish_change(self, session_id: str, change: Dict):
        """发布变更事件（供 WebSocket 订阅）"""
        channel = self._pubsub_channel(session_id)
        await self.redis.publish(channel, json.dumps(change))
        logger.debug(f"Published change to {channel}: {change['type']}")


# 全局实例
pack_workspace = PackWorkspaceService()
