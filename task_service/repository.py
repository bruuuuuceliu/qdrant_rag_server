"""Task service-owned execution state repository."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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


class SQLiteTaskStateRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def record_execution(
        self,
        task_id: str,
        *,
        data_type: str = "",
        correlation_id: str = "",
        operation: str = "",
    ) -> TaskState:
        with self._connect() as conn:
            _ensure_execution(
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
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            conn.execute(
                """
                UPDATE task_steps
                   SET expected = 0,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE task_id = ?
                """,
                (task_id,),
            )
            for helper in sorted(set(helpers)):
                _upsert_step_expected(conn, task_id, helper)

    async def add_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            for helper in sorted(set(helpers)):
                _upsert_step_expected(conn, task_id, helper)

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
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            _upsert_step_result(
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
            _insert_attempt_event(
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
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            execution = conn.execute(
                """
                SELECT task_id, data_type, correlation_id, operation
                  FROM task_executions
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if execution is None:
                return None
            step_rows = conn.execute(
                """
                SELECT helper, expected, completed, failed, operation, plan_json, result_json
                     , attempt, last_status, retryable, next_attempt_at, lease_owner
                     , lease_expires_at, last_dispatched_at, last_result_at, last_error
                     , last_source_message_id
                  FROM task_steps
                 WHERE task_id = ?
                 ORDER BY helper
                """,
                (task_id,),
            ).fetchall()
            result_row = conn.execute(
                """
                SELECT final_status, result_json, published
                  FROM task_results
                 WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            attempt_rows = conn.execute(
                """
                SELECT
                    helper,
                    attempt,
                    event,
                    status,
                    retryable,
                    source_message_id,
                    failed_message_id,
                    result_json,
                    error,
                    next_attempt_at,
                    lease_owner,
                    lease_expires_at,
                    created_at
                  FROM task_step_attempts
                 WHERE task_id = ?
                 ORDER BY id
                """,
                (task_id,),
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
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            conn.execute(
                """
                INSERT INTO task_results (
                    task_id,
                    final_status,
                    result_json,
                    published,
                    published_at,
                    updated_at
                )
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(task_id) DO UPDATE SET
                    final_status = excluded.final_status,
                    result_json = excluded.result_json,
                    published = 1,
                    published_at = excluded.published_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (task_id, status, json.dumps(dict(result), sort_keys=True)),
            )
            conn.execute(
                """
                UPDATE task_executions
                   SET updated_at = CURRENT_TIMESTAMP
                 WHERE task_id = ?
                """,
                (task_id,),
            )
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
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            _upsert_step_dispatch(
                conn,
                task_id,
                helper,
                attempt=attempt,
                source_message_id=source_message_id,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                next_attempt_at=next_attempt_at,
            )
            _insert_attempt_event(
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
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            _upsert_step_attempt(
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
            _insert_attempt_event(
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
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
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
                             AND s.next_attempt_at <= ?
                        THEN 'scheduled_retry'
                        WHEN s.last_status = 'dispatched'
                             AND s.lease_expires_at IS NOT NULL
                             AND s.lease_expires_at <= ?
                             AND s.attempt < ?
                        THEN 'expired_lease'
                        WHEN s.last_status = 'dispatched'
                             AND s.lease_expires_at IS NOT NULL
                             AND s.lease_expires_at <= ?
                             AND s.attempt >= ?
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
                            AND s.next_attempt_at <= ?
                            AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= ?)
                        )
                        OR (
                            s.last_status = 'dispatched'
                            AND s.lease_expires_at IS NOT NULL
                            AND s.lease_expires_at <= ?
                        )
                   )
                 ORDER BY s.updated_at, s.task_id, s.helper
                 LIMIT ?
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
            ).fetchall()
            claimed: list[PendingHelperDispatch] = []
            for row in rows:
                reason = str(row["reason"] or "")
                if not reason:
                    continue
                cursor = conn.execute(
                    """
                    UPDATE task_steps
                       SET lease_owner = ?,
                           lease_expires_at = ?,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE task_id = ?
                       AND helper = ?
                       AND expected = 1
                       AND completed = 0
                       AND failed = 0
                       AND (
                            (
                                ? = 'scheduled_retry'
                                AND last_status = 'retrying'
                                AND retryable = 1
                                AND next_attempt_at IS NOT NULL
                                AND next_attempt_at <= ?
                                AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                            )
                            OR (
                                ? IN ('expired_lease', 'expired_lease_terminal')
                                AND last_status = 'dispatched'
                                AND lease_expires_at IS NOT NULL
                                AND lease_expires_at <= ?
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
        with self._connect() as conn:
            _ensure_execution(conn, task_id)
            _upsert_step_plan(
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

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_executions (
                    task_id TEXT PRIMARY KEY,
                    data_type TEXT NOT NULL DEFAULT '',
                    correlation_id TEXT NOT NULL DEFAULT '',
                    operation TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (task_id, helper),
                    FOREIGN KEY (task_id) REFERENCES task_executions(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_steps_task_complete
                    ON task_steps(task_id, completed, failed);
                CREATE INDEX IF NOT EXISTS idx_task_steps_helper
                    ON task_steps(helper);

                CREATE TABLE IF NOT EXISTS task_step_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id, helper) REFERENCES task_steps(task_id, helper)
                );
                CREATE INDEX IF NOT EXISTS idx_task_step_attempts_task_helper
                    ON task_step_attempts(task_id, helper, attempt);
                CREATE INDEX IF NOT EXISTS idx_task_step_attempts_status
                    ON task_step_attempts(status, retryable);

                CREATE TABLE IF NOT EXISTS task_results (
                    task_id TEXT PRIMARY KEY,
                    final_status TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    published INTEGER NOT NULL DEFAULT 0,
                    published_at TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES task_executions(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_results_published
                    ON task_results(published, final_status);
                """
            )
            _ensure_task_execution_columns(conn)
            _ensure_task_step_columns(conn)
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_task_steps_next_attempt
                    ON task_steps(next_attempt_at, completed, failed);
                CREATE INDEX IF NOT EXISTS idx_task_steps_lease
                    ON task_steps(lease_owner, lease_expires_at);
                """
            )
            _migrate_legacy_task_states(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _ensure_execution(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    data_type: str = "",
    correlation_id: str = "",
    operation: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO task_executions (
            task_id,
            data_type,
            correlation_id,
            operation,
            updated_at
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id) DO UPDATE SET
            data_type = CASE
                WHEN excluded.data_type != '' THEN excluded.data_type
                ELSE task_executions.data_type
            END,
            correlation_id = CASE
                WHEN excluded.correlation_id != '' THEN excluded.correlation_id
                ELSE task_executions.correlation_id
            END,
            operation = CASE
                WHEN excluded.operation != '' THEN excluded.operation
                ELSE task_executions.operation
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (task_id, data_type, correlation_id, operation),
    )


def _upsert_step_expected(conn: sqlite3.Connection, task_id: str, helper: str) -> None:
    conn.execute(
        """
        INSERT INTO task_steps (
            task_id,
            helper,
            expected,
            updated_at
        )
        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (task_id, helper),
    )
    _touch_execution(conn, task_id)


