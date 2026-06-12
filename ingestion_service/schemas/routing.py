"""Routing schemas for file handler selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HandlerCandidate:
    name: str
    supported_content_types: tuple[str, ...] = ()
    supported_extensions: tuple[str, ...] = ()
    resource_tier: str = "minimal"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    handler_name: str
    status: str = "selected"
    reason: str = ""
    content_type: str = ""
    extension: str = ""
    resource_tier: str = "minimal"
    metadata: dict[str, Any] = field(default_factory=dict)
