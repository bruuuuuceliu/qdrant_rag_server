"""SQLite-backed queue broker for local multi-process development."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from shared.queue.protocols import QueueBroker, QueueFullError, QueueMessage


class SQLiteQueueBroker(QueueBroker):
    """Small durable-ish queue broker shared by local service processes.

    This is not a production broker. It exists to exercise real process
    boundaries locally while keeping the transport contract replaceable.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        maxsize: int = 0,
        poll_interval: float = 0.05,
    ) -> None:
        self.db_path = Path(db_path)
        self._maxsize = maxsize
        self._poll_interval = poll_interval
        self._claimed: dict[int, str] = {}
        self._initialize()

    async def publish(self, message: QueueMessage) -> None:
        self._publish_sync(message)

    async def consume(self, topic: str) -> QueueMessage:
        while True:
            message = self._consume_once_sync(topic)
            if message is not None:
                return message
            await asyncio.sleep(self._poll_interval)

    def task_done(self, topic: str) -> None:
        ids = [message_id for message_id, t in self._claimed.items() if t == topic]
        if not ids:
            return
        message_id = ids[0]
        with self._connect() as connection:
            connection.execute("DELETE FROM queue_messages WHERE id = ?", (message_id,))
        self._claimed.pop(message_id, None)

    def depth(self, topic: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM queue_messages WHERE topic = ?",
                (topic,),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    async def join(self, topic: str) -> None:
        while self.depth(topic) > 0:
            await asyncio.sleep(self._poll_interval)

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    message_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    headers_json TEXT NOT NULL,
                    claimed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_messages_topic_claimed_id
                ON queue_messages(topic, claimed, id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _publish_sync(self, message: QueueMessage) -> None:
        with self._connect() as connection:
            if self._maxsize > 0:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM queue_messages WHERE topic = ?",
                    (message.topic,),
                ).fetchone()
                if int(row["count"]) >= self._maxsize:
                    raise QueueFullError(f"queue topic {message.topic!r} is full")
            connection.execute(
                """
                INSERT INTO queue_messages (
                    topic, message_key, payload_json, headers_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message.topic,
                    message.key,
                    json.dumps(message.payload, sort_keys=True),
                    json.dumps(message.headers, sort_keys=True),
                    time.time(),
                ),
            )

    def _consume_once_sync(self, topic: str) -> QueueMessage | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, topic, message_key, payload_json, headers_json
                FROM queue_messages
                WHERE topic = ? AND claimed = 0
                ORDER BY id
                LIMIT 1
                """,
                (topic,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE queue_messages SET claimed = 1 WHERE id = ?",
                (row["id"],),
            )

        message_id = int(row["id"])
        self._claimed[message_id] = topic
        return QueueMessage(
            topic=str(row["topic"]),
            key=str(row["message_key"]),
            payload=_load_object(row["payload_json"]),
            headers={str(k): str(v) for k, v in _load_object(row["headers_json"]).items()},
        )


def _load_object(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("queue payload JSON must be an object")
    return loaded
