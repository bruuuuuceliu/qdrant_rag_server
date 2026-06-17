"""SQLite queue broker tests."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.queue import QueueFullError, QueueMessage, SQLiteQueueBroker


class SQLiteQueueBrokerTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_consume_across_instances(self) -> None:
        with TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "queue.db"
            producer = SQLiteQueueBroker(db_path)
            consumer = SQLiteQueueBroker(db_path)

            await producer.publish(
                QueueMessage(
                    topic="ingestion.requests",
                    key="job1",
                    payload={"doc_id": "d1"},
                    headers={"correlation_id": "job1"},
                )
            )

            message = await consumer.consume("ingestion.requests")

            self.assertEqual(message.key, "job1")
            self.assertEqual(message.payload["doc_id"], "d1")
            self.assertEqual(producer.depth("ingestion.requests"), 1)
            consumer.task_done("ingestion.requests")
            self.assertEqual(producer.depth("ingestion.requests"), 0)

    async def test_publish_raises_when_topic_full(self) -> None:
        with TemporaryDirectory() as tempdir:
            broker = SQLiteQueueBroker(Path(tempdir) / "queue.db", maxsize=1)
            await broker.publish(QueueMessage(topic="t", key="1", payload={}))

            with self.assertRaises(QueueFullError):
                await broker.publish(QueueMessage(topic="t", key="2", payload={}))

    async def test_consume_waits_for_later_message(self) -> None:
        with TemporaryDirectory() as tempdir:
            broker = SQLiteQueueBroker(Path(tempdir) / "queue.db", poll_interval=0.01)
            task = asyncio.create_task(broker.consume("t"))
            await asyncio.sleep(0.02)
            await broker.publish(QueueMessage(topic="t", key="1", payload={"ok": True}))

            message = await asyncio.wait_for(task, timeout=1)

            self.assertTrue(message.payload["ok"])
            broker.task_done("t")


if __name__ == "__main__":
    unittest.main()
