"""Shared transport-neutral contracts."""

from shared.contracts.data_types import (
    DATA_TYPE_REGISTRY,
    DataType,
    DataTypeSpec,
    data_type_spec,
    normalize_data_type,
)
from shared.contracts.jobs import IngestJobStatus, JobStatus
from shared.contracts.messages import (
    CURRENT_SCHEMA_VERSION,
    MessageConsumer,
    MessageEnvelope,
    MessageProducer,
    MessageType,
    MessageValidationError,
)
from shared.contracts.topics import TOPICS, TopicSet, domain_command_topic, domain_result_topic
from shared.contracts.task_status import TaskStatus, TaskStatusRecord, TaskStatusStore
from shared.contracts.task_messages import (
    DeadLetterPayload,
    DomainCommandPayload,
    DomainResultPayload,
    HelperCommandPayload,
    HelperResultPayload,
    ProjectPlanRequestPayload,
    ProjectPlanResultPayload,
    TaskEventPayload,
    TaskExecutionResultPayload,
    TaskRequestPayload,
    TaskResultPayload,
    TaskStartedPayload,
    TaskIntakePayload,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DATA_TYPE_REGISTRY",
    "DataType",
    "DataTypeSpec",
    "DeadLetterPayload",
    "DomainCommandPayload",
    "DomainResultPayload",
    "HelperCommandPayload",
    "HelperResultPayload",
    "IngestJobStatus",
    "JobStatus",
    "MessageConsumer",
    "MessageEnvelope",
    "MessageProducer",
    "MessageType",
    "MessageValidationError",
    "ProjectPlanRequestPayload",
    "ProjectPlanResultPayload",
    "TOPICS",
    "TaskEventPayload",
    "TaskExecutionResultPayload",
    "TaskRequestPayload",
    "TaskResultPayload",
    "TaskStartedPayload",
    "TaskStatus",
    "TaskStatusRecord",
    "TaskStatusStore",
    "TaskIntakePayload",
    "TopicSet",
    "data_type_spec",
    "domain_command_topic",
    "domain_result_topic",
    "normalize_data_type",
]
