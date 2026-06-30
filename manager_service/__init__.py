"""Public manager service package.

The manager service is the edge-facing coordinator. It validates public
requests, publishes task intake, and reads task status.
"""

from manager_service.routing import (
    DataType,
    ManagerRouter,
    Operation,
    RouteDecision,
    RouteRequest,
    ServiceTarget,
)
from manager_service.service import ManagerRequestContext, ManagerService, ManagerTaskAccepted

__all__ = [
    "DataType",
    "ManagerRouter",
    "ManagerRequestContext",
    "ManagerService",
    "ManagerTaskAccepted",
    "Operation",
    "RouteDecision",
    "RouteRequest",
    "ServiceTarget",
]
