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
    expected_helpers: set[str] = field(default_factory=set)
    completed_helpers: set[str] = field(default_factory=set)
    failed_helpers: set[str] = field(default_factory=set)
    helper_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    helper_plans: dict[str, dict[str, Any]] = field(default_factory=dict)
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


class TaskStateRepository(Protocol):
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

    async def mark_final_published(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> TaskState:
        ...


class InMemoryTaskStateRepository:
    def __init__(self) -> None:
        self._states: dict[str, TaskState] = {}

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


class SQLiteTaskStateRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def set_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        state = await self.get(task_id) or TaskState(task_id=task_id)
        state.expected_helpers = set(helpers)
        self._upsert(state)

    async def add_expected_helpers(self, task_id: str, helpers: tuple[str, ...]) -> None:
        state = await self.get(task_id) or TaskState(task_id=task_id)
        state.expected_helpers.update(helpers)
        self._upsert(state)

    async def mark_helper_result(
        self,
        task_id: str,
        helper: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
    ) -> TaskState:
        state = await self.get(task_id) or TaskState(task_id=task_id)
        state.expected_helpers.add(helper)
        if ok:
            state.completed_helpers.add(helper)
            state.failed_helpers.discard(helper)
        else:
            state.failed_helpers.add(helper)
            state.completed_helpers.discard(helper)
        state.helper_results[helper] = dict(result or {})
        self._upsert(state)
        return state

    async def get(self, task_id: str) -> TaskState | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
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
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
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

    async def mark_final_published(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> TaskState:
        state = await self.get(task_id) or TaskState(task_id=task_id)
        state.final_status = status
        state.final_result = dict(result)
        state.final_published = True
        self._upsert(state)
        return state

    async def record_helper_plan(
        self,
        task_id: str,
        helper: str,
        *,
        operation: str,
        plan: dict[str, Any],
    ) -> TaskState:
        state = await self.get(task_id) or TaskState(task_id=task_id)
        state.expected_helpers.add(helper)
        state.helper_plans[helper] = {
            "operation": operation,
            "plan": dict(plan),
        }
        self._upsert(state)
        return state

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_states (
                    task_id TEXT PRIMARY KEY,
                    expected_helpers TEXT NOT NULL,
                    completed_helpers TEXT NOT NULL,
                    failed_helpers TEXT NOT NULL,
                    helper_results TEXT NOT NULL,
                    helper_plans TEXT NOT NULL DEFAULT '{}',
                    final_status TEXT NOT NULL DEFAULT '',
                    final_result TEXT NOT NULL DEFAULT '{}',
                    final_published INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            _ensure_column(conn, "task_states", "final_status", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "task_states", "final_result", "TEXT NOT NULL DEFAULT '{}'")
            _ensure_column(conn, "task_states", "final_published", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(conn, "task_states", "helper_plans", "TEXT NOT NULL DEFAULT '{}'")

    def _upsert(self, state: TaskState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_states (
                    task_id,
                    expected_helpers,
                    completed_helpers,
                    failed_helpers,
                    helper_results,
                    helper_plans,
                    final_status,
                    final_result,
                    final_published,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(task_id) DO UPDATE SET
                    expected_helpers = excluded.expected_helpers,
                    completed_helpers = excluded.completed_helpers,
                    failed_helpers = excluded.failed_helpers,
                    helper_results = excluded.helper_results,
                    helper_plans = excluded.helper_plans,
                    final_status = excluded.final_status,
                    final_result = excluded.final_result,
                    final_published = excluded.final_published,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    state.task_id,
                    _dumps_list(state.expected_helpers),
                    _dumps_list(state.completed_helpers),
                    _dumps_list(state.failed_helpers),
                    json.dumps(state.helper_results, sort_keys=True),
                    json.dumps(state.helper_plans, sort_keys=True),
                    state.final_status,
                    json.dumps(state.final_result, sort_keys=True),
                    1 if state.final_published else 0,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


def _dumps_list(values: set[str]) -> str:
    return json.dumps(sorted(values), sort_keys=True)


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
