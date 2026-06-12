"""Public manager service package.

The manager service is the edge-facing coordinator. It owns route decisions and
delegates work to project, ingestion, retrieval, memory, and workflow services.
"""

from manager_service.clients import ProjectDocumentClient
from manager_service.errors import (
    ManagerIngestFailedError,
    ManagerIngestTimeoutError,
    ManagerServiceError,
)
from manager_service.routing import (
    DataType,
    ManagerRouter,
    Operation,
    RouteDecision,
    RouteRequest,
    ServiceTarget,
)
from manager_service.service import ManagerService

__all__ = [
    "DataType",
    "ManagerIngestFailedError",
    "ManagerIngestTimeoutError",
    "ManagerRouter",
    "ManagerService",
    "ManagerServiceError",
    "Operation",
    "ProjectDocumentClient",
    "RouteDecision",
    "RouteRequest",
    "ServiceTarget",
]
