"""Memory domain broker handler.

Consumes ``domain.memory.commands`` and dispatches the nine memory operations
(requirements §7): session start/close, message record, history compression,
cross-source lookup, source listing, document ingest, and profile read/update.

Every operation derives ``owner_user_id``/``agent_id`` from the caller's
verified service token (§8), runs mutation + idempotency writes in one
transaction (§9), and replies on ``domain.memory.results`` echoing the request
``correlation_id`` (AC-14).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from memory_service.compression import CompressionPolicy
from memory_service.facts import extract_facts
from memory_service.identity import IdentitySource
from memory_service.indexer import MemoryIndexer
from memory_service.models import (
    CompressionSpan,
    IdempotencyRecord,
    MemoryMessage,
    MemoryRecord,
    MemorySession,
    UserFact,
    UserProfile,
    iso_utc_now,
)
from memory_service.repository import (
    FactSupersessionConflict,
    IdempotencyConflictError,
    MemoryNotFoundError,
    MemoryRepository,
    MemoryTransaction,
)
from memory_service.searcher import (
    MemorySearcher,
    MemorySearchUnavailableError,
    MemorySearchUpstreamError,
)
from shared.contracts import (
    TOPICS,
    DomainCommandPayload,
    DomainResultPayload,
    MessageEnvelope,
    MessageProducer,
    MessageType,
)
from shared.ops.tracing import resume_span, setup_tracing, traceparent_from_envelope
from shared.service_auth import ServiceAuthError, ServiceAuthSettings, verify_service_token

logger = logging.getLogger(__name__)

_SOURCES = ("chat_history", "documents", "user_profile_facts")
_SOURCE_ORDER = {"chat_history": 0, "documents": 1, "user_profile_facts": 2}
_VALID_ROLES = ("user", "assistant")
_LOOKUP_MERGE_SCORE = 1.0
_FACT_SCORE = 1.0
# Documented per-message memory cap (§7.2.2 message.record content,
# §7.2.5 memory.lookup query): content/query longer than this are
# deterministically truncated to the exact prefix (never rejected), so a long
# user turn is always recorded and always searchable. Short identifier-like
# fields keep the harder 2048-char rejection in ``_require_str``.
_MEMORY_CONTENT_CAP = 2048


class MemoryAuthError(PermissionError):
    """Raised when caller service identity cannot be established."""

    def __init__(self, message: str, code: str = "unauthorized") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RequestScope:
    """Owner/agent scope derived from the caller's verified identity."""

    owner_user_id: str
    agent_id: str


