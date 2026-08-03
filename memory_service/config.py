"""Memory service settings.

Env-driven configuration mirroring ``WorkflowLogDomainSettings`` plus the
service-auth and hand-off mode switches used by the domain app composition root
(design doc §3.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from configs.base import get_bool_value, get_int_value, get_value
from shared.contracts import TOPICS
from shared.service_auth import ServiceAuthSettings


@dataclass(frozen=True, slots=True)
class MemoryServiceSettings:
    """Settings for the memory domain service process."""

    service_name: str = "memory_service"
    command_topic: str = TOPICS.domain_memory_commands
    result_topic: str = TOPICS.domain_memory_results
    identity_topic: str = TOPICS.identity_user_events
    retrieval_index_commands_topic: str = TOPICS.helper_retrieval_index_commands
    retrieval_commands_topic: str = TOPICS.helper_retrieval_commands
    retrieval_results_topic: str = TOPICS.helper_retrieval_results
    db_path: Path = Path("/var/lib/rag/agent_memory.db")
    identity_mode: str = "broker"  # broker | fake
    index_mode: str = "broker"     # broker | fake
    search_mode: str = "broker"    # broker | fake
    allowed_services: tuple[str, ...] = ("conversation-server",)
    service_auth: ServiceAuthSettings = ServiceAuthSettings()
    documents_collection_name: str = "agent_documents"
    memory_collection_name: str = "agent_memory"
    include_merged: bool = False

    @classmethod
    def from_values(cls, values: dict[str, str]) -> "MemoryServiceSettings":
        # B3 — RAG-side signing-key single contract: broker mode requires the
        # caller to set SERVICE_AUTH_SIGNING_KEY explicitly (it must equal
        # simple_agent's auth signing key). Fake mode and direct construction
        # bypass this guard.
        identity_mode = get_value(values, "MEMORY_IDENTITY_MODE", "broker")
        index_mode = get_value(values, "MEMORY_INDEX_MODE", "broker")
        search_mode = get_value(values, "MEMORY_SEARCH_MODE", "broker")
        # B3-1: an empty-but-present SERVICE_AUTH_SIGNING_KEY must fail the guard
        # just like a missing key (an empty key yields signing_key='' and every
        # verification 401s). Strip whitespace so ' ' is also rejected.
        signing_key_value = values.get("SERVICE_AUTH_SIGNING_KEY")
        if (
            any(mode == "broker" for mode in (identity_mode, index_mode, search_mode))
            and not (
                isinstance(signing_key_value, str) and signing_key_value.strip()
            )
        ):
            raise ValueError(
                "SERVICE_AUTH_SIGNING_KEY must be set to a non-empty value when any "
                "MEMORY_*_MODE=broker; it must equal simple_agent's auth signing key "
                "(single contract)."
            )
        auth = ServiceAuthSettings(
            signing_key=get_value(
                values,
                "SERVICE_AUTH_SIGNING_KEY",
                ServiceAuthSettings().signing_key,
            ),
            issuer=get_value(
                values,
                "SERVICE_AUTH_TOKEN_ISSUER",
                ServiceAuthSettings().issuer,
            ),
            audience=get_value(
                values,
                "SERVICE_AUTH_TOKEN_AUDIENCE",
                ServiceAuthSettings().audience,
            ),
            ttl_seconds=get_int_value(
                values,
                "SERVICE_AUTH_TOKEN_TTL_SECONDS",
                ServiceAuthSettings().ttl_seconds,
            ),
            allowed_services=_str_tuple(
                get_value(values, "MEMORY_ALLOWED_SERVICES", "conversation-server")
            ),
        )
        return cls(
            service_name=get_value(values, "MEMORY_SERVICE_NAME", "memory_service"),
            command_topic=get_value(
                values,
                "MEMORY_DOMAIN_COMMAND_TOPIC",
                TOPICS.domain_memory_commands,
            ),
            result_topic=get_value(
                values,
                "MEMORY_DOMAIN_RESULT_TOPIC",
                TOPICS.domain_memory_results,
            ),
            identity_topic=get_value(
                values,
                "MEMORY_IDENTITY_TOPIC",
                TOPICS.identity_user_events,
            ),
            retrieval_index_commands_topic=get_value(
                values,
                "MEMORY_RETRIEVAL_INDEX_COMMANDS_TOPIC",
                TOPICS.helper_retrieval_index_commands,
            ),
            retrieval_commands_topic=get_value(
                values,
                "MEMORY_RETRIEVAL_COMMANDS_TOPIC",
                TOPICS.helper_retrieval_commands,
            ),
            retrieval_results_topic=get_value(
                values,
                "MEMORY_RETRIEVAL_RESULTS_TOPIC",
                TOPICS.helper_retrieval_results,
            ),
            db_path=Path(
                get_value(values, "MEMORY_DB_PATH", "/var/lib/rag/agent_memory.db")
            ),
            identity_mode=identity_mode,
            index_mode=index_mode,
            search_mode=search_mode,
            documents_collection_name=get_value(
                values,
                "MEMORY_DOCUMENTS_COLLECTION",
                "agent_documents",
            ),
            memory_collection_name=get_value(
                values,
                "MEMORY_COLLECTION",
                "agent_memory",
            ),
            include_merged=get_bool_value(values, "MEMORY_LOOKUP_INCLUDE_MERGED", False),
            service_auth=auth,
        )


def _str_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