def _upsert_step_result(
    conn: sqlite3.Connection,
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
    conn.execute(
        """
        INSERT INTO task_steps (
            task_id,
            helper,
            expected,
            completed,
            failed,
            result_json,
            attempt,
            last_status,
            retryable,
            last_result_at,
            last_error,
            last_source_message_id,
            updated_at
        )
        VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            completed = excluded.completed,
            failed = excluded.failed,
            result_json = excluded.result_json,
            attempt = excluded.attempt,
            last_status = excluded.last_status,
            retryable = excluded.retryable,
            last_result_at = excluded.last_result_at,
            last_error = excluded.last_error,
            last_source_message_id = excluded.last_source_message_id,
            updated_at = CURRENT_TIMESTAMP
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
    _touch_execution(conn, task_id)


def _upsert_step_dispatch(
    conn: sqlite3.Connection,
    task_id: str,
    helper: str,
    *,
    attempt: int,
    source_message_id: str,
    lease_owner: str,
    lease_expires_at: str,
    next_attempt_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO task_steps (
            task_id,
            helper,
            expected,
            attempt,
            last_status,
            retryable,
            next_attempt_at,
            lease_owner,
            lease_expires_at,
            last_dispatched_at,
            last_source_message_id,
            updated_at
        )
        VALUES (?, ?, 1, ?, 'dispatched', 0, ?, ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            attempt = excluded.attempt,
            last_status = excluded.last_status,
            retryable = excluded.retryable,
            next_attempt_at = excluded.next_attempt_at,
            lease_owner = excluded.lease_owner,
            lease_expires_at = excluded.lease_expires_at,
            last_dispatched_at = excluded.last_dispatched_at,
            last_source_message_id = excluded.last_source_message_id,
            updated_at = CURRENT_TIMESTAMP
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
    _touch_execution(conn, task_id)


def _upsert_step_attempt(
    conn: sqlite3.Connection,
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
    conn.execute(
        """
        INSERT INTO task_steps (
            task_id,
            helper,
            expected,
            attempt,
            last_status,
            retryable,
            next_attempt_at,
            last_result_at,
            last_error,
            last_source_message_id,
            updated_at
        )
        VALUES (?, ?, 1, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            attempt = excluded.attempt,
            last_status = excluded.last_status,
            retryable = excluded.retryable,
            next_attempt_at = excluded.next_attempt_at,
            last_result_at = excluded.last_result_at,
            last_error = excluded.last_error,
            last_source_message_id = excluded.last_source_message_id,
            updated_at = CURRENT_TIMESTAMP
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
    _touch_execution(conn, task_id)


def _upsert_step_plan(
    conn: sqlite3.Connection,
    task_id: str,
    helper: str,
    *,
    operation: str,
    plan: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO task_steps (
            task_id,
            helper,
            expected,
            operation,
            plan_json,
            updated_at
        )
        VALUES (?, ?, 1, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id, helper) DO UPDATE SET
            expected = 1,
            operation = excluded.operation,
            plan_json = excluded.plan_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (task_id, helper, operation, json.dumps(plan, sort_keys=True)),
    )
    _touch_execution(conn, task_id)


def _insert_attempt_event(
    conn: sqlite3.Connection,
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
    conn.execute(
        """
        INSERT INTO task_step_attempts (
            task_id,
            helper,
            attempt,
            event,
            status,
            retryable,
            source_message_id,
            failed_message_id,
            result_json,
            error,
            next_attempt_at,
            lease_owner,
            lease_expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _touch_execution(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute(
        """
        UPDATE task_executions
           SET updated_at = CURRENT_TIMESTAMP
         WHERE task_id = ?
        """,
        (task_id,),
    )


def _migrate_legacy_task_states(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "task_states"):
        return
    _ensure_column(conn, "task_states", "final_status", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "task_states", "final_result", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "task_states", "final_published", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "task_states", "helper_plans", "TEXT NOT NULL DEFAULT '{}'")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            task_id,
            expected_helpers,
            completed_helpers,
            failed_helpers,
            helper_results,
            helper_plans,
            final_status,
            final_result,
            final_published
          FROM task_states
         ORDER BY task_id
        """
    ).fetchall()
    for row in rows:
        if _execution_exists(conn, str(row["task_id"])):
            continue
        _write_state(conn, _state_from_legacy_row(row))


def _write_state(conn: sqlite3.Connection, state: TaskState) -> None:
    _ensure_execution(conn, state.task_id)
    helpers = (
        state.expected_helpers
        | state.completed_helpers
        | state.failed_helpers
        | set(state.helper_results)
        | set(state.helper_plans)
    )
    for helper in sorted(helpers):
        plan_record = state.helper_plans.get(helper, {})
        operation = str(plan_record.get("operation", "")) if isinstance(plan_record, dict) else ""
        plan = plan_record.get("plan", {}) if isinstance(plan_record, dict) else {}
        if not isinstance(plan, dict):
            plan = {}
        conn.execute(
            """
            INSERT INTO task_steps (
                task_id,
                helper,
                expected,
                completed,
                failed,
                operation,
                plan_json,
                result_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(task_id, helper) DO UPDATE SET
                expected = excluded.expected,
                completed = excluded.completed,
                failed = excluded.failed,
                operation = excluded.operation,
                plan_json = excluded.plan_json,
                result_json = excluded.result_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                state.task_id,
                helper,
                1 if helper in state.expected_helpers else 0,
                1 if helper in state.completed_helpers else 0,
                1 if helper in state.failed_helpers else 0,
                operation,
                json.dumps(dict(plan), sort_keys=True),
                json.dumps(dict(state.helper_results.get(helper, {})), sort_keys=True),
            ),
        )
    if state.final_status or state.final_result or state.final_published:
        conn.execute(
            """
            INSERT INTO task_results (
                task_id,
                final_status,
                result_json,
                published,
                published_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END, CURRENT_TIMESTAMP)
            ON CONFLICT(task_id) DO UPDATE SET
                final_status = excluded.final_status,
                result_json = excluded.result_json,
                published = excluded.published,
                published_at = excluded.published_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                state.task_id,
                state.final_status,
                json.dumps(state.final_result, sort_keys=True),
                1 if state.final_published else 0,
                1 if state.final_published else 0,
            ),
        )


def _state_from_legacy_row(row: sqlite3.Row) -> TaskState:
    return TaskState(
        task_id=str(row["task_id"]),
        expected_helpers=set(_loads_list(row["expected_helpers"])),
        completed_helpers=set(_loads_list(row["completed_helpers"])),
        failed_helpers=set(_loads_list(row["failed_helpers"])),
        helper_results=_loads_mapping(row["helper_results"]),
        helper_plans=_loads_mapping(row["helper_plans"]),
        final_status=str(row["final_status"] or ""),
        final_result=_loads_dict(row["final_result"]),
        final_published=bool(row["final_published"]),
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _execution_exists(conn: sqlite3.Connection, task_id: str) -> bool:
    row = conn.execute(
        "SELECT task_id FROM task_executions WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return row is not None


def _ensure_task_step_columns(conn: sqlite3.Connection) -> None:
    columns = {
        "attempt": "INTEGER NOT NULL DEFAULT 0",
        "last_status": "TEXT NOT NULL DEFAULT ''",
        "retryable": "INTEGER NOT NULL DEFAULT 0",
        "next_attempt_at": "TEXT",
        "lease_owner": "TEXT NOT NULL DEFAULT ''",
        "lease_expires_at": "TEXT",
        "last_dispatched_at": "TEXT",
        "last_result_at": "TEXT",
        "last_error": "TEXT NOT NULL DEFAULT ''",
        "last_source_message_id": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in columns.items():
        _ensure_column(conn, "task_steps", column, definition)


def _ensure_task_execution_columns(conn: sqlite3.Connection) -> None:
    columns = {
        "data_type": "TEXT NOT NULL DEFAULT ''",
        "correlation_id": "TEXT NOT NULL DEFAULT ''",
        "operation": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in columns.items():
        _ensure_column(conn, "task_executions", column, definition)


def _pending_dispatch_from_row(row: sqlite3.Row) -> PendingHelperDispatch:
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


def _loads_list(value: str) -> list[str]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise ValueError("stored task helper set must be a list")
    return [str(item) for item in loaded]


def _loads_mapping(value: str) -> dict[str, dict[str, Any]]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("stored helper results must be a mapping")
    results: dict[str, dict[str, Any]] = {}
    for helper, result in loaded.items():
        results[str(helper)] = dict(result if isinstance(result, dict) else {})
    return results


def _loads_dict(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("stored final result must be a mapping")
    return dict(loaded)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
