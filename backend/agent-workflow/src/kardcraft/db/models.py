"""
PostgreSQL database models for Kardcraft.
Cards are the core entity - versioned, locked, and synced with Neo4j.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    String,
    Text,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    CheckConstraint,
    UniqueConstraint,
    Column,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from enum import Enum

Base = declarative_base()


class CardModel(str, Enum):
    """Card types supported by the system."""

    BASIC = "Basic"
    CLOZE = "Cloze"
    IR = "IR"
    REVERSE = "Reverse"


class EditStatus(str, Enum):
    """Card editing state machine."""

    DRAFT = "draft"
    AI_EDITING = "ai_editing"
    USER_EDITING = "user_editing"
    CONFIRMED = "confirmed"


class Card(Base):
    """
    Current state of a card.
    Content stored as JSONB for flexibility while maintaining schema constraints.
    """

    __tablename__ = "cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(64), nullable=False, index=True)
    card_id = Column(String(64), nullable=False, unique=True, index=True)

    # Content (versioned)
    version = Column(Integer, nullable=False, default=1)
    model = Column(
        SQLEnum(
            CardModel,
            name="cardmodel",
            native_enum=True,
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=CardModel.BASIC,
    )
    data = Column(
        JSONB, nullable=False, default=dict
    )  # Flexible content based on model
    media = Column(JSONB, nullable=False, default=list)  # Media references

    # Edit state
    edit_status = Column(
        SQLEnum(
            EditStatus,
            name="editstatus",
            native_enum=True,
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=EditStatus.DRAFT,
    )
    locked_by = Column(String(128), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # Metadata
    concepts = Column(JSONB, nullable=False, default=list)  # Neo4j concept IDs
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    modified_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at = Column(DateTime, nullable=True)

    # Statistics
    manual_edits = Column(Integer, nullable=False, default=0)

    # Relationships
    versions = relationship(
        "CardVersion", back_populates="card", order_by="desc(CardVersion.version)"
    )

    __table_args__ = (
        Index("idx_cards_user_modified", "user_id", "modified_at"),
        Index("idx_cards_edit_status", "edit_status", "locked_at"),
        Index("idx_cards_concepts", "concepts", postgresql_using="gin"),
        CheckConstraint("version >= 1", name="ck_card_version_positive"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "card_id": self.card_id,
            "content": {
                "version": self.version,
                "model": self.model.value,
                "data": self.data,
                "media": self.media,
            },
            "edit_state": {
                "status": self.edit_status.value,
                "locked_by": self.locked_by,
                "locked_at": self.locked_at.isoformat() if self.locked_at else None,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            },
            "concepts": self.concepts,
            "meta": {
                "created_at": self.created_at.isoformat(),
                "modified_at": self.modified_at.isoformat(),
                "manual_edits": self.manual_edits,
            },
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class CardVersion(Base):
    """
    Version history for cards.
    Stores diffs to save space - full content stored on initial version.
    """

    __tablename__ = "card_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    card_id = Column(
        UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False, index=True
    )

    version = Column(Integer, nullable=False)
    diff = Column(JSONB, nullable=False, default=dict)  # JSON Patch format
    data_snapshot = Column(JSONB, nullable=True)  # Full snapshot for major versions

    # Who/why
    changed_by = Column(String(128), nullable=False)
    change_comment = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    card = relationship("Card", back_populates="versions")

    __table_args__ = (
        UniqueConstraint("card_id", "version", name="uq_card_version"),
        Index("idx_card_versions_card_version", "card_id", "version"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "diff": self.diff,
            "data_snapshot": self.data_snapshot,
            "by": self.changed_by,
            "at": self.created_at.isoformat(),
            "comment": self.change_comment,
        }


class Pack(Base):
    """
    Card pack - group of cards for organization.
    """

    __tablename__ = "packs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(64), nullable=False, index=True)
    pack_id = Column(String(64), nullable=False, unique=True, index=True)

    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    modified_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    cards = relationship("PackCard", back_populates="pack")


class PackCard(Base):
    """
    Many-to-many relationship between packs and cards.
    """

    __tablename__ = "pack_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_id = Column(
        UUID(as_uuid=True), ForeignKey("packs.id"), nullable=False, index=True
    )
    card_id = Column(
        UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False, index=True
    )

    position = Column(Integer, nullable=False, default=0)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    pack = relationship("Pack", back_populates="cards")
    card = relationship("Card")

    __table_args__ = (UniqueConstraint("pack_id", "card_id", name="uq_pack_card"),)


class Media(Base):
    """
    Media file references (images, audio, etc).
    """

    __tablename__ = "media"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(64), nullable=False, index=True)
    media_id = Column(String(64), nullable=False, unique=True, index=True)

    file_name = Column(String(512), nullable=False)
    file_type = Column(String(64), nullable=False)  # image, audio, video
    file_path = Column(String(1024), nullable=False)  # MinIO path
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(128), nullable=True)

    file_metadata = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)


class WorkflowEventOutbox(Base):
    """
    Durable outbox for workflow realtime events.
    Events are persisted here first, then projected to Redis by a dedicated projector.
    """

    __tablename__ = "workflow_event_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String(128), nullable=False)
    session_id = Column(String(128), nullable=True)
    user_id = Column(String(128), nullable=True)
    workflow_id = Column(String(256), nullable=False)
    run_id = Column(String(128), nullable=False)
    event_seq = Column(BigInteger, nullable=False)
    event_type = Column(String(64), nullable=False)
    channel = Column(String(32), nullable=False, default="timeline")
    payload = Column(JSONB, nullable=False, default=dict)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(32), nullable=False, default="pending")
    projector_id = Column(String(128), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    projected_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("task_id", "event_seq", name="uq_outbox_task_seq"),
        Index("idx_outbox_pending", "status", "id"),
        Index("idx_outbox_task_seq", "task_id", "event_seq"),
        CheckConstraint(
            "status in ('pending', 'projecting', 'projected')",
            name="ck_outbox_status",
        ),
    )


class TaskLifecycleState(Base):
    """
    Task-level lifecycle and gating controls.
    Used by event bus to enforce pause/cancel/shutdown publish semantics.
    """

    __tablename__ = "task_lifecycle_state"

    task_id = Column(String(128), primary_key=True)
    phase = Column(String(32), nullable=False, default="running")
    accepting_progress = Column(Boolean, nullable=False, default=True)
    accepting_usage = Column(Boolean, nullable=False, default=True)
    terminal_event_emitted = Column(Boolean, nullable=False, default=False)
    done_event_emitted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "phase in ('running', 'paused', 'cancelling', 'terminal')",
            name="ck_task_lifecycle_phase",
        ),
    )


class TaskEventSeq(Base):
    """
    Monotonic event sequence per task.
    """

    __tablename__ = "task_event_seq"

    task_id = Column(String(128), primary_key=True)
    next_seq = Column(BigInteger, nullable=False, default=0)
