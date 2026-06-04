"""Health checks and operational metrics for the RAG engine.

Provides component-level health probes and simple in-memory metrics
tracking for latency, cache hit rate, queue depth, and saturation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComponentStatus:
    name: str
    healthy: bool
    message: str = ""


@dataclass
class HealthReport:
    status: str  # "healthy" | "degraded" | "unhealthy"
    components: list[ComponentStatus] = field(default_factory=list)


@dataclass
class MetricsSnapshot:
    search_requests_total: int = 0
    search_cache_hits_total: int = 0
    search_latency_ms_total: float = 0.0
    search_latency_count: int = 0
    generate_requests_total: int = 0
    generate_cache_hits_total: int = 0
    ingest_jobs_total: int = 0
    ingest_jobs_failed: int = 0
    queue_depth: int = 0

    @property
    def search_cache_hit_ratio(self) -> float:
        if self.search_requests_total == 0:
            return 0.0
        return self.search_cache_hits_total / self.search_requests_total

    @property
    def avg_search_latency_ms(self) -> float:
        if self.search_latency_count == 0:
            return 0.0
        return self.search_latency_ms_total / self.search_latency_count

    @property
    def generate_cache_hit_ratio(self) -> float:
        if self.generate_requests_total == 0:
            return 0.0
        return self.generate_cache_hits_total / self.generate_requests_total


class HealthChecker:
    """Probes all engine components and returns a health report."""

    def __init__(
        self,
        *,
        qdrant_store: Any = None,
        embed_fn: Any = None,
        rerank_fn: Any = None,
        tier1_cache: Any = None,
        tier2_cache: Any = None,
        config_repo: Any = None,
        openrouter_client: Any = None,
    ) -> None:
        self._qdrant_store = qdrant_store
        self._embed_fn = embed_fn
        self._rerank_fn = rerank_fn
        self._tier1_cache = tier1_cache
        self._tier2_cache = tier2_cache
        self._config_repo = config_repo
        self._openrouter_client = openrouter_client

    async def check(self) -> HealthReport:
        components: list[ComponentStatus] = []

        components.append(self._check_component("gateway", True))
        components.append(self._check_component("qdrant", self._qdrant_store is not None))
        components.append(self._check_component("embedding_model", self._embed_fn is not None))
        components.append(self._check_component("reranker_model", self._rerank_fn is not None))
        components.append(self._check_component("tier1_cache", self._tier1_cache is not None))
        components.append(self._check_component("tier2_cache", self._tier2_cache is not None))
        components.append(self._check_component("config_db", self._config_repo is not None))
        components.append(self._check_component("openrouter", self._openrouter_client is not None))

        available_count = sum(1 for c in components if c.healthy)
        total = len(components)

        if available_count == total:
            status = "healthy"
        elif available_count > 1:  # gateway + at least one other
            status = "degraded"
        else:
            status = "unhealthy"

        return HealthReport(status=status, components=components)

    @staticmethod
    def _check_component(name: str, available: bool) -> ComponentStatus:
        return ComponentStatus(
            name=name,
            healthy=available,
            message="healthy" if available else "unavailable",
        )


class MetricsCollector:
    """Thread-safe in-memory metrics for the RAG engine."""

    def __init__(self) -> None:
        self._snapshot = MetricsSnapshot()

    def record_search_request(self) -> None:
        self._snapshot.search_requests_total += 1

    def record_search_cache_hit(self) -> None:
        self._snapshot.search_cache_hits_total += 1

    def record_search_latency(self, latency_ms: float) -> None:
        self._snapshot.search_latency_ms_total += latency_ms
        self._snapshot.search_latency_count += 1

    def record_generate_request(self) -> None:
        self._snapshot.generate_requests_total += 1

    def record_generate_cache_hit(self) -> None:
        self._snapshot.generate_cache_hits_total += 1

    def record_ingest_job(self) -> None:
        self._snapshot.ingest_jobs_total += 1

    def record_ingest_job_failed(self) -> None:
        self._snapshot.ingest_jobs_failed += 1

    def set_queue_depth(self, depth: int) -> None:
        self._snapshot.queue_depth = depth

    def snapshot(self) -> MetricsSnapshot:
        return self._snapshot

    def reset(self) -> None:
        self._snapshot = MetricsSnapshot()