class MemoryDomainHandler:
    """Handles memory domain commands for the agent-service caller."""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        compression: CompressionPolicy,
        indexer: MemoryIndexer,
        searcher: MemorySearcher,
        identity_source: IdentitySource,
        producer: MessageProducer | None = None,
        service_auth: ServiceAuthSettings | None = None,
        result_topic: str = TOPICS.domain_memory_results,
        memory_collection_name: str = "agent_memory",
        documents_collection_name: str = "agent_memory",
        include_merged: bool = False,
    ) -> None:
        self._repository = repository
        self._compression = compression
        self._indexer = indexer
        self._searcher = searcher
        self._identity_source = identity_source
        self._producer = producer
        self._service_auth = service_auth or ServiceAuthSettings()
        self._result_topic = result_topic
        self._memory_collection_name = memory_collection_name
        self._documents_collection_name = documents_collection_name
        self._include_merged = include_merged

    async def handle(self, envelope: MessageEnvelope) -> MessageEnvelope:
        operation = ""
        try:
            payload = DomainCommandPayload.from_envelope(envelope)
        except Exception as exc:  # noqa: BLE001 - a bad envelope still gets a reply
            payload = None
            operation = _operation_from_raw(envelope)
            result = _error_result("validation_error", str(exc), retryable=False)
            return await self._reply(envelope, operation, result)

        operation = payload.operation
        handler = _OPERATIONS.get(operation)
        if handler is None:
            result = _error_result(
                "validation_error", f"unsupported memory operation: {operation}", retryable=False
            )
            return await self._reply(envelope, operation, result)
        try:
            scope = self._build_scope(envelope)
            with resume_span(
                setup_tracing("memory_service"),
                traceparent_from_envelope(envelope),
                f"memory.{operation}",
                operation=operation,
                task_id=envelope.task_id,
                correlation_id=envelope.correlation_id,
                agent_id=scope.agent_id,
                owner_user_id=scope.owner_user_id,
            ):
                result = await handler(self, scope, payload)
        except MemoryAuthError as exc:
            result = _error_result(exc.code, str(exc), retryable=False)
        except MemoryNotFoundError as exc:
            result = _error_result("not_found", str(exc), retryable=False)
        except (IdempotencyConflictError, FactSupersessionConflict) as exc:
            result = _error_result("conflict", str(exc), retryable=False)
        except ValueError as exc:
            result = _error_result("validation_error", str(exc), retryable=False)
        except _UnavailableError as exc:
            result = _error_result("unavailable", str(exc), retryable=True)
        except MemorySearchUpstreamError as exc:
            result = _error_result("upstream_error", str(exc), retryable=True)
        except MemorySearchUnavailableError as exc:
            result = _error_result("unavailable", str(exc), retryable=True)
        except Exception as exc:  # noqa: BLE001 - one bad command must not stop the worker
            result = _error_result("internal_error", str(exc), retryable=True)
        return await self._reply(envelope, operation, result)

    async def _reply(
        self,
        envelope: MessageEnvelope,
        operation: str,
        result: dict[str, Any],
    ) -> MessageEnvelope:
        error_text = ""
        retryable = False
        if result.get("ok") is False and isinstance(result.get("error"), dict):
            error = result["error"]
            error_text = str(error.get("message", ""))
            retryable = bool(error.get("retryable", False))
        response = MessageEnvelope.create(
            producer="memory_service",
            message_type=MessageType.DOMAIN_RESULT,
            data_type=envelope.data_type,
            task_id=envelope.task_id,
            correlation_id=envelope.correlation_id,
            payload=DomainResultPayload(
                operation=operation,
                result=result,
                attempt=1,
                retryable=retryable,
                error=error_text,
                source_message_id=envelope.message_id,
            ).to_payload(),
        )
        response_topic = self._response_topic(envelope)
        if self._producer is not None:
            await self._producer.publish(response_topic, response, key=envelope.task_id)
        return response

    def _response_topic(self, envelope: MessageEnvelope) -> str:
        payload = envelope.payload
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        return str(context.get("response_topic") or self._result_topic)

    # --- scope and identity ------------------------------------------------

    def _build_scope(self, envelope: MessageEnvelope) -> RequestScope:
        headers = envelope.headers
        authorization = headers.get("Authorization", "")
        token = authorization[len("Bearer "):] if authorization.startswith("Bearer ") else ""
        if not token:
            raise MemoryAuthError("missing service token", "unauthorized")
        try:
            claims = verify_service_token(
                token,
                settings=self._service_auth,
            )
        except ServiceAuthError as exc:
            raise MemoryAuthError(str(exc), "unauthorized") from exc
        if claims.service not in self._service_auth.allowed_services:
            raise MemoryAuthError(
                f"service {claims.service!r} is not allowed", "forbidden"
            )
        actor_header = headers.get("X-Actor-User-ID", "")
        if actor_header and actor_header != claims.actor_user_id:
            raise MemoryAuthError("X-Actor-User-ID does not match token", "forbidden")
        # B3-2: requirements §8 bounds owner_user_id (the token's actor_user_id)
        # at 128 chars, enforced after token verification.
        owner_user_id = claims.actor_user_id
        if len(owner_user_id) > 128:
            raise MemoryAuthError(
                "actor_user_id exceeds 128 characters", "forbidden"
            )
        agent_id = headers.get("X-Agent-ID", "").strip()
        if not agent_id:
            raise MemoryAuthError("missing X-Agent-ID header", "forbidden")
        return RequestScope(owner_user_id=owner_user_id, agent_id=agent_id)

    # --- FR-1 sessions and messages ---------------------------------------

    async def session_start(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        request = payload.request
        session_id = _require_str(request, "session_id")
        agent_id = _require_str(request, "agent_id")
        _require_agent_match(scope, agent_id)
        key = str(request.get("idempotency_key") or f"session:{session_id}")
        existing = await self._repository.get_session(scope.owner_user_id, session_id)
        if existing is not None:
            return {"session": existing.to_mapping(), "created": False, "replayed": True}
        owner = await self._repository.session_owner(session_id)
        if owner is not None and owner != scope.owner_user_id:
            raise MemoryAuthError(
                "session belongs to a different user", "forbidden"
            )

        async def run(tx: MemoryTransaction) -> dict[str, Any]:
            now = iso_utc_now()
            session = MemorySession(
                session_id=session_id,
                owner_user_id=scope.owner_user_id,
                agent_id=agent_id,
                status="active",
                started_at=str(request.get("started_at") or now),
                metadata=dict(request.get("metadata", {}) or {}),
                created_at=now,
                updated_at=now,
            )
            created = tx.upsert_session(session)
            return {"session": session.to_mapping(), "created": created, "replayed": False}

        return await self._mutate(
            "session.start", request, key, run, owner_user_id=scope.owner_user_id
        )

    async def message_record(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        request = payload.request
        message_id = _require_str(request, "message_id")
        session_id = _require_str(request, "session_id")
        agent_id = _require_str(request, "agent_id")
        _require_agent_match(scope, agent_id)
        role = _require_str(request, "role")
        if role not in _VALID_ROLES:
            raise ValueError("message.record role must be 'user' or 'assistant'")
        sequence_number = _require_int(request, "sequence_number", minimum=1)
        # Content is deterministically truncated to _MEMORY_CONTENT_CAP rather
        # than rejected, so a >2048-char user turn is still recorded (bounded)
        # and the session's message history is intact (§7.2.2).
        content = _require_truncated_str(request, "content")
        key = str(request.get("idempotency_key") or f"message:{message_id}")
        existing = await self._repository.get_message(scope.owner_user_id, message_id)
        if existing is not None:
            return {"message": existing.to_mapping(), "recorded": False, "indexed": False}
        owner = await self._repository.session_owner(session_id)
        if owner is not None and owner != scope.owner_user_id:
            raise MemoryAuthError(
                "session belongs to a different user", "forbidden"
            )

        now = iso_utc_now()
        message = MemoryMessage(
            message_id=message_id,
            session_id=session_id,
            owner_user_id=scope.owner_user_id,
            agent_id=agent_id,
            role=role,
            sequence_number=sequence_number,
            content=content,
            created_at=str(request.get("created_at") or now),
            metadata=dict(request.get("metadata", {}) or {}),
        )
        record = MemoryRecord(
            memory_id=message_id,
            session_id=session_id,
            owner_user_id=scope.owner_user_id,
            agent_id=agent_id,
            kind="message",
            content=content,
            created_at=now,
        )

        async def run(tx: MemoryTransaction) -> dict[str, Any]:
            _ensure_session(tx, scope, session_id, agent_id, now)
            recorded = tx.insert_message(message)
            return {
                "message": message.to_mapping(),
                "recorded": recorded,
                "indexed": False,
            }

        result = await self._mutate(
            "message.record", request, key, run, owner_user_id=scope.owner_user_id
        )
        if result.get("recorded"):
            result["indexed"] = await self._try_index([record])
            # FR-4: deterministic first-person fact extraction from user turns.
            # Runs AFTER the message transaction commits, in its own per-fact
            # transactions, so a supersession conflict (unique partial index) or
            # any fact-write failure can never abort the message transaction or
            # lose the recorded message (best-effort, non-fatal). The get_message
            # guard + per-message idempotency above ensure extraction fires at
            # most once per message_id. The outer guard means even a wholly
            # unexpected failure here never turns an already-recorded message
            # into an error response.
            if role == "user":
                try:
                    extracted = await _persist_extracted_facts(
                        self._repository,
                        owner_user_id=scope.owner_user_id,
                        agent_id=agent_id,
                        message_id=message_id,
                        content=content,
                        now=now,
                    )
                except Exception:  # noqa: BLE001 - best-effort, never fatal
                    logger.warning(
                        "fact persistence failed for message %s",
                        message_id,
                        exc_info=True,
                    )
                else:
                    if extracted:
                        result["extracted_facts"] = extracted
        logger.info(
            "memory.message.record completed",
            extra={
                "operation": "message.record",
                "role": role,
                "recorded": bool(result.get("recorded")),
                "indexed": bool(result.get("indexed")),
                "agent_id": scope.agent_id,
                "owner_user_id": scope.owner_user_id,
            },
        )
        return result

    async def session_close(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        request = payload.request
        session_id = _require_str(request, "session_id")
        key = str(request.get("idempotency_key") or f"session.close:{session_id}")
        closed_at = str(request.get("closed_at") or iso_utc_now())
        session = await self._repository.get_session(scope.owner_user_id, session_id)
        if session is not None and session.status == "closed":
            return {
                "session": {
                    "session_id": session.session_id,
                    "status": session.status,
                    "closed_at": session.closed_at,
                },
                "changed": False,
            }

        async def run(tx: MemoryTransaction) -> dict[str, Any]:
            session, changed = tx.close_session(
                owner_user_id=scope.owner_user_id,
                session_id=session_id,
                closed_at=closed_at,
            )
            return {
                "session": {"session_id": session.session_id, "status": session.status, "closed_at": session.closed_at},
                "changed": changed,
            }

        return await self._mutate(
            "session.close", request, key, run, owner_user_id=scope.owner_user_id
        )

    # --- FR-2 compression --------------------------------------------------

    async def memory_compress(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        request = payload.request
        session_id = _require_str(request, "session_id")
        end_sequence = _require_int(request, "end_sequence", minimum=1)
        start_sequence = int(request.get("start_sequence") or 1)
        if start_sequence > end_sequence:
            raise ValueError("memory.compress start_sequence must be <= end_sequence")
        keep_recent = int(request.get("keep_recent") or 0)
        if keep_recent < 0:
            raise ValueError("memory.compress keep_recent must be >= 0")
        policy = str(request.get("policy") or "condense-v1")
        if policy != self._compression.policy_name:
            raise ValueError(
                f"unknown compression policy: {policy}; supported: {self._compression.policy_name}"
            )

        session = await self._repository.get_session(scope.owner_user_id, session_id)
        if session is None:
            raise MemoryNotFoundError(f"session not found: {session_id}")
        if session.agent_id != scope.agent_id:
            raise MemoryAuthError(
                "session belongs to a different agent", "forbidden"
            )
        messages = await self._repository.list_session_messages(
            scope.owner_user_id, session_id
        )
        span_messages = tuple(
            (message.sequence_number, message.role, message.content)
            for message in messages
            if start_sequence <= message.sequence_number <= end_sequence
        )
        if not span_messages:
            raise ValueError(
                f"memory.compress span [{start_sequence}, {end_sequence}] has no messages"
            )
        if keep_recent >= len(span_messages):
            raise ValueError(
                "memory.compress keep_recent must be less than the number of span messages"
            )
        output = await self._compression.compress(
            CompressionSpan(
                session_id=session_id,
                messages=span_messages,
                policy=policy,
                keep_recent=keep_recent,
            )
        )
        policy = output.policy
        memory_id = _compress_memory_id(
            session_id, output.covered_from, output.covered_to, policy
        )
        key = str(
            request.get("idempotency_key")
            or f"compress:{session_id}:{start_sequence}:{end_sequence}:{keep_recent}:{policy}"
        )
        existing = await self._repository.get_memory_record(scope.owner_user_id, memory_id)
        if existing is not None:
            return self._compress_result(existing, replayed=True)
        record = MemoryRecord(
            memory_id=memory_id,
            session_id=session_id,
            owner_user_id=scope.owner_user_id,
            agent_id=scope.agent_id,
            kind="compression_summary",
            content=output.condensed_context,
            covered_from=output.covered_from,
            covered_to=output.covered_to,
            created_at=iso_utc_now(),
        )

        async def run(tx: MemoryTransaction) -> dict[str, Any]:
            inserted = tx.insert_memory_record(record)
            return {"inserted": inserted}

        await self._mutate(
            "memory.compress", request, key, run, owner_user_id=scope.owner_user_id
        )
        await self._try_index([record])
        return self._compress_result(
            record, replayed=False, recent_messages=output.recent_messages
        )

    # --- FR-3 cross-source retrieval ---------------------------------------

    async def memory_lookup(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        request = payload.request
        # The lookup query is the current user message content in the B2 saga
        # (which may exceed the message cap). Truncate deterministically to the
        # prefix instead of rejecting, so a long user turn still produces a
        # working memory.lookup and the retrieved-context block can appear
        # (§7.2.5). Server-side truncation is the single source of truth,
        # protecting every client.
        query = _require_truncated_str(request, "query")
        top_k = int(request.get("top_k") or 5)
        if top_k < 1:
            raise ValueError("memory.lookup top_k must be >= 1")
        requested = _requested_sources(request)
        session_ids = _str_tuple(request.get("session_ids"))
        # B1-2: honor the request-level collection_name as an optional filter for
        # the documents source. When absent, the collection is resolved from the
        # document rows' stored ingest-time collection, so ingest-time and
        # lookup-time collections are consistent by default.
        documents_collection_name = str(request.get("collection_name") or "")
        started = time.monotonic()
        results: dict[str, list[dict[str, Any]]] = {}
        consulted: dict[str, bool] = {}
        for source in _ordered_sources(requested):
            try:
                matched = await self._lookup_source(
                    scope,
                    source,
                    query,
                    top_k,
                    session_ids,
                    documents_collection_name=documents_collection_name,
                )
            except MemorySearchUpstreamError as exc:
                # Lookup is best-effort and per-source (design §3.6 / B2): a
                # stale-dimension memory collection (e.g. a 384-dim
                # ``agent_memory`` collection queried with a 768-dim bge
                # embedding) degrades that source to empty instead of failing
                # the whole lookup with ``upstream_error``. The retrieval search
                # path returns empty for the same mismatch, so this catch is a
                # defense-in-depth guard at the lookup layer. Non-dimension
                # upstream failures (worker down, timeout) still propagate as
                # ``upstream_error``/``unavailable`` and the SA saga absorbs
                # them best-effort.
                if not _is_stale_dimension_error(exc):
                    raise
                logger.warning(
                    "memory.lookup: source %r degraded to empty results; "
                    "stale vector dimension mismatch: %s",
                    source,
                    exc,
                )
                matched = []
            results[source] = matched
            # FR-3.3: every requested source was searched.
            consulted[source] = True
        ordered = [s for s in _ordered_sources(requested) if results[s]]
        ordered += [s for s in _ordered_sources(requested) if not results[s]]
        response: dict[str, Any] = {
            "query": query,
            "sources": ordered,
            "consulted": consulted,
            "results": results,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        logger.info(
            "memory.lookup completed",
            extra={
                "operation": "memory.lookup",
                "source": "|".join(ordered),
                "hits": sum(len(values) for values in results.values()),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "agent_id": scope.agent_id,
                "owner_user_id": scope.owner_user_id,
            },
        )
        if self._include_merged:
            merged = sorted(
                (item for source in results.values() for item in source),
                key=lambda item: float(item.get("score", 0.0)),
                reverse=True,
            )
            response["merged"] = merged[:top_k]
        return response

    async def memory_sources(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        requested = _requested_sources(payload.request)
        entries: list[dict[str, Any]] = []
        for source in _ordered_sources(requested):
            if source == "chat_history":
                count = await self._repository.count_messages(
                    scope.owner_user_id, scope.agent_id
                )
                summaries = await self._repository.count_memory_records(
                    scope.owner_user_id, scope.agent_id, kind="compression_summary"
                )
                entries.append(
                    {"source": source, "available": True, "count": count + summaries}
                )
            elif source == "documents":
                count = await self._repository.count_memory_records(
                    scope.owner_user_id, scope.agent_id, kind="document"
                )
                entries.append(
                    {"source": source, "available": count > 0, "count": count}
                )
            else:
                count = await self._repository.count_active_facts(scope.owner_user_id)
                entries.append({"source": source, "available": True, "count": count})
        return {
            "scope": {"owner_user_id": scope.owner_user_id, "agent_id": scope.agent_id},
            "sources": entries,
        }

    # --- B1 owner-scoped documents source ----------------------------------

    async def memory_documents_ingest(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        """Ingest owner/agent-scoped documents into the distinct documents
        collection (FR-3.1 ``documents`` source). Each document is persisted as
        a ``kind='document'`` memory record; vector indexing is the same
        fire-and-forget ``memory_ingest`` hand-off targeting the documents
        collection (default ``MEMORY_DOCUMENTS_COLLECTION``)."""
        request = payload.request
        documents = request.get("documents")
        if not isinstance(documents, list) or not documents:
            raise ValueError(
                "memory.documents.ingest requires a non-empty 'documents' list"
            )
        agent_id = str(request.get("agent_id") or scope.agent_id)
        _require_agent_match(scope, agent_id)
        # B1-6 trust-based collection validation: a caller must never index
        # documents into the chat-memory collection. The guard applies only to a
        # non-empty request `collection_name`; the operator-configured documents
        # collection (the default when the request omits or empties the field) is
        # trusted (validated against config defaults, not a hardcoded list;
        # §7.2.9).
        requested_collection = request.get("collection_name")
        target = str(requested_collection or self._documents_collection_name)
        self._validate_documents_collection(target, explicit=bool(requested_collection))
        now = iso_utc_now()
        records: list[MemoryRecord] = []
        seen_doc_ids: set[str] = set()
        for item in documents:
            if not isinstance(item, dict):
                raise ValueError("each document entry must be an object")
            doc_id = _require_str(item, "doc_id")
            # B1-3: reject duplicate doc_ids within one request so the per-doc
            # recorded/status aggregation is unambiguous (a deduped second entry
            # would otherwise flip recorded_by_id to False while the row exists).
            if doc_id in seen_doc_ids:
                raise ValueError(f"duplicate doc_id within one request: {doc_id}")
            seen_doc_ids.add(doc_id)
            # B1-1: doc_id stays short (_require_str keeps the 2048 cap); text
            # is a long document body and only needs to be a non-empty string.
            text = _require_long_text(item, "text")
            records.append(
                MemoryRecord(
                    memory_id=doc_id,
                    owner_user_id=scope.owner_user_id,
                    agent_id=scope.agent_id,
                    kind="document",
                    content=text,
                    collection_name=target,
                    metadata=dict(item.get("metadata", {}) or {}),
                    created_at=now,
                )
            )

        async def run(tx: MemoryTransaction) -> dict[str, Any]:
            statuses: list[dict[str, Any]] = []
            for record in records:
                recorded = tx.insert_memory_record(record)
                statuses.append({"doc_id": record.memory_id, "recorded": recorded})
            return {"documents": statuses}

        result = await self._mutate(
            "memory.documents.ingest",
            request,
            f"documents:{_canonical_hash(request)}",
            run,
            owner_user_id=scope.owner_user_id,
        )
        recorded_by_id = {
            entry["doc_id"]: bool(entry["recorded"]) for entry in result["documents"]
        }
        to_index = [record for record in records if recorded_by_id[record.memory_id]]
        # Async projection: `indexed=True` means the index command was *queued*,
        # not that Qdrant holds the points. The durable store is the source of
        # truth; the only recovery path for a lost hand-off is the §9 re-drive
        # seam (a periodic job re-indexing memory_records lacking a Qdrant point).
        indexed = bool(
            await self._try_index(to_index, collection_name=target) if to_index else False
        )
        return {
            "documents": [
                {
                    "doc_id": doc_id,
                    "recorded": recorded_by_id[doc_id],
                    "indexed": indexed if recorded_by_id[doc_id] else False,
                }
                for doc_id in recorded_by_id
            ],
            "collection_name": target,
        }

    # --- FR-4 profile and facts --------------------------------------------

    async def profile_read(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        include_inactive = bool(payload.request.get("include_inactive_facts", False))
        user_id = scope.owner_user_id
        profile = await self._repository.get_profile(user_id)
        active = await self._repository.list_active_facts(user_id)
        response: dict[str, Any] = {
            "profile": _profile_mapping(user_id, profile, active),
        }
        if include_inactive:
            all_facts = await self._repository.list_facts(user_id, include_inactive=True)
            response["inactive_facts"] = [
                _fact_summary(fact)
                for fact in all_facts
                if fact.status == "inactive"
            ]
        return response

    async def profile_update(
        self, scope: RequestScope, payload: DomainCommandPayload
    ) -> dict[str, Any]:
        request = payload.request
        fact_type = _require_str(request, "fact_type")
        text = _require_str(request, "text")
        subject = str(request.get("subject") or "")
        source_message_id = str(request.get("source_message_id") or "")
        user_id = scope.owner_user_id
        now = iso_utc_now()

        requested_fact_id = str(request.get("fact_id") or "").strip()
        if requested_fact_id:
            existing = await self._repository.get_fact(user_id, requested_fact_id)
            if existing is not None:
                return {
                    "fact": existing.to_mapping(),
                    "superseded": [],
                    "profile": await self._profile_mapping(user_id),
                    "basic_info": {
                        "updated_fields": [],
                        "account_authoritative_conflicts": [],
                    },
                }
        fact_id = requested_fact_id or f"fact_{uuid4().hex}"

        profile = await self._repository.get_profile(user_id)
        basic_info = dict(profile.basic_info) if profile is not None else {}
        updated_fields, conflicts, new_basic_info = _reconcile_basic_info(
            request.get("basic_info_fields"), basic_info
        )
        new_fact = UserFact(
            fact_id=fact_id,
            user_id=user_id,
            fact_type=fact_type,
            subject=subject,
            text=text,
            status="active",
            version=0,
            updated_by=scope.agent_id,
            source_message_id=source_message_id,
            created_at=now,
            updated_at=now,
        )
        record = MemoryRecord(
            memory_id=fact_id,
            owner_user_id=user_id,
            agent_id=scope.agent_id,
            kind="fact",
            content=f"{fact_type}: {text}",
            created_at=now,
        )
        key = str(
            request.get("idempotency_key")
            or (f"fact:{requested_fact_id}" if requested_fact_id else _canonical_hash(request))
        )

        async def run(tx: MemoryTransaction) -> dict[str, Any]:
            superseded, inserted = tx.supersede_fact(
                user_id=user_id,
                fact_type=fact_type,
                subject=subject,
                new_fact=new_fact,
            )
            if updated_fields:
                tx.upsert_profile(
                    UserProfile(
                        user_id=user_id,
                        basic_info=new_basic_info,
                        identity_revision=(
                            profile.identity_revision if profile is not None else 0
                        ),
                        created_at=profile.created_at if profile is not None else now,
                        updated_at=now,
                    )
                )
            return {
                "fact": inserted.to_mapping(),
                "superseded": [
                    {
                        "fact_id": fact.fact_id,
                        "version": fact.version,
                        "superseded_by": inserted.fact_id,
                    }
                    for fact in superseded
                ],
                "basic_info": {
                    "updated_fields": updated_fields,
                    "account_authoritative_conflicts": conflicts,
                },
            }

        result = await self._mutate(
            "profile.update", request, key, run, owner_user_id=user_id
        )
        result["profile"] = await self._profile_mapping(user_id)
        await self._try_index([record])
        return result

    # --- shared helpers ----------------------------------------------------

    async def _lookup_source(
        self,
        scope: RequestScope,
        source: str,
        query: str,
        top_k: int,
        session_ids: tuple[str, ...],
        *,
        documents_collection_name: str = "",
    ) -> list[dict[str, Any]]:
        if source == "chat_history":
            return await self._lookup_chat_history(scope, query, top_k, session_ids)
        if source == "documents":
            return await self._lookup_documents(
                scope, query, top_k, documents_collection_name
            )
        return await self._lookup_facts(scope.owner_user_id, query, top_k)

    async def _lookup_documents(
        self,
        scope: RequestScope,
        query: str,
        top_k: int,
        collection_name: str = "",
    ) -> list[dict[str, Any]]:
        # B1-2: resolve the collection(s) from the rows actually indexed at
        # ingest-time, so ingest-time == lookup-time even for a non-default
        # collection. A request-level `collection_name` is an optional filter.
        collections = await self._repository.list_document_collections(
            scope.owner_user_id, scope.agent_id
        )
        if not collections:
            # No document row carries a collection: either there are no
            # documents, or they predate the collection column (legacy). Fall
            # back to the count-gate, then the configured documents collection.
            count = await self._repository.count_memory_records(
                scope.owner_user_id, scope.agent_id, kind="document"
            )
            if count == 0:
                return []
            collections = (self._documents_collection_name,)
        if collection_name:
            collections = tuple(c for c in collections if c == collection_name)
        if not collections:
            return []
        # Documents are NEVER session-filtered: the session filter only narrows
        # chat_history. A missing/empty documents collection would raise on
        # search, so the collection-resolution above short-circuits that case.
        hits: list[dict[str, Any]] = []
        for name in collections:
            hits.extend(
                await self._searcher.search(
                    scope,
                    query,
                    top_k,
                    collection_name=name,
                    session_ids=(),
                )
            )
        hits.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return [_hit_item("documents", hit) for hit in hits[:top_k]]

    async def _lookup_chat_history(
        self,
        scope: RequestScope,
        query: str,
        top_k: int,
        session_ids: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        hits = await self._searcher.search(
            scope,
            query,
            top_k,
            collection_name=self._memory_collection_name,
            session_ids=session_ids,
        )
        items = [_hit_item("chat_history", hit) for hit in hits]
        summaries: list[dict[str, Any]] = []
        for session_id in session_ids:
            records = await self._repository.list_session_summaries(
                scope.owner_user_id, session_id
            )
            for record in records:
                summaries.append(
                    {
                        "source": "chat_history",
                        "source_id": record.memory_id,
                        "text": record.content,
                        "score": _LOOKUP_MERGE_SCORE,
                        "session_id": session_id,
                        "memory_id": record.memory_id,
                    }
                )
        return items + summaries

    async def _lookup_facts(self, user_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
        facts = await self._repository.list_active_facts(user_id)
        tokens = {token for token in re.split(r"\W+", query.lower()) if token}
        matched = [fact for fact in facts if _fact_matches(fact, tokens)]
        return [
            {
                "source": "user_profile_facts",
                "source_id": fact.fact_id,
                "text": f"{fact.fact_type}: {fact.text}",
                "score": _FACT_SCORE,
            }
            for fact in matched[:top_k]
        ]

    def _validate_documents_collection(self, collection_name: str, *, explicit: bool) -> None:
        """Trust-based guard (B1-6): documents must never land in the chat-memory
        collection.

        Only an explicitly-supplied request ``collection_name`` is checked;
        the operator-configured documents collection (``explicit=False``) is
        trusted. Config defaults are compared, not a hardcoded list.
        """
        if explicit and collection_name == self._memory_collection_name:
            raise ValueError(
                f"collection_name {collection_name!r} is the chat-memory collection; "
                "documents cannot be indexed into it"
            )

    async def _mutate(
        self,
        operation: str,
        request: dict[str, Any],
        idempotency_key: str,
        run: Callable[[MemoryTransaction], Awaitable[dict[str, Any]]],
        *,
        owner_user_id: str,
    ) -> dict[str, Any]:
        request_hash = _canonical_hash(request)
        async with self._repository.transaction() as tx:
            existing = tx.get_idempotent(idempotency_key, owner_user_id=owner_user_id)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        f"idempotency key {idempotency_key!r} reused with a different request"
                    )
                return dict(existing.result)
            result = await run(tx)
            tx.store_idempotent(
                IdempotencyRecord(
                    idempotency_key=idempotency_key,
                    operation=operation,
                    request_hash=request_hash,
                    result=result,
                    owner_user_id=owner_user_id,
                    created_at=iso_utc_now(),
                )
            )
            return result

    async def _try_index(self, records: list[MemoryRecord], *, collection_name: str = "") -> bool:
        if not records:
            return True
        try:
            await self._indexer.index(records, collection_name=collection_name)
        except Exception:  # noqa: BLE001 - indexing is a best-effort projection
            return False
        # Persist the queued status so the §9 re-drive seam does not re-publish a
        # successfully queued hand-off. Best-effort: if the UPDATE fails the
        # record stays indexed=0 and the seam re-queues it on the next startup.
        try:
            await self._repository.mark_memory_records_indexed(
                [record.memory_id for record in records]
            )
        except Exception:  # noqa: BLE001
            pass
        return True

    def _compress_result(
        self,
        record: MemoryRecord,
        *,
        replayed: bool,
        recent_messages: list[MemoryMessage] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "condensed_context": record.content,
            "memory_id": record.memory_id,
            "covered_range": {"from": record.covered_from, "to": record.covered_to},
            "policy": "condense-v1",
            "replayed": replayed,
        }
        if recent_messages:
            result["recent_messages"] = [
                message.to_mapping() for message in recent_messages
            ]
        return result

    async def _profile_mapping(
        self, user_id: str, profile: UserProfile | None = None, active: list[UserFact] | None = None
    ) -> dict[str, Any]:
        profile = profile or await self._repository.get_profile(user_id)
        active = active if active is not None else await self._repository.list_active_facts(user_id)
        return _profile_mapping(user_id, profile, active)


# --- operation dispatch ----------------------------------------------------

_OPERATIONS = {
    "session.start": MemoryDomainHandler.session_start,
    "message.record": MemoryDomainHandler.message_record,
    "session.close": MemoryDomainHandler.session_close,
    "memory.compress": MemoryDomainHandler.memory_compress,
    "memory.lookup": MemoryDomainHandler.memory_lookup,
    "memory.sources": MemoryDomainHandler.memory_sources,
    "memory.documents.ingest": MemoryDomainHandler.memory_documents_ingest,
    "profile.read": MemoryDomainHandler.profile_read,
    "profile.update": MemoryDomainHandler.profile_update,
}


def _operation_from_raw(envelope: MessageEnvelope) -> str:
    payload = envelope.payload
    if not isinstance(payload, dict):
        return ""
    operation = payload.get("operation")
    return str(operation) if operation is not None else ""


def _is_stale_dimension_error(exc: Exception) -> bool:
    """True when the error indicates a collection vector-dimension mismatch.

    Qdrant reports ``Wrong input: Query vector dimension error: expected dim:
    384, got 768`` and the retrieval vector-store validation path raises
    ``... has vector dimension 384; expected 768 ...``. Both carry the
    ``dimension`` marker plus an expected/got signal, so a message check is the
    shared signal across the broker searcher (which only sees the retrieval
    helper's error string).
    """
    message = str(exc).lower()
    return "dimension" in message and (
        "expected" in message or "got" in message or "mismatch" in message
    )


class _UnavailableError(RuntimeError):
    """Mapped to the unavailable (503, retryable) error code."""


class _UpstreamError(RuntimeError):
    """Mapped to the upstream_error (502, retryable) error code."""


def _ensure_session(
    tx: MemoryTransaction,
    scope: RequestScope,
    session_id: str,
    agent_id: str,
    now: str,
) -> None:
    """Auto-create the session classifier on out-of-order message delivery."""
    tx.upsert_session(
        MemorySession(
            session_id=session_id,
            owner_user_id=scope.owner_user_id,
            agent_id=agent_id,
            status="active",
            started_at=now,
            metadata={},
            created_at=now,
            updated_at=now,
        )
    )


async def _persist_extracted_facts(
    repository: MemoryRepository,
    *,
    owner_user_id: str,
    agent_id: str,
    message_id: str,
    content: str,
    now: str,
) -> list[dict[str, Any]]:
    """Best-effort persistence of first-person facts from a user message.

    Runs AFTER ``message.record``'s transaction has committed, in a fresh
    transaction per fact. This isolates fact writes from the message write: a
    supersession conflict (Postgres unique partial index, FR-4.5) or any
    fact-write failure can never abort the already-committed message
    transaction, so ``message.record`` never loses the message and never fails
    because of extraction. Each fact is best-effort independently — one failed
    fact does not drop the others.

    Facts are intentionally kept self-contained in Postgres (retrieved via
    ``list_active_facts``, not vector search): unlike ``profile_update`` no
    ``MemoryRecord`` is created and no Qdrant index hand-off happens, so the
    §9 reconciliation re-drive does not try to vector-index fact rows.
    """
    try:
        matches = extract_facts(content)
    except Exception:  # noqa: BLE001 - extraction must never fail message.record
        logger.warning(
            "fact extraction failed for message %s", message_id, exc_info=True
        )
        return []
    created: list[dict[str, Any]] = []
    for match in matches:
        fact_type = str(match.get("fact_type") or "").strip()
        subject = str(match.get("subject") or "").strip()
        text = str(match.get("text") or "").strip()
        if not fact_type or not text:
            continue
        fact = UserFact(
            fact_id=f"fact_{uuid4().hex}",
            user_id=owner_user_id,
            fact_type=fact_type,
            subject=subject,
            text=text,
            status="active",
            version=0,
            updated_by=agent_id,
            source_message_id=message_id,
            created_at=now,
            updated_at=now,
        )
        try:
            # Own transaction per fact: an aborted transaction on a conflict
            # stays scoped to this fact and cannot affect the message or the
            # other facts.
            async with repository.transaction() as tx:
                # FR-4.5: supersede prior active facts of the same (fact_type,
                # subject) so the durable store keeps exactly one active version.
                _, inserted = tx.supersede_fact(
                    user_id=owner_user_id,
                    fact_type=fact_type,
                    subject=subject,
                    new_fact=fact,
                )
        except Exception:  # noqa: BLE001 - best-effort persistence
            logger.warning(
                "fact supersede failed for (%s, %s) from message %s",
                fact_type,
                subject,
                message_id,
                exc_info=True,
            )
            continue
        created.append(inserted.to_mapping())
    return created


def _require_agent_match(scope: RequestScope, agent_id: str) -> None:
    if agent_id != scope.agent_id:
        raise MemoryAuthError("agent_id does not match X-Agent-ID", "forbidden")


def _require_str(request: dict[str, Any], name: str) -> str:
    value = str(request.get(name) or "").strip()
    if not value:
        raise ValueError(f"missing required field: {name}")
    if len(value) > 2048:
        raise ValueError(f"field {name} exceeds 2048 characters")
    return value


def _require_truncated_str(
    request: dict[str, Any], name: str, *, cap: int = _MEMORY_CONTENT_CAP
) -> str:
    """Require a non-empty string; deterministically truncate to ``cap`` chars.

    Used for ``message.record`` content and ``memory.lookup`` query, both of
    which legitimately exceed the 2048-char cap that ``_require_str`` applies to
    short identifier-like fields. Truncation keeps the exact string prefix and
    is the documented contract (§7.2.2 / §7.2.5): a long user turn is recorded
    (history intact, bounded) and a long lookup query searches rather than being
    rejected with ``validation_error``. Truncating server-side makes this the
    single source of truth for every client.
    """
    value = str(request.get(name) or "").strip()
    if not value:
        raise ValueError(f"missing required field: {name}")
    if len(value) > cap:
        value = value[:cap]
    return value


def _require_long_text(request: dict[str, Any], name: str) -> str:
    """Require a non-empty string but do NOT cap its length (B1-1).

    Used for document bodies, which legitimately exceed the 2048-char limit
    applied to short identifier-like fields by ``_require_str``.
    """
    value = str(request.get(name) or "").strip()
    if not value:
        raise ValueError(f"missing required field: {name}")
    return value


def _require_int(request: dict[str, Any], name: str, *, minimum: int) -> int:
    try:
        value = int(request.get(name))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"field {name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"field {name} must be >= {minimum}")
    return value


def _requested_sources(request: dict[str, Any]) -> tuple[str, ...]:
    raw = request.get("sources")
    if raw is None or raw == []:
        return _SOURCES
    requested = _str_tuple(raw)
    invalid = [source for source in requested if source not in _SOURCES]
    if invalid:
        raise ValueError(
            f"unknown memory.lookup source(s): {', '.join(invalid)}; "
            f"valid sources are {', '.join(_SOURCES)}"
        )
    return requested


def _ordered_sources(requested: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(requested, key=_SOURCE_ORDER.get))


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),) if str(value) else ()


def _canonical_hash(request: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _compress_memory_id(session_id: str, start: int, end: int, policy: str) -> str:
    canonical = f"{session_id}|{start}|{end}|{policy}"
    return "mem_sum_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _reconcile_basic_info(
    proposed: Any, current: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Apply basic-info fields only when account data is not authoritative.

    Returns ``(updated_fields, conflicts, merged_basic_info)``. A proposed field
    already present in the account-backed basic info is treated as a conflict
    (account data wins, FR-4.6); a genuinely new field is applied.
    """
    if not isinstance(proposed, dict):
        return [], [], dict(current)
    updated: list[str] = []
    conflicts: list[str] = []
    merged = dict(current)
    for field_name, value in proposed.items():
        field_value = str(value or "").strip()
        if not field_value:
            continue
        if field_name in current and current[field_name] != field_value:
            conflicts.append(field_name)
            continue
        if merged.get(field_name) != field_value:
            merged[field_name] = field_value
            updated.append(field_name)
    return updated, conflicts, merged


def _fact_matches(fact: UserFact, tokens: set[str]) -> bool:
    if not tokens:
        return True
    haystack = f"{fact.fact_type} {fact.subject} {fact.text}".lower()
    return any(token in haystack for token in tokens)


def _hit_item(source: str, hit: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source": source,
        "source_id": str(hit.get("source_id", "")),
        "text": str(hit.get("text", "")),
        "score": float(hit.get("score", 0.0)),
    }
    for field_name in ("session_id", "sequence_number", "memory_id"):
        if hit.get(field_name) is not None:
            item[field_name] = hit[field_name]
    return item


def _profile_mapping(
    user_id: str,
    profile: UserProfile | None,
    active: list[UserFact] | None,
) -> dict[str, Any]:
    basic_info = dict(profile.basic_info) if profile is not None else {}
    facts = [_fact_summary(fact) for fact in (active or [])]
    return {
        "user_id": user_id,
        "basic_info": basic_info,
        "active_facts": facts,
        "updated_at": profile.updated_at if profile is not None else "",
    }


def _fact_summary(fact: UserFact) -> dict[str, Any]:
    return {
        "fact_id": fact.fact_id,
        "fact_type": fact.fact_type,
        "subject": fact.subject,
        "text": fact.text,
        "version": fact.version,
        "updated_at": fact.updated_at,
        "source_message_id": fact.source_message_id,
    }


def _error_result(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "retryable": retryable},
    }
