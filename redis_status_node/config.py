"""Redis task-status node settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedisStatusSettings:
    url: str = "redis://127.0.0.1:6379/0"
    key_prefix: str = "task:"
    completed_ttl_seconds: int = 86400

    @classmethod
    def from_values(cls, values: dict[str, str]) -> RedisStatusSettings:
        return cls(
            url=values.get("REDIS_TASK_STATUS_URL", "redis://127.0.0.1:6379/0"),
            key_prefix=values.get("REDIS_TASK_STATUS_KEY_PREFIX", "task:"),
            completed_ttl_seconds=int(values.get("REDIS_TASK_COMPLETED_TTL_SECONDS", "86400")),
        )

    def task_key(self, task_id: str) -> str:
        if not task_id.strip():
            raise ValueError("task_id is required")
        return f"{self.key_prefix}{task_id}"

