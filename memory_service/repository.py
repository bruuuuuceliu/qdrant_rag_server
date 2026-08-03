"""Memory service repositories.

``MemoryRepository`` is the port the domain handler depends on. Two
implementations exist: ``MemoryInMemoryRepository`` for tests/local and
``SQLiteMemoryRepository`` for the durable store. Mutations and idempotency
writes commit in a single ``BEGIN IMMEDIATE`` transaction exposed through the
``transaction()`` context manager (requirements §9).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from memory_service.models import (
    IdempotencyRecord,
    MemoryMessage,
    MemoryRecord,
    MemorySession,
    UserFact,
    UserProfile,
)


class MemoryNotFoundError(KeyError):
    """Raised when a session/message/profile/fact is missing for the scope."""


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different payload."""


class FactSupersessionConflict(ValueError):
    """Raised when a concurrent fact supersession hits the unique partial index."""


class MemoryTransaction(Protocol):
    """Write-scoped operations sharing one repository transaction."""

    def get_idempotent(
        self, idempotency_key: str, *, owner_user_id: str = ""
    ) -> IdempotencyRecord | None:
        ...

    def store_idempotent(self, record: IdempotencyRecord) -> None:
        ...

    def upsert_session(self, session: MemorySession) -> bool:
        ...

    def close_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        closed_at: str,
    ) -> tuple[MemorySession, bool]:
        ...

    def insert_message(self, message: MemoryMessage) -> bool:
        ...

    def insert_memory_record(self, record: MemoryRecord) -> bool:
        ...

    def upsert_profile(self, profile: UserProfile) -> bool:
        ...

    def insert_fact(self, fact: UserFact) -> None:
        ...

    def supersede_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        subject: str,
        new_fact: UserFact,
    ) -> tuple[list[UserFact], UserFact]:
        ...


