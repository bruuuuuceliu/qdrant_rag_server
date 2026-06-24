"""Small runtime health payloads for service entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    service: str
    ready: bool
    dependencies: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "ready": self.ready,
            "dependencies": dict(self.dependencies),
            "details": dict(self.details),
        }
