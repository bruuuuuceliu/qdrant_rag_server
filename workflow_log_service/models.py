"""Workflow log domain models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.queue import QueueMessage


@dataclass(frozen=True, slots=True)
class WorkflowLogEntry:
    event: str
    job_id: str
    status: str
    project_id: str
    user_id: str
    kb_id: str = ""
    doc_id: str = ""
    data_type: str = ""
    content_hash: str = ""
    raw_storage_key: str = ""
    error: str = ""
    topic: str = ""
    key: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def from_message(cls, message: QueueMessage) -> "WorkflowLogEntry":
        payload = dict(message.payload)
        return cls(
            event=str(payload.get("event", "")),
            job_id=str(payload.get("job_id", message.key)),
            status=str(payload.get("status", "")),
            project_id=str(payload.get("project_id", "")),
            user_id=str(payload.get("user_id", "")),
            kb_id=str(payload.get("kb_id", "")),
            doc_id=str(payload.get("doc_id", "")),
            data_type=str(payload.get("data_type", "")),
            content_hash=str(payload.get("content_hash", "")),
            raw_storage_key=str(payload.get("raw_storage_key", "")),
            error=str(payload.get("error", "")),
            topic=message.topic,
            key=message.key,
            headers=dict(message.headers),
            payload=payload,
        )