class MemoryRepository(Protocol):
    """Port used by the domain handler for reads and transactions."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[MemoryTransaction]:
        ...

    async def get_session(self, owner_user_id: str, session_id: str) -> MemorySession | None:
        ...

    async def session_owner(self, session_id: str) -> str | None:
        """Return the owning user of a session regardless of the caller scope.

        Used to reject cross-owner session reuse (m13). Returns ``None`` when
        the session does not exist.
        """

        ...

    async def get_message(self, owner_user_id: str, message_id: str) -> MemoryMessage | None:
        ...

    async def list_session_messages(
        self, owner_user_id: str, session_id: str
    ) -> list[MemoryMessage]:
        ...

    async def list_messages(
        self, owner_user_id: str, agent_id: str
    ) -> list[MemoryMessage]:
        ...

    async def count_messages(self, owner_user_id: str, agent_id: str) -> int:
        ...

    async def get_memory_record(
        self, owner_user_id: str, memory_id: str
    ) -> MemoryRecord | None:
        ...

    async def list_session_summaries(
        self, owner_user_id: str, session_id: str
    ) -> list[MemoryRecord]:
        ...

    async def list_memory_records(
        self, owner_user_id: str, agent_id: str
    ) -> list[MemoryRecord]:
        ...

    async def count_memory_records(
        self, owner_user_id: str, agent_id: str, kind: str
    ) -> int:
        ...

    async def get_profile(self, user_id: str) -> UserProfile | None:
        ...

    async def get_fact(self, user_id: str, fact_id: str) -> UserFact | None:
        ...

    async def list_active_facts(self, user_id: str) -> list[UserFact]:
        ...

    async def list_facts(
        self, user_id: str, *, include_inactive: bool = False
    ) -> list[UserFact]:
        ...

    async def count_active_facts(self, user_id: str) -> int:
        ...


class _InMemoryState:
    """Mutable state backing the in-memory repository."""

    def __init__(self) -> None:
        self.sessions: dict[str, MemorySession] = {}
        self.messages: dict[str, MemoryMessage] = {}
        self.memory_records: dict[str, MemoryRecord] = {}
        self.profiles: dict[str, UserProfile] = {}
        self.facts: dict[str, UserFact] = {}
        self.idempotency: dict[tuple[str, str], IdempotencyRecord] = {}


class InMemoryMemoryTransaction:
    """In-memory write-scoped operations over shared state."""

    def __init__(self, state: _InMemoryState) -> None:
        self._state = state

    def get_idempotent(
        self, idempotency_key: str, *, owner_user_id: str = ""
    ) -> IdempotencyRecord | None:
        return self._state.idempotency.get((owner_user_id, idempotency_key))

    def store_idempotent(self, record: IdempotencyRecord) -> None:
        self._state.idempotency[(record.owner_user_id, record.idempotency_key)] = record

    def upsert_session(self, session: MemorySession) -> bool:
        if session.session_id in self._state.sessions:
            return False
        self._state.sessions[session.session_id] = session
        return True

    def close_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        closed_at: str,
    ) -> tuple[MemorySession, bool]:
        session = self._state.sessions.get(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            raise MemoryNotFoundError(f"session not found: {session_id}")
        if session.status == "closed":
            return session, False
        updated = MemorySession(
            session_id=session.session_id,
            owner_user_id=session.owner_user_id,
            agent_id=session.agent_id,
            status="closed",
            started_at=session.started_at,
            closed_at=closed_at,
            metadata=dict(session.metadata),
            created_at=session.created_at,
            updated_at=closed_at,
        )
        self._state.sessions[session_id] = updated
        return updated, True

    def insert_message(self, message: MemoryMessage) -> bool:
        if message.message_id in self._state.messages:
            return False
        for existing in self._state.messages.values():
            if (
                existing.session_id == message.session_id
                and existing.sequence_number == message.sequence_number
            ):
                return False
        self._state.messages[message.message_id] = message
        return True

    def insert_memory_record(self, record: MemoryRecord) -> bool:
        if record.memory_id in self._state.memory_records:
            return False
        self._state.memory_records[record.memory_id] = record
        return True

    def upsert_profile(self, profile: UserProfile) -> bool:
        created = profile.user_id not in self._state.profiles
        self._state.profiles[profile.user_id] = profile
        return created

    def insert_fact(self, fact: UserFact) -> None:
        self._state.facts[fact.fact_id] = fact

    def supersede_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        subject: str,
        new_fact: UserFact,
    ) -> tuple[list[UserFact], UserFact]:
        active = [
            fact
            for fact in self._state.facts.values()
            if fact.user_id == user_id
            and fact.fact_type == fact_type
            and fact.subject == subject
            and fact.status == "active"
        ]
        for fact in active:
            self._state.facts[fact.fact_id] = UserFact(
                fact_id=fact.fact_id,
                user_id=fact.user_id,
                fact_type=fact.fact_type,
                subject=fact.subject,
                text=fact.text,
                status="inactive",
                version=fact.version,
                superseded_by=new_fact.fact_id,
                updated_by=fact.updated_by,
                source_message_id=fact.source_message_id,
                created_at=fact.created_at,
                updated_at=new_fact.updated_at,
            )
        versions = [
            fact.version
            for fact in self._state.facts.values()
            if fact.user_id == user_id
            and fact.fact_type == fact_type
            and fact.subject == subject
        ]
        new_version = max(versions, default=0) + 1
        inserted = UserFact(
            fact_id=new_fact.fact_id,
            user_id=new_fact.user_id,
            fact_type=new_fact.fact_type,
            subject=new_fact.subject,
            text=new_fact.text,
            status="active",
            version=new_version,
            superseded_by=None,
            updated_by=new_fact.updated_by,
            source_message_id=new_fact.source_message_id,
            created_at=new_fact.created_at,
            updated_at=new_fact.updated_at,
        )
        self._state.facts[inserted.fact_id] = inserted
        return active, inserted


class MemoryInMemoryRepository:
    """Small dict-backed repository for local development and tests."""

    def __init__(self) -> None:
        self._state = _InMemoryState()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[MemoryTransaction]:
        yield InMemoryMemoryTransaction(self._state)

    async def get_session(self, owner_user_id: str, session_id: str) -> MemorySession | None:
        session = self._state.sessions.get(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            return None
        return session

    async def session_owner(self, session_id: str) -> str | None:
        session = self._state.sessions.get(session_id)
        return session.owner_user_id if session is not None else None

    async def get_message(self, owner_user_id: str, message_id: str) -> MemoryMessage | None:
        message = self._state.messages.get(message_id)
        if message is None or message.owner_user_id != owner_user_id:
            return None
        return message

    async def list_session_messages(
        self, owner_user_id: str, session_id: str
    ) -> list[MemoryMessage]:
        messages = [
            message
            for message in self._state.messages.values()
            if message.session_id == session_id and message.owner_user_id == owner_user_id
        ]
        return sorted(messages, key=lambda message: message.sequence_number)

    async def list_messages(
        self, owner_user_id: str, agent_id: str
    ) -> list[MemoryMessage]:
        messages = [
            message
            for message in self._state.messages.values()
            if message.owner_user_id == owner_user_id and message.agent_id == agent_id
        ]
        return sorted(messages, key=lambda message: message.created_at)

    async def count_messages(self, owner_user_id: str, agent_id: str) -> int:
        return sum(
            1
            for message in self._state.messages.values()
            if message.owner_user_id == owner_user_id and message.agent_id == agent_id
        )

    async def get_memory_record(
        self, owner_user_id: str, memory_id: str
    ) -> MemoryRecord | None:
        record = self._state.memory_records.get(memory_id)
        if record is None or record.owner_user_id != owner_user_id:
            return None
        return record

    async def list_session_summaries(
        self, owner_user_id: str, session_id: str
    ) -> list[MemoryRecord]:
        records = [
            record
            for record in self._state.memory_records.values()
            if record.owner_user_id == owner_user_id
            and record.session_id == session_id
            and record.kind == "compression_summary"
        ]
        return sorted(
            records,
            key=lambda record: (record.covered_from or 0, record.memory_id),
        )

    async def list_memory_records(
        self, owner_user_id: str, agent_id: str
    ) -> list[MemoryRecord]:
        return [
            record
            for record in self._state.memory_records.values()
            if record.owner_user_id == owner_user_id and record.agent_id == agent_id
        ]

    async def count_memory_records(
        self, owner_user_id: str, agent_id: str, kind: str
    ) -> int:
        return sum(
            1
            for record in self._state.memory_records.values()
            if record.owner_user_id == owner_user_id
            and record.agent_id == agent_id
            and record.kind == kind
        )

    async def get_profile(self, user_id: str) -> UserProfile | None:
        return self._state.profiles.get(user_id)

    async def get_fact(self, user_id: str, fact_id: str) -> UserFact | None:
        fact = self._state.facts.get(fact_id)
        if fact is None or fact.user_id != user_id:
            return None
        return fact

    async def list_active_facts(self, user_id: str) -> list[UserFact]:
        return [
            fact
            for fact in self._state.facts.values()
            if fact.user_id == user_id and fact.status == "active"
        ]

    async def list_facts(
        self, user_id: str, *, include_inactive: bool = False
    ) -> list[UserFact]:
        facts = [
            fact
            for fact in self._state.facts.values()
            if fact.user_id == user_id
            and (include_inactive or fact.status == "active")
        ]
        return sorted(facts, key=lambda fact: (fact.fact_type, fact.subject, fact.version))

    async def count_active_facts(self, user_id: str) -> int:
        return sum(
            1
            for fact in self._state.facts.values()
            if fact.user_id == user_id and fact.status == "active"
        )


class SQLiteMemoryTransaction:
    """SQLite-backed write-scoped operations over one live connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_idempotent(
        self, idempotency_key: str, *, owner_user_id: str = ""
    ) -> IdempotencyRecord | None:
        row = self._conn.execute(
            "SELECT owner_user_id, idempotency_key, operation, request_hash, result_json, created_at"
            "  FROM idempotency_records WHERE owner_user_id = ? AND idempotency_key = ?",
            (owner_user_id, idempotency_key),
        ).fetchone()
        return _idempotency_from_row(row) if row is not None else None

    def store_idempotent(self, record: IdempotencyRecord) -> None:
        self._conn.execute(
            "INSERT INTO idempotency_records"
            " (owner_user_id, idempotency_key, operation, request_hash, result_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.owner_user_id,
                record.idempotency_key,
                record.operation,
                record.request_hash,
                json.dumps(record.result, sort_keys=True),
                record.created_at,
            ),
        )

    def upsert_session(self, session: MemorySession) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO sessions"
            " (session_id, owner_user_id, agent_id, status, started_at, closed_at,"
            "  metadata_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.session_id,
                session.owner_user_id,
                session.agent_id,
                session.status,
                session.started_at,
                session.closed_at,
                json.dumps(session.metadata, sort_keys=True),
                session.created_at,
                session.updated_at,
            ),
        )
        return cursor.rowcount > 0

    def close_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        closed_at: str,
    ) -> tuple[MemorySession, bool]:
        row = self._conn.execute(
            "SELECT session_id, owner_user_id, agent_id, status, started_at, closed_at,"
            "       metadata_json, created_at, updated_at"
            "  FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None or row["owner_user_id"] != owner_user_id:
            raise MemoryNotFoundError(f"session not found: {session_id}")
        if row["status"] == "closed":
            return _session_from_row(row), False
        self._conn.execute(
            "UPDATE sessions SET status = 'closed', closed_at = ?, updated_at = ?"
            " WHERE session_id = ?",
            (closed_at, closed_at, session_id),
        )
        updated = _session_from_row(row)
        updated = MemorySession(
            session_id=updated.session_id,
            owner_user_id=updated.owner_user_id,
            agent_id=updated.agent_id,
            status="closed",
            started_at=updated.started_at,
            closed_at=closed_at,
            metadata=updated.metadata,
            created_at=updated.created_at,
            updated_at=closed_at,
        )
        return updated, True

    def insert_message(self, message: MemoryMessage) -> bool:
        try:
            cursor = self._conn.execute(
                "INSERT INTO messages"
                " (message_id, session_id, owner_user_id, agent_id, role,"
                "  sequence_number, content, created_at, metadata_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message.message_id,
                    message.session_id,
                    message.owner_user_id,
                    message.agent_id,
                    message.role,
                    message.sequence_number,
                    message.content,
                    message.created_at,
                    json.dumps(message.metadata, sort_keys=True),
                ),
            )
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def insert_memory_record(self, record: MemoryRecord) -> bool:
        try:
            cursor = self._conn.execute(
                "INSERT INTO memory_records"
                " (memory_id, session_id, owner_user_id, agent_id, kind, content,"
                "  covered_from, covered_to, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.memory_id,
                    record.session_id or None,
                    record.owner_user_id,
                    record.agent_id,
                    record.kind,
                    record.content,
                    record.covered_from,
                    record.covered_to,
                    record.created_at,
                ),
            )
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def upsert_profile(self, profile: UserProfile) -> bool:
        cursor = self._conn.execute(
            "INSERT INTO user_profiles"
            " (user_id, basic_info_json, identity_revision, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            " basic_info_json = excluded.basic_info_json,"
            " identity_revision = excluded.identity_revision,"
            " updated_at = excluded.updated_at",
            (
                profile.user_id,
                json.dumps(profile.basic_info, sort_keys=True),
                profile.identity_revision,
                profile.created_at,
                profile.updated_at,
            ),
        )
        return cursor.rowcount > 0

    def insert_fact(self, fact: UserFact) -> None:
        self._conn.execute(
            "INSERT INTO user_facts"
            " (fact_id, user_id, fact_type, subject, text, status, version,"
            "  superseded_by, updated_by, source_message_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fact.fact_id,
                fact.user_id,
                fact.fact_type,
                fact.subject,
                fact.text,
                fact.status,
                fact.version,
                fact.superseded_by,
                fact.updated_by,
                fact.source_message_id or None,
                fact.created_at,
                fact.updated_at,
            ),
        )

    def supersede_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        subject: str,
        new_fact: UserFact,
    ) -> tuple[list[UserFact], UserFact]:
        # SQLite holds a write lock for the whole BEGIN IMMEDIATE transaction,
        # so no row-level FOR UPDATE is needed (or supported) here.
        rows = self._conn.execute(
            "SELECT fact_id, user_id, fact_type, subject, text, status, version,"
            "       superseded_by, updated_by, source_message_id, created_at, updated_at"
            "  FROM user_facts"
            " WHERE user_id = ? AND fact_type = ? AND subject = ? AND status = 'active'",
            (user_id, fact_type, subject),
        ).fetchall()
        superseded: list[UserFact] = []
        for row in rows:
            fact = _fact_from_row(row)
            self._conn.execute(
                "UPDATE user_facts SET status = 'inactive', superseded_by = ?, updated_at = ?"
                " WHERE fact_id = ?",
                (new_fact.fact_id, new_fact.updated_at, fact.fact_id),
            )
            superseded.append(fact)
        max_version = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM user_facts"
            " WHERE user_id = ? AND fact_type = ? AND subject = ?",
            (user_id, fact_type, subject),
        ).fetchone()[0]
        inserted = UserFact(
            fact_id=new_fact.fact_id,
            user_id=new_fact.user_id,
            fact_type=new_fact.fact_type,
            subject=new_fact.subject,
            text=new_fact.text,
            status="active",
            version=int(max_version) + 1,
            superseded_by=None,
            updated_by=new_fact.updated_by,
            source_message_id=new_fact.source_message_id,
            created_at=new_fact.created_at,
            updated_at=new_fact.updated_at,
        )
        try:
            self.insert_fact(inserted)
        except sqlite3.IntegrityError as exc:
            raise FactSupersessionConflict(
                "concurrent fact supersession for "
                f"({user_id}, {fact_type}, {subject})"
            ) from exc
        return superseded, inserted


