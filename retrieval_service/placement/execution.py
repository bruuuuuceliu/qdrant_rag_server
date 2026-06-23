"""Runtime helpers for executing retrieval work against placement targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from retrieval_service.services.vector_store import QdrantStore


@dataclass(frozen=True, slots=True)
class PlacementExecutionTarget:
    routing_key: str
    shard_id: str
    collection_name: str
    role: str = "primary"
    placement_version: int = 0

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        placement_version: int,
    ) -> "PlacementExecutionTarget":
        shard_id = str(payload.get("shard_id", "")).strip()
        collection_name = str(payload.get("collection_name", "")).strip()
        if not shard_id:
            raise ValueError("placement target shard_id is required")
        if not collection_name:
            raise ValueError("placement target collection_name is required")
        return cls(
            routing_key=str(payload.get("routing_key", "")),
            shard_id=shard_id,
            collection_name=collection_name,
            role=str(payload.get("role", "primary") or "primary"),
            placement_version=placement_version,
        )


class PlacementStoreResolver:
    """Resolves placement target shard IDs to Qdrant store instances."""

    def __init__(
        self,
        *,
        default_store: Any,
        shard_repository: Any | None = None,
        store_factory: Callable[..., Any] = QdrantStore,
        default_vector_size: int | None = None,
    ) -> None:
        self._default_store = default_store
        self._shard_repository = shard_repository
        self._store_factory = store_factory
        self._default_vector_size = default_vector_size
        self._stores: dict[str, Any] = {}

    async def resolve(self, target: PlacementExecutionTarget | None) -> Any:
        if target is None or self._shard_repository is None:
            return self._default_store
        shard = await _get_shard(self._shard_repository, target.shard_id)
        if shard is None:
            return self._default_store
        endpoint = str(getattr(shard, "qdrant_endpoint", "") or "").strip()
        if not endpoint:
            return self._default_store
        cache_key = f"{target.shard_id}|{endpoint}"
        if cache_key not in self._stores:
            self._stores[cache_key] = self._make_store(endpoint)
        return self._stores[cache_key]

    async def close(self) -> None:
        for store in self._stores.values():
            close = getattr(store, "close", None)
            if close is not None:
                await close()
        self._stores.clear()

    def _make_store(self, endpoint: str) -> Any:
        kwargs: dict[str, Any] = {}
        if self._default_vector_size is not None:
            kwargs["default_vector_size"] = self._default_vector_size
        parsed = urlparse(endpoint)
        if parsed.scheme:
            return self._store_factory(url=endpoint, **kwargs)
        if ":" in endpoint:
            host, port = endpoint.rsplit(":", 1)
            return self._store_factory(host=host, port=int(port), **kwargs)
        return self._store_factory(host=endpoint, **kwargs)


def placement_read_targets(
    placement_plan: dict[str, Any] | None,
    *,
    fallback_collection_name: str,
) -> list[PlacementExecutionTarget]:
    targets = _targets_from_plan(placement_plan)
    if not targets:
        return [
            PlacementExecutionTarget(
                routing_key="",
                shard_id="",
                collection_name=fallback_collection_name,
            )
        ]
    return targets


def placement_write_target(
    placement_plan: dict[str, Any] | None,
    *,
    fallback_collection_name: str,
) -> PlacementExecutionTarget:
    targets = placement_write_targets(
        placement_plan,
        fallback_collection_name=fallback_collection_name,
    )
    return targets[0]


def placement_write_targets(
    placement_plan: dict[str, Any] | None,
    *,
    fallback_collection_name: str,
) -> list[PlacementExecutionTarget]:
    targets = _targets_from_plan(placement_plan)
    if not targets:
        return [
            PlacementExecutionTarget(
                routing_key="",
                shard_id="",
                collection_name=fallback_collection_name,
            )
        ]
    return sorted(targets, key=lambda target: target.role != "primary")


def placement_cache_scope(placement_plan: dict[str, Any] | None) -> str:
    targets = _targets_from_plan(placement_plan)
    if not targets:
        return ""
    parts = [f"v{targets[0].placement_version}"]
    parts.extend(f"{target.shard_id}:{target.routing_key}" for target in targets)
    return "|".join(parts)


def _targets_from_plan(
    placement_plan: dict[str, Any] | None,
) -> list[PlacementExecutionTarget]:
    if not placement_plan:
        return []
    raw_targets = placement_plan.get("targets", [])
    if not isinstance(raw_targets, list):
        raise ValueError("placement_plan targets must be a list")
    placement_version = int(placement_plan.get("placement_version", 0) or 0)
    return [
        PlacementExecutionTarget.from_mapping(
            dict(target),
            placement_version=placement_version,
        )
        for target in raw_targets
        if isinstance(target, dict)
    ]


async def _get_shard(shard_repository: Any, shard_id: str) -> Any | None:
    get = getattr(shard_repository, "get", None)
    if get is not None:
        return await _maybe_await(get(shard_id))
    get_shard = getattr(shard_repository, "get_shard", None)
    if get_shard is not None:
        return await _maybe_await(get_shard(shard_id))
    shards = getattr(shard_repository, "list", None)
    if shards is not None:
        for shard in await _maybe_await(shards()):
            if getattr(shard, "shard_id", "") == shard_id:
                return shard
    return None


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
