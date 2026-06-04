"""Phase 10 tests: health checks, metrics, and operations."""

from __future__ import annotations

import unittest

from rag_server.health import (
    ComponentStatus,
    HealthChecker,
    HealthReport,
    MetricsCollector,
    MetricsSnapshot,
)


class HealthCheckerTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_components_healthy(self) -> None:
        checker = HealthChecker(
            qdrant_store=True,
            embed_fn=True,
            rerank_fn=True,
            tier1_cache=True,
            tier2_cache=True,
            config_repo=True,
            openrouter_client=True,
        )
        report = await checker.check()
        self.assertEqual(report.status, "healthy")
        self.assertEqual(len(report.components), 8)

    async def test_some_missing_components_degraded(self) -> None:
        checker = HealthChecker(
            qdrant_store=True,
            embed_fn=None,
            rerank_fn=None,
        )
        report = await checker.check()
        self.assertEqual(report.status, "degraded")

    async def test_all_missing_components_unhealthy(self) -> None:
        checker = HealthChecker()
        report = await checker.check()
        self.assertEqual(report.status, "unhealthy")


class MetricsCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metrics = MetricsCollector()

    def test_initial_snapshot_all_zeros(self) -> None:
        snap = self.metrics.snapshot()
        self.assertEqual(snap.search_requests_total, 0)
        self.assertEqual(snap.search_cache_hit_ratio, 0.0)
        self.assertEqual(snap.avg_search_latency_ms, 0.0)

    def test_record_search_request_and_cache_hit(self) -> None:
        self.metrics.record_search_request()
        self.metrics.record_search_request()
        self.metrics.record_search_cache_hit()

        snap = self.metrics.snapshot()
        self.assertEqual(snap.search_requests_total, 2)
        self.assertEqual(snap.search_cache_hit_ratio, 0.5)

    def test_record_search_latency_avg(self) -> None:
        self.metrics.record_search_latency(100.0)
        self.metrics.record_search_latency(200.0)

        snap = self.metrics.snapshot()
        self.assertEqual(snap.avg_search_latency_ms, 150.0)

    def test_record_generate_and_cache_hit(self) -> None:
        self.metrics.record_generate_request()
        self.metrics.record_generate_request()
        self.metrics.record_generate_cache_hit()

        snap = self.metrics.snapshot()
        self.assertEqual(snap.generate_requests_total, 2)
        self.assertEqual(snap.generate_cache_hit_ratio, 0.5)

    def test_record_ingest_jobs_and_failures(self) -> None:
        self.metrics.record_ingest_job()
        self.metrics.record_ingest_job()
        self.metrics.record_ingest_job()
        self.metrics.record_ingest_job_failed()

        snap = self.metrics.snapshot()
        self.assertEqual(snap.ingest_jobs_total, 3)
        self.assertEqual(snap.ingest_jobs_failed, 1)

    def test_queue_depth(self) -> None:
        self.metrics.set_queue_depth(5)
        snap = self.metrics.snapshot()
        self.assertEqual(snap.queue_depth, 5)

    def test_reset_clears_all(self) -> None:
        self.metrics.record_search_request()
        self.metrics.reset()

        snap = self.metrics.snapshot()
        self.assertEqual(snap.search_requests_total, 0)


if __name__ == "__main__":
    unittest.main()
