"""Canonical Redpanda topic names for the target runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopicSet:
    manager_request_accepted: str = "manager.request.accepted"
    manager_request_rejected: str = "manager.request.rejected"
    task_requests: str = "task.requests"
    task_events: str = "task.events"
    task_intake: str = "task.intake"
    project_plan_requests: str = "project.plan.requests"
    project_plan_results: str = "project.plan.results"
    domain_workflow_log_commands: str = "domain.workflow_log.commands"
    domain_workflow_log_results: str = "domain.workflow_log.results"
    domain_memory_commands: str = "domain.memory.commands"
    domain_memory_results: str = "domain.memory.results"
    domain_other_commands: str = "domain.other.commands"
    domain_other_results: str = "domain.other.results"
    helper_ingestion_commands: str = "helper.ingestion.commands"
    helper_ingestion_results: str = "helper.ingestion.results"
    helper_retrieval_commands: str = "helper.retrieval.commands"
    helper_retrieval_results: str = "helper.retrieval.results"
    helper_retrieval_index_commands: str = "helper.retrieval_index.commands"
    helper_retrieval_index_results: str = "helper.retrieval_index.results"
    helper_storage_commands: str = "helper.storage.commands"
    helper_storage_results: str = "helper.storage.results"
    task_started: str = "task.started"
    task_step_events: str = "task.step.events"
    task_results: str = "task.results"
    task_dead_letters: str = "task.dead_letters"
    audit_events: str = "audit.events"
    metrics_events: str = "metrics.events"
    health_events: str = "health.events"

    def all(self) -> tuple[str, ...]:
        return tuple(getattr(self, field) for field in self.__dataclass_fields__)


TOPICS = TopicSet()


def domain_command_topic(data_type: str) -> str:
    normalized = data_type.strip().lower()
    if normalized == "project_document":
        return TOPICS.project_plan_requests
    if normalized == "workflow_log":
        return TOPICS.domain_workflow_log_commands
    if normalized == "agent_memory":
        return TOPICS.domain_memory_commands
    return TOPICS.domain_other_commands


def domain_result_topic(data_type: str) -> str:
    normalized = data_type.strip().lower()
    if normalized == "project_document":
        return TOPICS.project_plan_results
    if normalized == "workflow_log":
        return TOPICS.domain_workflow_log_results
    if normalized == "agent_memory":
        return TOPICS.domain_memory_results
    return TOPICS.domain_other_results
