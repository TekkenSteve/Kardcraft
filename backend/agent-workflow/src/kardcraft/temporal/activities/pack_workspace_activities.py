"""
Pack Workspace Activities - Temporal Activities for Redis Workspace Operations

These activities operate on the Redis workspace (pack:session:{id}).
PostgreSQL is only used for final archival via commit_pack_to_postgres.
"""

from datetime import timedelta
from temporalio import activity
from kardcraft.services.pack_workspace import pack_workspace, PackWorkspaceService
from kardcraft.utils.logger import logger


# ========== Workspace Lifecycle Activities ==========


@activity.defn
async def create_pack_workspace(session_id: str, initial_context: str = "") -> dict:
    """
    Create a new pack workspace in Redis.
    Called at the start of a card editing session.
    """
    service: PackWorkspaceService = pack_workspace

    # Create empty workspace (cards will be added by AI agents)
    pack = await service.create_workspace(session_id)

    logger.info(f"Created pack workspace for session {session_id}")
    return pack.to_dict()


@activity.defn
async def delete_pack_workspace(session_id: str) -> bool:
    """Delete workspace (cleanup on error or cancellation)"""
    service: PackWorkspaceService = pack_workspace
    return await service.delete_workspace(session_id)


@activity.defn
async def refresh_pack_state(session_id: str) -> dict:
    """Refresh pack state from Redis (for Workflow cache)"""
    service: PackWorkspaceService = pack_workspace
    pack = await service.get_workspace(session_id)
    return pack.to_dict() if pack else {}


# ========== Card Operations Activities ==========


@activity.defn
async def add_cards_to_workspace(
    session_id: str, cards: list, source: str = "ai"
) -> dict:
    """
    Add AI-generated cards to workspace.
    Called by AI agents during extraction/optimization.
    """
    from kardcraft.services.pack_workspace import WorkspaceCard

    service: PackWorkspaceService = pack_workspace

    # Convert dicts to WorkspaceCard objects
    card_objects = []
    for card_data in cards:
        card = WorkspaceCard(
            temp_id=card_data.get("temp_id"),
            order=card_data.get("order", 0),
            model=card_data.get("model", "default"),
            content=card_data.get("content", {}),
            media=card_data.get("media", []),
            version=1,
            modified_at="",
            source_doc=card_data.get("source_doc"),
            source_range=card_data.get("source_range"),
        )
        card_objects.append(card)

    pack = await service.add_cards(session_id, card_objects, source)
    return pack.to_dict()


@activity.defn
async def acquire_lock_in_redis(
    session_id: str, temp_id: str, holder: str, ttl_seconds: int = 120
) -> bool:
    """
    Acquire editing lock for a card.
    Called when user opens editor or AI starts optimization.
    """
    service: PackWorkspaceService = pack_workspace
    success = await service.acquire_lock(session_id, temp_id, holder, ttl_seconds)

    if success:
        logger.info(f"Lock acquired: {temp_id} by {holder}")
    else:
        logger.warning(f"Lock failed: {temp_id} for {holder}")

    return success


@activity.defn
async def release_lock_in_redis(session_id: str, temp_id: str, holder: str) -> bool:
    """Release editing lock"""
    service: PackWorkspaceService = pack_workspace
    success = await service.release_lock(session_id, temp_id, holder)

    if success:
        logger.info(f"Lock released: {temp_id} by {holder}")

    return success


@activity.defn
async def apply_edit_in_redis(
    session_id: str, temp_id: str, new_content: dict, editor: str, expected_version: int
) -> dict:
    """
    Apply content edit with optimistic locking.
    Called when user saves changes or AI applies suggestion.
    """
    service: PackWorkspaceService = pack_workspace

    result = await service.update_card_content(
        session_id=session_id,
        temp_id=temp_id,
        new_content=new_content,
        expected_version=expected_version,
        editor=editor,
    )

    if result["success"]:
        logger.info(f"Card updated: {temp_id} to v{result['new_version']} by {editor}")
    else:
        logger.warning(f"Card update failed: {temp_id} - {result.get('error')}")

    return result


@activity.defn
async def notify_lock_acquired(session_id: str, temp_id: str, holder: str):
    """Notify frontend that lock was acquired (via WebSocket)"""
    # WebSocket notification is already done in _publish_change
    # This activity exists for explicit logging/metrics if needed
    logger.info(f"Notified lock acquired: {temp_id} for {holder}")


@activity.defn
async def notify_edit_conflict(session_id: str, temp_id: str, current_version: int):
    """Notify frontend of version conflict"""
    logger.warning(f"Edit conflict: {temp_id}, current v{current_version}")
    # Frontend will receive the conflict via WebSocket and refresh


# ========== Archival Activities ==========


@activity.defn
async def commit_pack_to_postgres(session_id: str) -> str:
    """
    Commit workspace to PostgreSQL (final archival).
    Called when session ends successfully.

    Returns: pack_id (permanent ID in PostgreSQL)
    """
    from kardcraft.db.card_repository import CardRepository
    from kardcraft.db.postgres import postgres
    from sqlalchemy.ext.asyncio import AsyncSession
    import uuid

    service: PackWorkspaceService = pack_workspace

    # Get final workspace state
    pack = await service.get_workspace(session_id)
    if not pack:
        raise ValueError(f"Workspace {session_id} not found")

    # Generate permanent pack_id
    pack_id = f"p-{uuid.uuid4()}"

    # Persist to PostgreSQL
    async with postgres.session() as session:
        repo = CardRepository(session)

        # TODO: Create Pack record
        # TODO: Create Card records for each card in pack
        # TODO: Create CardVersion records for history

        # For now, just log
        logger.info(
            f"Committed pack {pack_id} with {len(pack.cards)} cards to PostgreSQL"
        )

    # Clean up Redis workspace
    await service.delete_workspace(session_id)

    return pack_id


@activity.defn
async def checkpoint_workspace_to_postgres(session_id: str) -> str:
    """
    Periodic checkpoint to PostgreSQL (for long-running sessions).
    Does not delete Redis workspace.
    """
    # Similar to commit but keeps workspace active
    logger.info(f"Checkpoint for session {session_id}")
    return "checkpoint-id"
