"""Startup re-drive seam for failed memory index hand-offs.

Best-effort, log-only reconciliation (design doc §9 "Index durability"): on
``memory_service`` startup, re-index ``memory_records`` where ``indexed=0``
through the existing ``MemoryIndexer``, then persist the queued status. Failures
are logged and never raised — SQLite stays the source of truth and the next
startup re-attempts. This is deliberately NOT a scheduler; the "periodic timer"
variant is a documented follow-up.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from memory_service.models import MemoryRecord

logger = logging.getLogger(__name__)


async def reconcile_pending_index(
    *,
    repository: Any,
    indexer: Any,
) -> int:
    """Re-index pending (``indexed=0``) memory records and mark them queued.

    Records are grouped by their target collection so documents keep their
    ingest-time ``collection_name`` (e.g. ``agent_documents``) while message /
    compression-summary / fact records fall back to the indexer's default
    memory collection. Returns the number of records successfully re-queued.
    """
    pending: list[MemoryRecord] = await repository.list_memory_records_pending_index()
    if not pending:
        return 0

    groups: dict[str, list[MemoryRecord]] = defaultdict(list)
    for record in pending:
        groups[record.collection_name].append(record)

    reindexed = 0
    for collection_name, records in groups.items():
        try:
            await indexer.index(records, collection_name=collection_name)
        except Exception as exc:  # noqa: BLE001 - best-effort projection
            logger.warning(
                "memory re-drive: re-index of %d pending record(s) into "
                "collection %r failed: %s",
                len(records),
                collection_name,
                exc,
            )
            continue
        reindexed += len(records)

    if reindexed:
        try:
            await repository.mark_memory_records_indexed(
                [record.memory_id for record in pending]
            )
        except Exception as exc:  # noqa: BLE001 - next startup re-attempts
            logger.warning(
                "memory re-drive: failed to mark %d record(s) indexed: %s",
                len(pending),
                exc,
            )
            return 0
        logger.info(
            "memory re-drive: re-queued %d pending memory record(s) for indexing",
            reindexed,
        )
    return reindexed
