"""Project planning API tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from project_service.gateway.requests import (
    DeleteDocumentRequest,
    IngestRequest,
    SearchRequest,
)
from project_service.planning import ProjectPlanningService
from retrieval_service.placement import (
    InMemoryPlacementRepository,
    InMemoryRoutingPolicyRepository,
    InMemoryRetrievalShardRepository,
    PlacementResolver,
    RetrievalShard,
    RoutingPolicy,
)


class ProjectPlanningServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_plan_search_exposes_project_owned_retrieval_inputs(self) -> None:
        gateway = _Gateway()
        service = ProjectPlanningService(gateway=gateway)

        plan = await service.plan_search(
            SearchRequest(project_id="p1", user_id="u1", query="hello")
        )

        self.assertEqual(plan.project_id, "p1")
        self.assertEqual(plan.user_id, "u1")
        self.assertEqual(plan.query_text, "hello")
        self.assertEqual(plan.collection_name, "rag_p1_v1")
        self.assertEqual(plan.retrieval_config, {"top_k": 3})
        self.assertIs(plan.retrieval_filter, gateway.search_plan.retrieval_filter)
        gateway.prepare_search.assert_awaited_once()

    async def test_plan_delete_exposes_project_owned_delete_inputs(self) -> None:
        gateway = _Gateway()
        service = ProjectPlanningService(gateway=gateway)

        plan = await service.plan_delete(
            DeleteDocumentRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
            )
        )

        self.assertEqual(plan.project_id, "p1")
        self.assertEqual(plan.user_id, "u1")
        self.assertEqual(plan.kb_id, "kb")
        self.assertEqual(plan.doc_id, "d1")
        self.assertEqual(plan.collection_name, "rag_p1_v1")
        gateway.prepare_delete.assert_awaited_once()

    async def test_plan_ingest_exposes_project_owned_ingest_inputs(self) -> None:
        gateway = _Gateway()
        service = ProjectPlanningService(gateway=gateway)

        plan = await service.plan_ingest(
            IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                source_uri="memory://d1",
                content_type="text/plain",
            )
        )

        self.assertEqual(plan.project_id, "p1")
        self.assertEqual(plan.user_id, "u1")
        self.assertEqual(plan.kb_id, "kb")
        self.assertEqual(plan.doc_id, "d1")
        self.assertEqual(plan.source_uri, "memory://d1")
        self.assertEqual(plan.content_type, "text/plain")
        self.assertEqual(plan.collection_name, "rag_p1_v1")
        self.assertEqual(plan.retrieval_config, {"top_k": 3})
        self.assertEqual(plan.chunker_config, {"chunk_size": 128})
        gateway.prepare_ingest.assert_awaited_once()

    async def test_plan_search_resolves_placement_when_configured(self) -> None:
        gateway = _Gateway()
        service = ProjectPlanningService(
            gateway=gateway,
            placement_resolver=_placement_resolver(),
            routing_policy=RoutingPolicy(project_id="p1", routing_mode="project_single"),
        )

        plan = await service.plan_search(
            SearchRequest(project_id="p1", user_id="u1", query="hello")
        )

        self.assertEqual(plan.placement_plan["placement_version"], 1)
        self.assertFalse(plan.placement_plan["fanout"])
        self.assertEqual(plan.placement_plan["targets"][0]["shard_id"], "shard-1")
        self.assertEqual(
            plan.placement_plan["targets"][0]["routing_key"],
            "project:p1",
        )

    async def test_plan_ingest_uses_topic_placement_when_requested(self) -> None:
        gateway = _Gateway()
        gateway.ingest_plan = _IngestPlan(
            request=IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                source_uri="memory://d1",
                content_type="text/plain",
                topic_id="rentals",
            ),
        )
        gateway.prepare_ingest.return_value = gateway.ingest_plan
        service = ProjectPlanningService(
            gateway=gateway,
            placement_resolver=_placement_resolver(),
            routing_policy=RoutingPolicy(project_id="p1", routing_mode="topic_single"),
        )

        plan = await service.plan_ingest(gateway.ingest_plan.request)

        self.assertEqual(
            plan.placement_plan["targets"][0]["routing_key"],
            "project:p1:topic:rentals",
        )

    async def test_plan_search_uses_policy_from_placement_resolver(self) -> None:
        gateway = _Gateway()
        service = ProjectPlanningService(
            gateway=gateway,
            placement_resolver=_placement_resolver(
                policies=InMemoryRoutingPolicyRepository(
                    [RoutingPolicy(project_id="*", routing_mode="project_single")]
                )
            ),
        )

        plan = await service.plan_search(
            SearchRequest(project_id="p1", user_id="u1", query="hello")
        )

        self.assertEqual(plan.placement_plan["targets"][0]["routing_key"], "project:p1")


class _Gateway:
    def __init__(self) -> None:
        self.search_plan = _SearchPlan(
            request=SearchRequest(project_id="p1", user_id="u1", query="hello"),
        )
        self.delete_plan = _DeletePlan(
            request=DeleteDocumentRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
            ),
        )
        self.ingest_plan = _IngestPlan(
            request=IngestRequest(
                project_id="p1",
                user_id="u1",
                kb_id="kb",
                doc_id="d1",
                source_uri="memory://d1",
                content_type="text/plain",
            ),
        )
        self.prepare_search = AsyncMock(return_value=self.search_plan)
        self.prepare_delete = AsyncMock(return_value=self.delete_plan)
        self.prepare_ingest = AsyncMock(return_value=self.ingest_plan)


class _Config:
    project_id = "p1"
    collection_name = "rag_p1_v1"
    retrieval_config = {"top_k": 3}
    chunker_config = {"chunk_size": 128}


class _SearchPlan:
    def __init__(self, *, request: SearchRequest) -> None:
        self.request = request
        self.config = _Config()
        self.retrieval_filter = object()


class _DeletePlan:
    def __init__(self, *, request: DeleteDocumentRequest) -> None:
        self.request = request
        self.config = _Config()


class _IngestPlan:
    def __init__(self, *, request: IngestRequest) -> None:
        self.request = request
        self.config = _Config()


def _placement_resolver(policies=None) -> PlacementResolver:
    return PlacementResolver(
        shard_repository=InMemoryRetrievalShardRepository(
            [
                RetrievalShard(
                    shard_id="shard-1",
                    cluster_id="cluster",
                    qdrant_endpoint="http://qdrant:6333",
                )
            ]
        ),
        placement_repository=InMemoryPlacementRepository(),
        policy_repository=policies,
    )


if __name__ == "__main__":
    unittest.main()