class SQLiteMemoryRepository:
    """SQLite-backed memory repository owning the requirements §6 schema."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id        TEXT PRIMARY KEY,
                    owner_user_id     TEXT NOT NULL,
                    agent_id          TEXT NOT NULL,
                    status            TEXT NOT NULL CHECK (status IN ('active', 'closed')),
                    started_at        TEXT NOT NULL,
                    closed_at         TEXT,
                    metadata_json     TEXT NOT NULL DEFAULT '{}',
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_owner_agent
                    ON sessions(owner_user_id, agent_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sessions_owner_status
                    ON sessions(owner_user_id, status);

                CREATE TABLE IF NOT EXISTS messages (
                    message_id        TEXT PRIMARY KEY,
                    session_id        TEXT NOT NULL REFERENCES sessions(session_id),
                    owner_user_id     TEXT NOT NULL,
                    agent_id          TEXT NOT NULL,
                    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    sequence_number   INTEGER NOT NULL CHECK (sequence_number >= 1),
                    content           TEXT NOT NULL,
                    created_at        TEXT NOT NULL,
                    metadata_json     TEXT NOT NULL DEFAULT '{}',
                    UNIQUE (session_id, sequence_number)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_owner_agent
                    ON messages(owner_user_id, agent_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session_order
                    ON messages(session_id, sequence_number);

                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id         TEXT PRIMARY KEY,
                    session_id        TEXT,
                    owner_user_id     TEXT NOT NULL,
                    agent_id          TEXT NOT NULL,
                    kind              TEXT NOT NULL CHECK (kind IN ('message', 'compression_summary', 'fact')),
                    content           TEXT NOT NULL,
                    covered_from      INTEGER,
                    covered_to        INTEGER,
                    created_at        TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_owner_agent
                    ON memory_records(owner_user_id, agent_id);
                CREATE INDEX IF NOT EXISTS idx_memory_session_span
                    ON memory_records(session_id, covered_from, covered_to);

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id           TEXT PRIMARY KEY,
                    basic_info_json   TEXT NOT NULL DEFAULT '{}',
                    identity_revision INTEGER NOT NULL DEFAULT 0,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_facts (
                    fact_id           TEXT PRIMARY KEY,
                    user_id           TEXT NOT NULL REFERENCES user_profiles(user_id),
                    fact_type         TEXT NOT NULL,
                    subject           TEXT NOT NULL DEFAULT '',
                    text              TEXT NOT NULL,
                    status            TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
                    version           INTEGER NOT NULL CHECK (version >= 1),
                    superseded_by     TEXT,
                    updated_by        TEXT NOT NULL,
                    source_message_id TEXT,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_user_facts_one_active
                    ON user_facts(user_id, fact_type, subject)
                    WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_user_facts_user_type_version
                    ON user_facts(user_id, fact_type, version);

                CREATE TABLE IF NOT EXISTS idempotency_records (
                    owner_user_id     TEXT NOT NULL,
                    idempotency_key   TEXT NOT NULL,
                    operation         TEXT NOT NULL,
                    request_hash      TEXT NOT NULL,
                    result_json       TEXT NOT NULL,
                    created_at        TEXT NOT NULL,
                    PRIMARY KEY (owner_user_id, idempotency_key)
                );
                """
            )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[MemoryTransaction]:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield SQLiteMemoryTransaction(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_session(self, owner_user_id: str, session_id: str) -> MemorySession | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT session_id, owner_user_id, agent_id, status, started_at, closed_at,"
                "       metadata_json, created_at, updated_at"
                "  FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None or row["owner_user_id"] != owner_user_id:
            return None
        return _session_from_row(row)

    async def session_owner(self, session_id: str) -> str | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT owner_user_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return str(row["owner_user_id"]) if row is not None else None

    async def get_message(self, owner_user_id: str, message_id: str) -> MemoryMessage | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT message_id, session_id, owner_user_id, agent_id, role,"
                "       sequence_number, content, created_at, metadata_json"
                "  FROM messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None or row["owner_user_id"] != owner_user_id:
            return None
        return _message_from_row(row)

    async def list_session_messages(
        self, owner_user_id: str, session_id: str
    ) -> list[MemoryMessage]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT message_id, session_id, owner_user_id, agent_id, role,"
                "       sequence_number, content, created_at, metadata_json"
                "  FROM messages WHERE session_id = ? AND owner_user_id = ?"
                " ORDER BY sequence_number ASC",
                (session_id, owner_user_id),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    async def list_messages(
        self, owner_user_id: str, agent_id: str
    ) -> list[MemoryMessage]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT message_id, session_id, owner_user_id, agent_id, role,"
                "       sequence_number, content, created_at, metadata_json"
                "  FROM messages WHERE owner_user_id = ? AND agent_id = ?"
                " ORDER BY created_at ASC, sequence_number ASC",
                (owner_user_id, agent_id),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    async def count_messages(self, owner_user_id: str, agent_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE owner_user_id = ? AND agent_id = ?",
                (owner_user_id, agent_id),
            ).fetchone()
        return int(row[0])

    async def get_memory_record(
        self, owner_user_id: str, memory_id: str
    ) -> MemoryRecord | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT memory_id, session_id, owner_user_id, agent_id, kind, content,"
                "       covered_from, covered_to, created_at"
                "  FROM memory_records WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None or row["owner_user_id"] != owner_user_id:
            return None
        return _memory_record_from_row(row)

    async def list_session_summaries(
        self, owner_user_id: str, session_id: str
    ) -> list[MemoryRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT memory_id, session_id, owner_user_id, agent_id, kind, content,"
                "       covered_from, covered_to, created_at"
                "  FROM memory_records"
                " WHERE owner_user_id = ? AND session_id = ? AND kind = 'compression_summary'"
                " ORDER BY covered_from ASC, memory_id ASC",
                (owner_user_id, session_id),
            ).fetchall()
        return [_memory_record_from_row(row) for row in rows]

    async def list_memory_records(
        self, owner_user_id: str, agent_id: str
    ) -> list[MemoryRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT memory_id, session_id, owner_user_id, agent_id, kind, content,"
                "       covered_from, covered_to, created_at"
                "  FROM memory_records WHERE owner_user_id = ? AND agent_id = ?"
                " ORDER BY created_at ASC, memory_id ASC",
                (owner_user_id, agent_id),
            ).fetchall()
        return [_memory_record_from_row(row) for row in rows]

    async def count_memory_records(
        self, owner_user_id: str, agent_id: str, kind: str
    ) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_records"
                " WHERE owner_user_id = ? AND agent_id = ? AND kind = ?",
                (owner_user_id, agent_id, kind),
            ).fetchone()
        return int(row[0])

    async def get_profile(self, user_id: str) -> UserProfile | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, basic_info_json, identity_revision, created_at, updated_at"
                "  FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return _profile_from_row(row) if row is not None else None

    async def get_fact(self, user_id: str, fact_id: str) -> UserFact | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT fact_id, user_id, fact_type, subject, text, status, version,"
                "       superseded_by, updated_by, source_message_id, created_at, updated_at"
                "  FROM user_facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
        if row is None or row["user_id"] != user_id:
            return None
        return _fact_from_row(row)

    async def list_active_facts(self, user_id: str) -> list[UserFact]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT fact_id, user_id, fact_type, subject, text, status, version,"
                "       superseded_by, updated_by, source_message_id, created_at, updated_at"
                "  FROM user_facts WHERE user_id = ? AND status = 'active'"
                " ORDER BY fact_type ASC, subject ASC, version ASC",
                (user_id,),
            ).fetchall()
        return [_fact_from_row(row) for row in rows]

    async def list_facts(
        self, user_id: str, *, include_inactive: bool = False
    ) -> list[UserFact]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if include_inactive:
                rows = conn.execute(
                    "SELECT fact_id, user_id, fact_type, subject, text, status, version,"
                    "       superseded_by, updated_by, source_message_id, created_at, updated_at"
                    "  FROM user_facts WHERE user_id = ?"
                    " ORDER BY fact_type ASC, subject ASC, version ASC",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fact_id, user_id, fact_type, subject, text, status, version,"
                    "       superseded_by, updated_by, source_message_id, created_at, updated_at"
                    "  FROM user_facts WHERE user_id = ? AND status = 'active'"
                    " ORDER BY fact_type ASC, subject ASC, version ASC",
                    (user_id,),
                ).fetchall()
        return [_fact_from_row(row) for row in rows]

    async def count_active_facts(self, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM user_facts WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()
        return int(row[0])

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn


def _session_from_row(row: sqlite3.Row) -> MemorySession:
    return MemorySession(
        session_id=row["session_id"],
        owner_user_id=row["owner_user_id"],
        agent_id=row["agent_id"],
        status=row["status"],
        started_at=row["started_at"],
        closed_at=row["closed_at"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: sqlite3.Row) -> MemoryMessage:
    return MemoryMessage(
        message_id=row["message_id"],
        session_id=row["session_id"],
        owner_user_id=row["owner_user_id"],
        agent_id=row["agent_id"],
        role=row["role"],
        sequence_number=int(row["sequence_number"]),
        content=row["content"],
        created_at=row["created_at"],
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def _memory_record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=row["memory_id"],
        session_id=row["session_id"] or "",
        owner_user_id=row["owner_user_id"],
        agent_id=row["agent_id"],
        kind=row["kind"],
        content=row["content"],
        covered_from=row["covered_from"],
        covered_to=row["covered_to"],
        created_at=row["created_at"],
    )


def _profile_from_row(row: sqlite3.Row) -> UserProfile:
    return UserProfile(
        user_id=row["user_id"],
        basic_info=json.loads(row["basic_info_json"] or "{}"),
        identity_revision=int(row["identity_revision"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _fact_from_row(row: sqlite3.Row) -> UserFact:
    return UserFact(
        fact_id=row["fact_id"],
        user_id=row["user_id"],
        fact_type=row["fact_type"],
        subject=row["subject"] or "",
        text=row["text"],
        status=row["status"],
        version=int(row["version"]),
        superseded_by=row["superseded_by"],
        updated_by=row["updated_by"],
        source_message_id=row["source_message_id"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _idempotency_from_row(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        idempotency_key=row["idempotency_key"],
        operation=row["operation"],
        request_hash=row["request_hash"],
        result=json.loads(row["result_json"] or "{}"),
        owner_user_id=row["owner_user_id"],
        created_at=row["created_at"],
    )
