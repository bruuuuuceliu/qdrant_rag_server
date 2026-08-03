"""Memory service domain models.

Frozen dataclasses mirroring the SQLite tables in requirements §6 plus the
transport fields carried over the broker. Each model exposes explicit
``from_mapping``/``to_mapping`` converters (mirror ``WorkflowLogEntry``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MemorySession:
    """A chat-session classifier/identifier (FR-1.1)."""

    session_id: str
    owner_user_id: str
    agent_id: str
    status: str
    started_at: str
    closed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "MemorySession":
        return cls(
            session_id=str(value.get("session_id", "")),
            owner_user_id=str(value.get("owner_user_id", "")),
            agent_id=str(value.get("agent_id", "")),
            status=str(value.get("status", "")),
            started_at=str(value.get("started_at", "")),
            closed_at=_optional_str(value.get("closed_at")),
            metadata=dict(value.get("metadata", {}) or {}),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "session_id": self.session_id,
            "owner_user_id": self.owner_user_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "started_at": self.started_at,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.closed_at is not None:
            mapping["closed_at"] = self.closed_at
        return mapping


@dataclass(frozen=True, slots=True)
class MemoryMessage:
    """A single user or assistant turn within a session (FR-1.2)."""

    message_id: str
    session_id: str
    owner_user_id: str
    agent_id: str
    role: str
    sequence_number: int
    content: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "MemoryMessage":
        return cls(
            message_id=str(value.get("message_id", "")),
            session_id=str(value.get("session_id", "")),
            owner_user_id=str(value.get("owner_user_id", "")),
            agent_id=str(value.get("agent_id", "")),
            role=str(value.get("role", "")),
            sequence_number=int(value.get("sequence_number", 0)),
            content=str(value.get("content", "")),
            created_at=str(value.get("created_at", "")),
            metadata=dict(value.get("metadata", {}) or {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "owner_user_id": self.owner_user_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "sequence_number": self.sequence_number,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A durable memory record: compression summary or mirrored fact.

    ``kind`` is one of ``message``, ``compression_summary``, or ``fact``.
    Compression summaries carry the covered ``[from, to]`` span; other kinds
    leave the span fields unset.
    """

    memory_id: str
    owner_user_id: str
    agent_id: str
    kind: str
    content: str
    session_id: str = ""
    covered_from: int | None = None
    covered_to: int | None = None
    created_at: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "MemoryRecord":
        return cls(
            memory_id=str(value.get("memory_id", "")),
            owner_user_id=str(value.get("owner_user_id", "")),
            agent_id=str(value.get("agent_id", "")),
            kind=str(value.get("kind", "")),
            content=str(value.get("content", "")),
            session_id=str(value.get("session_id", "")),
            covered_from=_optional_int(value.get("covered_from")),
            covered_to=_optional_int(value.get("covered_to")),
            created_at=str(value.get("created_at", "")),
        )

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "memory_id": self.memory_id,
            "owner_user_id": self.owner_user_id,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "content": self.content,
            "session_id": self.session_id,
            "created_at": self.created_at,
        }
        if self.covered_from is not None:
            mapping["covered_from"] = self.covered_from
        if self.covered_to is not None:
            mapping["covered_to"] = self.covered_to
        return mapping


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Per-user profile with basic info and an identity revision (FR-4.1)."""

    user_id: str
    basic_info: dict[str, Any]
    identity_revision: int
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=str(value.get("user_id", "")),
            basic_info=dict(value.get("basic_info", {}) or {}),
            identity_revision=int(value.get("identity_revision", 0)),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "basic_info": dict(self.basic_info),
            "identity_revision": self.identity_revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class UserFact:
    """A versioned, superseding fact about a user (FR-4.5)."""

    fact_id: str
    user_id: str
    fact_type: str
    subject: str
    text: str
    status: str
    version: int
    updated_by: str
    source_message_id: str = ""
    superseded_by: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "UserFact":
        return cls(
            fact_id=str(value.get("fact_id", "")),
            user_id=str(value.get("user_id", "")),
            fact_type=str(value.get("fact_type", "")),
            subject=str(value.get("subject", "")),
            text=str(value.get("text", "")),
            status=str(value.get("status", "")),
            version=int(value.get("version", 1)),
            updated_by=str(value.get("updated_by", "")),
            source_message_id=str(value.get("source_message_id", "")),
            superseded_by=_optional_str(value.get("superseded_by")),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )

    def to_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "fact_id": self.fact_id,
            "user_id": self.user_id,
            "fact_type": self.fact_type,
            "subject": self.subject,
            "text": self.text,
            "status": self.status,
            "version": self.version,
            "updated_by": self.updated_by,
            "source_message_id": self.source_message_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.superseded_by is not None:
            mapping["superseded_by"] = self.superseded_by
        return mapping


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """A mutation replay row scoped to the owner (requirements §9)."""

    idempotency_key: str
    operation: str
    request_hash: str
    result: dict[str, Any]
    owner_user_id: str = ""
    created_at: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "IdempotencyRecord":
        return cls(
            idempotency_key=str(value.get("idempotency_key", "")),
            operation=str(value.get("operation", "")),
            request_hash=str(value.get("request_hash", "")),
            result=dict(value.get("result", {}) or {}),
            owner_user_id=str(value.get("owner_user_id", "")),
            created_at=str(value.get("created_at", "")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "operation": self.operation,
            "request_hash": self.request_hash,
            "result": dict(self.result),
            "owner_user_id": self.owner_user_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class CompressionSpan:
    """Ordered message span to compress (design §3.3)."""

    session_id: str
    messages: tuple[tuple[int, str, str], ...]
    policy: str = "condense-v1"
    keep_recent: int = 0


@dataclass(frozen=True, slots=True)
class CondensedOutput:
    """Compression output: condensed context plus the kept-recent tail."""

    condensed_context: str
    memory_id: str
    covered_from: int
    covered_to: int
    policy: str
    recent_messages: list[MemoryMessage] = field(default_factory=list)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iso_utc_now() -> str:
    """Return a deterministic ISO-8601 UTC timestamp for row writes."""

    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
