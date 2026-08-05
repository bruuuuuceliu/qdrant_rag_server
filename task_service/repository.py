"""Task service-owned execution state repository."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from psycopg import AsyncConnection

from shared.postgres import async_pool


@dataclass(slots=True)
class TaskState:
    task_id: str
    data_type: str = ""
    correlation_id: str = ""
    operation: str = ""
    expected_helpers: set[str] = field(default_factory=set)
    completed_helpers: set[str] = field(default_factory=set)
    failed_helpers: set[str] = field(default_factory=set)
    helper_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    helper_plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    helper_attempts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    final_status: str = ""
    final_result: dict[str, Any] = field(default_factory=dict)
    final_published: bool = False

    @property
    def complete(self) -> bool:
        return bool(self.expected_helpers) and self.expected_helpers <= (
            self.completed_helpers | self.failed_helpers
        )

    @property
    def failed(self) -> bool:
        return bool(self.failed_helpers)


@dataclass(frozen=True, slots=True)
class PendingHelperDispatch:
    task_id: str
    data_type: str
    correlation_id: str
    operation: str
    helper: str
    plan: dict[str, Any]
    attempt: int
    reason: str
    last_source_message_id: str = ""
    next_attempt_at: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""


class TaskStateRepository(Protocol):
    async def record_execution(
        self,
        task_id: str,
        *,
        data_type: str = "",
        correlation_id: str = "",
        operation: str = "",
    ) -> TaskState:
        ...

    async def set_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        ...

    async def add_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        ...

    async def mark_helper_result(
        self,
        task_id: str,
        helper: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        attempt: int = 1,
        retryable: bool = False,
        error: str = "",
        source_message_id: str = "",
        failed_message_id: str = "",
    ) -> TaskState:
        ...

    async def get(self, task_id: str) -> TaskState | None:
        ...

    async def record_helper_plan(
        self,
        task_id: str,
        helper: str,
        *,
        operation: str,
        plan: dict[str, Any],
    ) -> TaskState:
        ...

    async def record_helper_dispatch(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int = 1,
        source_message_id: str = "",
        lease_owner: str = "",
        lease_expires_at: str = "",
        next_attempt_at: str = "",
    ) -> TaskState:
        ...

    async def record_helper_attempt(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int,
        status: str,
        result: dict[str, Any] | None = None,
        retryable: bool = False,
        error: str = "",
        source_message_id: str = "",
        failed_message_id: str = "",
        next_attempt_at: str = "",
    ) -> TaskState:
        ...

    async def mark_final_published(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> TaskState:
        ...

    async def claim_due_helper_dispatches(
        self,
        *,
        now: str,
        lease_owner: str,
        lease_expires_at: str,
        max_attempts: int,
        limit: int = 25,
    ) -> tuple[PendingHelperDispatch, ...]:
        ...


class InMemoryTaskStateRepository:
    def __init__(self) -> None:
        self._states: dict[str, TaskState] = {}

    async def record_execution(
        self,
        task_id: str,
        *,
        data_type: str = "",
        correlation_id: str = "",
        operation: str = "",
    ) -> TaskState:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        if data_type:
            state.data_type = data_type
        if correlation_id:
            state.correlation_id = correlation_id
        if operation:
            state.operation = operation
        return state

    async def set_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.expected_helpers = set(helpers)

    async def add_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.expected_helpers.update(helpers)

    async def mark_helper_result(
        self,
        task_id: str,
        helper: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        attempt: int = 1,
        retryable: bool = False,
        error: str = "",
        source_message_id: str = "",
        failed_message_id: str = "",
    ) -> TaskState:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.expected_helpers.add(helper)
        if ok:
            state.completed_helpers.add(helper)
            state.failed_helpers.discard(helper)
        else:
            state.failed_helpers.add(helper)
            state.completed_helpers.discard(helper)
        state.helper_results[helper] = dict(result or {})
        state.helper_attempts.setdefault(helper, []).append(
            _attempt_payload(
                attempt=attempt,
                event="result",
                status="completed" if ok else "failed",
                retryable=retryable,
                result=dict(result or {}),
                error=error,
                source_message_id=source_message_id,
                failed_message_id=failed_message_id,
            )
        )
        return state

    async def get(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    async def record_helper_plan(
        self,
        task_id: str,
        helper: str,
        *,
        operation: str,
        plan: dict[str, Any],
    ) -> TaskState:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.expected_helpers.add(helper)
        state.helper_plans[helper] = {
            "operation": operation,
            "plan": dict(plan),
        }
        return state

    async def record_helper_dispatch(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int = 1,
        source_message_id: str = "",
        lease_owner: str = "",
        lease_expires_at: str = "",
        next_attempt_at: str = "",
    ) -> TaskState:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.expected_helpers.add(helper)
        state.helper_attempts.setdefault(helper, []).append(
            _attempt_payload(
                attempt=attempt,
                event="dispatch",
                status="dispatched",
                retryable=False,
                source_message_id=source_message_id,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                next_attempt_at=next_attempt_at,
            )
        )
        return state

    async def record_helper_attempt(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int,
        status: str,
        result: dict[str, Any] | None = None,
        retryable: bool = False,
        error: str = "",
        source_message_id: str = "",
        failed_message_id: str = "",
        next_attempt_at: str = "",
    ) -> TaskState:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.expected_helpers.add(helper)
        state.helper_attempts.setdefault(helper, []).append(
            _attempt_payload(
                attempt=attempt,
                event="result",
                status=status,
                retryable=retryable,
                result=dict(result or {}),
                error=error,
                source_message_id=source_message_id,
                failed_message_id=failed_message_id,
                next_attempt_at=next_attempt_at,
            )
        )
        return state

    async def mark_final_published(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> TaskState:
        state = self._states.setdefault(task_id, TaskState(task_id=task_id))
        state.final_status = status
        state.final_result = dict(result)
        state.final_published = True
        return state

    async def claim_due_helper_dispatches(
        self,
        *,
        now: str,
        lease_owner: str,
        lease_expires_at: str,
        max_attempts: int,
        limit: int = 25,
    ) -> tuple[PendingHelperDispatch, ...]:
        return ()



_TASK_POSTGRES_DDL = (
    """
    CREATE TABLE IF NOT EXISTS task_executions (
        task_id TEXT PRIMARY KEY,
        data_type TEXT NOT NULL DEFAULT '',
        correlation_id TEXT NOT NULL DEFAULT '',
        operation TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS task_steps (
        task_id TEXT NOT NULL,
        helper TEXT NOT NULL,
        expected INTEGER NOT NULL DEFAULT 1,
        completed INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        operation TEXT NOT NULL DEFAULT '',
        plan_json TEXT NOT NULL DEFAULT '{}',
        result_json TEXT NOT NULL DEFAULT '{}',
        attempt INTEGER NOT NULL DEFAULT 0,
        last_status TEXT NOT NULL DEFAULT '',
        retryable INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        lease_owner TEXT NOT NULL DEFAULT '',
        lease_expires_at TEXT,
        last_dispatched_at TEXT,
        last_result_at TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        last_source_message_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        PRIMARY KEY (task_id, helper),
        FOREIGN KEY (task_id) REFERENCES task_executions(task_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_steps_task_complete
        ON task_steps(task_id, completed, failed);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_steps_helper
        ON task_steps(helper);
    """,
    """
    CREATE TABLE IF NOT EXISTS task_step_attempts (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        task_id TEXT NOT NULL,
        helper TEXT NOT NULL,
        attempt INTEGER NOT NULL,
        event TEXT NOT NULL,
        status TEXT NOT NULL,
        retryable INTEGER NOT NULL DEFAULT 0,
        source_message_id TEXT NOT NULL DEFAULT '',
        failed_message_id TEXT NOT NULL DEFAULT '',
        result_json TEXT NOT NULL DEFAULT '{}',
        error TEXT NOT NULL DEFAULT '',
        next_attempt_at TEXT,
        lease_owner TEXT NOT NULL DEFAULT '',
        lease_expires_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        FOREIGN KEY (task_id, helper) REFERENCES task_steps(task_id, helper)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_step_attempts_task_helper
        ON task_step_attempts(task_id, helper, attempt);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_step_attempts_status
        ON task_step_attempts(status, retryable);
    """,
    """
    CREATE TABLE IF NOT EXISTS task_results (
        task_id TEXT PRIMARY KEY,
        final_status TEXT NOT NULL DEFAULT '',
        result_json TEXT NOT NULL DEFAULT '{}',
        published INTEGER NOT NULL DEFAULT 0,
        published_at TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
        FOREIGN KEY (task_id) REFERENCES task_executions(task_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_results_published
        ON task_results(published, final_status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_steps_next_attempt
        ON task_steps(next_attempt_at, completed, failed);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_steps_lease
        ON task_steps(lease_owner, lease_expires_at);
    """,
)


class PostgresTaskStateRepository:
    """Postgres-backed task state repository selected via ``TASK_SERVICE_STATE_DB_URL``.

    The composition root is synchronous, so the async pool and schema are
    initialized lazily on the first method call.
    """

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self._pool = async_pool(db_url)
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        await self._pool.open()
        await self._pool.wait()
        async with self._pool.connection() as conn:
            for statement in _TASK_POSTGRES_DDL:
                await conn.execute(statement)
        self._initialized = True

    async def close(self) -> None:
        await self._pool.close()

    async def record_execution(
        self,
        task_id: str,
        *,
        data_type: str = "",
        correlation_id: str = "",
        operation: str = "",
    ) -> TaskState:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(
                conn,
                task_id,
                data_type=data_type,
                correlation_id=correlation_id,
                operation=operation,
            )
        state = await self.get(task_id)
        if state is None:
            raise RuntimeError(f"task state was not persisted for task_id={task_id!r}")
        return state

    async def set_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            await conn.execute(
                "UPDATE task_steps SET expected = 0, updated_at = CURRENT_TIMESTAMP::text"
                " WHERE task_id = %s",
                (task_id,),
            )
            for helper in sorted(set(helpers)):
                await _upsert_step_expected_pg(conn, task_id, helper)

    async def add_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            for helper in sorted(set(helpers)):
                await _upsert_step_expected_pg(conn, task_id, helper)

    async def mark_helper_result(
        self,
        task_id: str,
        helper: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        attempt: int = 1,
        retryable: bool = False,
        error: str = "",
        source_message_id: str = "",
        failed_message_id: str = "",
    ) -> TaskState:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            await _upsert_step_result_pg(
                conn,
                task_id,
                helper,
                ok=ok,
                result=dict(result or {}),
                attempt=attempt,
                retryable=retryable,
                error=error,
                source_message_id=source_message_id,
            )
            await _insert_attempt_event_pg(
                conn,
                task_id,
                helper,
                attempt=attempt,
                event="result",
                status="completed" if ok else "failed",
                retryable=retryable,
                result=dict(result or {}),
                error=error,
                source_message_id=source_message_id,
                failed_message_id=failed_message_id,
            )
        state = await self.get(task_id)
        if state is None:
            raise RuntimeError(f"task state was not persisted for task_id={task_id!r}")
        return state

    async def get(self, task_id: str) -> TaskState | None:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            execution = await (
                await conn.execute(
                    "SELECT task_id, data_type, correlation_id, operation"
                    "  FROM task_executions WHERE task_id = %s",
                    (task_id,),
                )
            ).fetchone()
            if execution is None:
                return None
            step_rows = await (
                await conn.execute(
                    "SELECT helper, expected, completed, failed, operation, plan_json, result_json"
                    "     , attempt, last_status, retryable, next_attempt_at, lease_owner"
                    "     , lease_expires_at, last_dispatched_at, last_result_at, last_error"
                    "     , last_source_message_id"
                    "  FROM task_steps WHERE task_id = %s ORDER BY helper",
                    (task_id,),
                )
            ).fetchall()
            result_row = await (
                await conn.execute(
                    "SELECT final_status, result_json, published"
                    "  FROM task_results WHERE task_id = %s",
                    (task_id,),
                )
            ).fetchone()
            attempt_rows = await (
                await conn.execute(
                    "SELECT helper, attempt, event, status, retryable, source_message_id,"
                    "       failed_message_id, result_json, error, next_attempt_at, lease_owner,"
                    "       lease_expires_at, created_at"
                    "  FROM task_step_attempts WHERE task_id = %s ORDER BY id",
                    (task_id,),
                )
            ).fetchall()
        helper_results: dict[str, dict[str, Any]] = {}
        helper_plans: dict[str, dict[str, Any]] = {}
        helper_attempts: dict[str, list[dict[str, Any]]] = {}
        for row in step_rows:
            helper = str(row["helper"])
            if bool(row["completed"]) or bool(row["failed"]):
                helper_results[helper] = _loads_dict(row["result_json"])
            operation = str(row["operation"] or "")
            plan = _loads_dict(row["plan_json"])
            if operation or plan:
                helper_plans[helper] = {"operation": operation, "plan": plan}
        for row in attempt_rows:
            helper = str(row["helper"])
            helper_attempts.setdefault(helper, []).append(
                {
                    "attempt": int(row["attempt"]),
                    "event": str(row["event"]),
                    "status": str(row["status"]),
                    "retryable": bool(row["retryable"]),
                    "source_message_id": str(row["source_message_id"] or ""),
                    "failed_message_id": str(row["failed_message_id"] or ""),
                    "result": _loads_dict(row["result_json"]),
                    "error": str(row["error"] or ""),
                    "next_attempt_at": str(row["next_attempt_at"] or ""),
                    "lease_owner": str(row["lease_owner"] or ""),
                    "lease_expires_at": str(row["lease_expires_at"] or ""),
                    "created_at": str(row["created_at"] or ""),
                }
            )
        return TaskState(
            task_id=str(execution["task_id"]),
            data_type=str(execution["data_type"] or ""),
            correlation_id=str(execution["correlation_id"] or ""),
            operation=str(execution["operation"] or ""),
            expected_helpers={str(row["helper"]) for row in step_rows if bool(row["expected"])},
            completed_helpers={str(row["helper"]) for row in step_rows if bool(row["completed"])},
            failed_helpers={str(row["helper"]) for row in step_rows if bool(row["failed"])},
            helper_results=helper_results,
            helper_plans=helper_plans,
            helper_attempts=helper_attempts,
            final_status=str(result_row["final_status"] if result_row is not None else ""),
            final_result=_loads_dict(result_row["result_json"]) if result_row is not None else {},
            final_published=bool(result_row["published"]) if result_row is not None else False,
        )

    async def mark_final_published(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> TaskState:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            await conn.execute(
                "INSERT INTO task_results (task_id, final_status, result_json, published, published_at, updated_at)"
                " VALUES (%s, %s, %s, 1, CURRENT_TIMESTAMP::text, CURRENT_TIMESTAMP::text)"
                " ON CONFLICT(task_id) DO UPDATE SET"
                "   final_status = EXCLUDED.final_status,"
                "   result_json = EXCLUDED.result_json,"
                "   published = 1,"
                "   published_at = EXCLUDED.published_at,"
                "   updated_at = CURRENT_TIMESTAMP::text",
                (task_id, status, json.dumps(dict(result), sort_keys=True)),
            )
            await _touch_execution_pg(conn, task_id)
        state = await self.get(task_id)
        if state is None:
            raise RuntimeError(f"task state was not persisted for task_id={task_id!r}")
        return state

    async def record_helper_dispatch(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int = 1,
        source_message_id: str = "",
        lease_owner: str = "",
        lease_expires_at: str = "",
        next_attempt_at: str = "",
    ) -> TaskState:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            await _upsert_step_dispatch_pg(
                conn,
                task_id,
                helper,
                attempt=attempt,
                source_message_id=source_message_id,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                next_attempt_at=next_attempt_at,
            )
            await _insert_attempt_event_pg(
                conn,
                task_id,
                helper,
                attempt=attempt,
                event="dispatch",
                status="dispatched",
                retryable=False,
                source_message_id=source_message_id,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                next_attempt_at=next_attempt_at,
            )
        state = await self.get(task_id)
        if state is None:
            raise RuntimeError(f"task state was not persisted for task_id={task_id!r}")
        return state

    async def record_helper_attempt(
        self,
        task_id: str,
        helper: str,
        *,
        attempt: int,
        status: str,
        result: dict[str, Any] | None = None,
        retryable: bool = False,
        error: str = "",
        source_message_id: str = "",
        failed_message_id: str = "",
        next_attempt_at: str = "",
    ) -> TaskState:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            await _upsert_step_attempt_pg(
                conn,
                task_id,
                helper,
                attempt=attempt,
                status=status,
                retryable=retryable,
                error=error,
                source_message_id=source_message_id,
                next_attempt_at=next_attempt_at,
            )
            await _insert_attempt_event_pg(
                conn,
                task_id,
                helper,
                attempt=attempt,
                event="result",
                status=status,
                retryable=retryable,
                result=dict(result or {}),
                error=error,
                source_message_id=source_message_id,
                failed_message_id=failed_message_id,
                next_attempt_at=next_attempt_at,
            )
        state = await self.get(task_id)
        if state is None:
            raise RuntimeError(f"task state was not persisted for task_id={task_id!r}")
        return state

    async def claim_due_helper_dispatches(
        self,
        *,
        now: str,
        lease_owner: str,
        lease_expires_at: str,
        max_attempts: int,
        limit: int = 25,
    ) -> tuple[PendingHelperDispatch, ...]:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if limit < 1:
            return ()
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT
                        e.task_id,
                        e.data_type,
                        e.correlation_id,
                        COALESCE(NULLIF(s.operation, ''), e.operation) AS operation,
                        s.helper,
                        s.plan_json,
                        s.attempt,
                        s.last_status,
                        s.last_source_message_id,
                        s.next_attempt_at,
                        s.lease_owner,
                        s.lease_expires_at,
                        CASE
                            WHEN s.last_status = 'retrying'
                                 AND s.retryable = 1
                                 AND s.next_attempt_at IS NOT NULL
                                 AND s.next_attempt_at <= %s
                            THEN 'scheduled_retry'
                            WHEN s.last_status = 'dispatched'
                                 AND s.lease_expires_at IS NOT NULL
                                 AND s.lease_expires_at <= %s
                                 AND s.attempt < %s
                            THEN 'expired_lease'
                            WHEN s.last_status = 'dispatched'
                                 AND s.lease_expires_at IS NOT NULL
                                 AND s.lease_expires_at <= %s
                                 AND s.attempt >= %s
                            THEN 'expired_lease_terminal'
                            ELSE ''
                        END AS reason
                      FROM task_steps AS s
                      JOIN task_executions AS e
                        ON e.task_id = s.task_id
                      LEFT JOIN task_results AS r
                        ON r.task_id = s.task_id
                       AND r.published = 1
                     WHERE s.expected = 1
                       AND s.completed = 0
                       AND s.failed = 0
                       AND r.task_id IS NULL
                       AND e.data_type != ''
                       AND e.correlation_id != ''
                       AND COALESCE(NULLIF(s.operation, ''), e.operation) != ''
                       AND (
                            (
                                s.last_status = 'retrying'
                                AND s.retryable = 1
                                AND s.next_attempt_at IS NOT NULL
                                AND s.next_attempt_at <= %s
                                AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= %s)
                            )
                            OR (
                                s.last_status = 'dispatched'
                                AND s.lease_expires_at IS NOT NULL
                                AND s.lease_expires_at <= %s
                            )
                       )
                     ORDER BY s.updated_at, s.task_id, s.helper
                     LIMIT %s
                     FOR UPDATE OF s SKIP LOCKED
                    """,
                    (
                        now,
                        now,
                        max_attempts,
                        now,
                        max_attempts,
                        now,
                        now,
                        now,
                        limit,
                    ),
                )
            ).fetchall()
            claimed: list[PendingHelperDispatch] = []
            for row in rows:
                reason = str(row["reason"] or "")
                if not reason:
                    continue
                cursor = await conn.execute(
                    """
                    UPDATE task_steps
                       SET lease_owner = %s,
                           lease_expires_at = %s,
                           updated_at = CURRENT_TIMESTAMP::text
                     WHERE task_id = %s
                       AND helper = %s
                       AND expected = 1
                       AND completed = 0
                       AND failed = 0
                       AND (
                            (
                                %s = 'scheduled_retry'
                                AND last_status = 'retrying'
                                AND retryable = 1
                                AND next_attempt_at IS NOT NULL
                                AND next_attempt_at <= %s
                                AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
                            )
                            OR (
                                %s IN ('expired_lease', 'expired_lease_terminal')
                                AND last_status = 'dispatched'
                                AND lease_expires_at IS NOT NULL
                                AND lease_expires_at <= %s
                            )
                       )
                    """,
                    (
                        lease_owner,
                        _nullable_text(lease_expires_at),
                        str(row["task_id"]),
                        str(row["helper"]),
                        reason,
                        now,
                        now,
                        reason,
                        now,
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                claimed.append(_pending_dispatch_from_row(row))
        return tuple(claimed)

    async def record_helper_plan(
        self,
        task_id: str,
        helper: str,
        *,
        operation: str,
        plan: dict[str, Any],
    ) -> TaskState:
        await self._ensure_initialized()
        async with self._pool.connection() as conn:
            await _ensure_execution_pg(conn, task_id)
            await _upsert_step_plan_pg(
                conn,
                task_id,
                helper,
                operation=operation,
                plan=dict(plan),
            )
        state = await self.get(task_id)
        if state is None:
            raise RuntimeError(f"task state was not persisted for task_id={task_id!r}")
        return state


async def _ensure_execution_pg(
    conn: AsyncConnection,
    task_id: str,
    *,
    data_type: str = "",
    correlation_id: str = "",
    operation: str = "",
) -> None:
    await conn.execute(
        """
        INSERT INTO task_executions (task_id, data_type, correlation_id, operation, updated_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP::text)
        ON CONFLICT(task_id) DO UPDATE SET
            data_type = CASE
                WHEN EXCLUDED.data_type != '' THEN EXCLUDED.data_type
                ELSE task_executions.data_type
            END,
            correlation_id = CASE
                WHEN EXCLUDED.correlation_id != '' THEN EXCLUDED.correlation_id
                ELSE task_executions.correlation_id
            END,
            operation = CASE
                WHEN EXCLUDED.operation != '' THEN EXCLUDED.operation
                ELSE task_executions.operation
            END,
            updated_at = CURRENT_TIMESTAMP::text
        """,
        (task_id, data_type, correlation_id, operation),
    )


async def _upsert_step_expected_pg(conn: AsyncConnection, task_id: str, helper: str) -> None:
    await conn.execute(
        """
        INSERT INTO task_steps (task_id, helper, expected, updated_at)
        VALUES (%s, %s, 1, CURRENT_TIMESTAMP::text)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            updated_at = CURRENT_TIMESTAMP::text
        """,
        (task_id, helper),
    )
    await _touch_execution_pg(conn, task_id)


async def _upsert_step_result_pg(
    conn: AsyncConnection,
    task_id: str,
    helper: str,
    *,
    ok: bool,
    result: dict[str, Any],
    attempt: int = 1,
    retryable: bool = False,
    error: str = "",
    source_message_id: str = "",
) -> None:
    await conn.execute(
        """
        INSERT INTO task_steps (
            task_id, helper, expected, completed, failed, result_json, attempt,
            last_status, retryable, last_result_at, last_error, last_source_message_id, updated_at
        )
        VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP::text, %s, %s, CURRENT_TIMESTAMP::text)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            completed = EXCLUDED.completed,
            failed = EXCLUDED.failed,
            result_json = EXCLUDED.result_json,
            attempt = EXCLUDED.attempt,
            last_status = EXCLUDED.last_status,
            retryable = EXCLUDED.retryable,
            last_result_at = EXCLUDED.last_result_at,
            last_error = EXCLUDED.last_error,
            last_source_message_id = EXCLUDED.last_source_message_id,
            updated_at = CURRENT_TIMESTAMP::text
        """,
        (
            task_id,
            helper,
            1 if ok else 0,
            0 if ok else 1,
            json.dumps(result, sort_keys=True),
            _positive_attempt(attempt),
            "completed" if ok else "failed",
            1 if retryable else 0,
            error,
            source_message_id,
        ),
    )
    await _touch_execution_pg(conn, task_id)


async def _upsert_step_dispatch_pg(
    conn: AsyncConnection,
    task_id: str,
    helper: str,
    *,
    attempt: int,
    source_message_id: str,
    lease_owner: str,
    lease_expires_at: str,
    next_attempt_at: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO task_steps (
            task_id, helper, expected, attempt, last_status, retryable, next_attempt_at,
            lease_owner, lease_expires_at, last_dispatched_at, last_source_message_id, updated_at
        )
        VALUES (%s, %s, 1, %s, 'dispatched', 0, %s, %s, %s, CURRENT_TIMESTAMP::text, %s, CURRENT_TIMESTAMP::text)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            attempt = EXCLUDED.attempt,
            last_status = EXCLUDED.last_status,
            retryable = EXCLUDED.retryable,
            next_attempt_at = EXCLUDED.next_attempt_at,
            lease_owner = EXCLUDED.lease_owner,
            lease_expires_at = EXCLUDED.lease_expires_at,
            last_dispatched_at = EXCLUDED.last_dispatched_at,
            last_source_message_id = EXCLUDED.last_source_message_id,
            updated_at = CURRENT_TIMESTAMP::text
        """,
        (
            task_id,
            helper,
            _positive_attempt(attempt),
            _nullable_text(next_attempt_at),
            lease_owner,
            _nullable_text(lease_expires_at),
            source_message_id,
        ),
    )
    await _touch_execution_pg(conn, task_id)


async def _upsert_step_attempt_pg(
    conn: AsyncConnection,
    task_id: str,
    helper: str,
    *,
    attempt: int,
    status: str,
    retryable: bool,
    error: str,
    source_message_id: str,
    next_attempt_at: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO task_steps (
            task_id, helper, expected, attempt, last_status, retryable, next_attempt_at,
            last_result_at, last_error, last_source_message_id, updated_at
        )
        VALUES (%s, %s, 1, %s, %s, %s, %s, CURRENT_TIMESTAMP::text, %s, %s, CURRENT_TIMESTAMP::text)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            attempt = EXCLUDED.attempt,
            last_status = EXCLUDED.last_status,
            retryable = EXCLUDED.retryable,
            next_attempt_at = EXCLUDED.next_attempt_at,
            last_result_at = EXCLUDED.last_result_at,
            last_error = EXCLUDED.last_error,
            last_source_message_id = EXCLUDED.last_source_message_id,
            updated_at = CURRENT_TIMESTAMP::text
        """,
        (
            task_id,
            helper,
            _positive_attempt(attempt),
            status,
            1 if retryable else 0,
            _nullable_text(next_attempt_at),
            error,
            source_message_id,
        ),
    )
    await _touch_execution_pg(conn, task_id)


async def _upsert_step_plan_pg(
    conn: AsyncConnection,
    task_id: str,
    helper: str,
    *,
    operation: str,
    plan: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO task_steps (task_id, helper, expected, operation, plan_json, updated_at)
        VALUES (%s, %s, 1, %s, %s, CURRENT_TIMESTAMP::text)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            operation = EXCLUDED.operation,
            plan_json = EXCLUDED.plan_json,
            updated_at = CURRENT_TIMESTAMP::text
        """,
        (task_id, helper, operation, json.dumps(plan, sort_keys=True)),
    )
    await _touch_execution_pg(conn, task_id)


async def _insert_attempt_event_pg(
    conn: AsyncConnection,
    task_id: str,
    helper: str,
    *,
    attempt: int,
    event: str,
    status: str,
    retryable: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
    source_message_id: str = "",
    failed_message_id: str = "",
    next_attempt_at: str = "",
    lease_owner: str = "",
    lease_expires_at: str = "",
) -> None:
    await conn.execute(
        """
        INSERT INTO task_step_attempts (
            task_id, helper, attempt, event, status, retryable, source_message_id,
            failed_message_id, result_json, error, next_attempt_at, lease_owner, lease_expires_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            task_id,
            helper,
            _positive_attempt(attempt),
            event,
            status,
            1 if retryable else 0,
            source_message_id,
            failed_message_id,
            json.dumps(dict(result or {}), sort_keys=True),
            error,
            _nullable_text(next_attempt_at),
            lease_owner,
            _nullable_text(lease_expires_at),
        ),
    )


async def _touch_execution_pg(conn: AsyncConnection, task_id: str) -> None:
    await conn.execute(
        "UPDATE task_executions SET updated_at = CURRENT_TIMESTAMP::text WHERE task_id = %s",
        (task_id,),
    )


def _pending_dispatch_from_row(row: Mapping[str, Any]) -> PendingHelperDispatch:
    return PendingHelperDispatch(
        task_id=str(row["task_id"]),
        data_type=str(row["data_type"] or ""),
        correlation_id=str(row["correlation_id"] or ""),
        operation=str(row["operation"] or ""),
        helper=str(row["helper"]),
        plan=_loads_dict(row["plan_json"]),
        attempt=int(row["attempt"]),
        reason=str(row["reason"]),
        last_source_message_id=str(row["last_source_message_id"] or ""),
        next_attempt_at=str(row["next_attempt_at"] or ""),
        lease_owner=str(row["lease_owner"] or ""),
        lease_expires_at=str(row["lease_expires_at"] or ""),
    )


def _attempt_payload(
    *,
    attempt: int,
    event: str,
    status: str,
    retryable: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
    source_message_id: str = "",
    failed_message_id: str = "",
    next_attempt_at: str = "",
    lease_owner: str = "",
    lease_expires_at: str = "",
) -> dict[str, Any]:
    return {
        "attempt": _positive_attempt(attempt),
        "event": event,
        "status": status,
        "retryable": bool(retryable),
        "source_message_id": source_message_id,
        "failed_message_id": failed_message_id,
        "result": dict(result or {}),
        "error": error,
        "next_attempt_at": next_attempt_at,
        "lease_owner": lease_owner,
        "lease_expires_at": lease_expires_at,
    }


def _positive_attempt(value: int) -> int:
    attempt = int(value)
    if attempt < 1:
        raise ValueError("attempt must be a positive integer")
    return attempt


def _nullable_text(value: str) -> str | None:
    value = str(value or "")
    return value or None


def _loads_dict(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("stored final result must be a mapping")
    return dict(loaded)
