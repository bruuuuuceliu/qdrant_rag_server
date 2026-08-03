"""Standalone HS256 service-token helpers for memory_service callers.

This module is a small, dependency-free mirror of the Simple Agent shared
service-auth library (``simple_agent_service_auth.tokens``). It exists so the
RAG repo's ``memory_service`` can verify caller service tokens without importing
a Simple Agent service package; after the repos fully merge these two modules
collapse into one. The algorithm, header, claims, and default local signing key
are identical to the Simple Agent implementation so fake/local mode and the real
broker path interoperate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

# Defaults mirror ``simple_agent_service_auth`` local-dev defaults so tokens
# minted by conversation-server's fake/local path verify here unchanged.
DEFAULT_SIGNING_KEY = "local-dev-signing-key"
DEFAULT_ISSUER = "simple-agent-local"
DEFAULT_AUDIENCE = "simple-agent-internal"
DEFAULT_TTL_SECONDS = 300

_HEADER = {"alg": "HS256", "typ": "SA-SERVICE"}


class ServiceAuthError(PermissionError):
    """Raised when a service token cannot be verified."""


@dataclass(frozen=True)
class ServiceTokenClaims:
    """Verified claims carried by a service token."""

    issuer: str
    audience: str
    service: str
    actor_user_id: str
    actor_role: str
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class ServiceAuthSettings:
    """Signing/verification policy for service tokens."""

    signing_key: str = DEFAULT_SIGNING_KEY
    issuer: str = DEFAULT_ISSUER
    audience: str = DEFAULT_AUDIENCE
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    allowed_services: tuple[str, ...] = ("conversation-server",)


def create_service_token(
    *,
    settings: ServiceAuthSettings,
    service: str,
    actor_user_id: str,
    actor_role: str,
    now: int | None = None,
) -> str:
    """Mint an HS256 service token with actor claims (same shape as the
    Simple Agent ``create_service_token``)."""

    issued_at = int(time.time() if now is None else now)
    payload = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "svc": service,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "iat": issued_at,
        "exp": issued_at + settings.ttl_seconds,
    }
    signing_input = f"{_b64encode(_json_bytes(_HEADER))}.{_b64encode(_json_bytes(payload))}"
    return f"{signing_input}.{_sign(signing_input, settings.signing_key)}"


def verify_service_token(
    token: str,
    *,
    settings: ServiceAuthSettings,
    expected_service: str | None = None,
    now: int | None = None,
) -> ServiceTokenClaims:
    """Verify an HS256 service token and return its verified claims."""

    parts = token.split(".")
    if len(parts) != 3:
        raise ServiceAuthError("malformed service token")

    signing_input = f"{parts[0]}.{parts[1]}"
    expected_signature = _sign(signing_input, settings.signing_key)
    if not hmac.compare_digest(parts[2], expected_signature):
        raise ServiceAuthError("invalid service token signature")

    try:
        header = json.loads(_b64decode(parts[0]))
        payload = json.loads(_b64decode(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ServiceAuthError("invalid service token encoding") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "SA-SERVICE":
        raise ServiceAuthError("unsupported service token header")
    if payload.get("iss") != settings.issuer:
        raise ServiceAuthError("invalid service token issuer")
    if payload.get("aud") != settings.audience:
        raise ServiceAuthError("invalid service token audience")

    service = payload.get("svc")
    if not isinstance(service, str) or not service:
        raise ServiceAuthError("missing service identity")
    if expected_service is not None and service != expected_service:
        raise ServiceAuthError("unexpected service identity")

    current_time = int(time.time() if now is None else now)
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise ServiceAuthError("invalid service token timestamps")
    if expires_at - issued_at > settings.ttl_seconds:
        raise ServiceAuthError("service token lifetime exceeds policy")
    if expires_at <= current_time:
        raise ServiceAuthError("expired service token")
    if issued_at > current_time + 60:
        raise ServiceAuthError("service token issued in the future")

    actor_user_id = payload.get("actor_user_id")
    actor_role = payload.get("actor_role")
    if not isinstance(actor_user_id, str) or not actor_user_id:
        raise ServiceAuthError("missing actor user claim")
    if actor_role not in {"free", "tier_1", "admin"}:
        raise ServiceAuthError("invalid actor role claim")

    return ServiceTokenClaims(
        issuer=payload["iss"],
        audience=payload["aud"],
        service=service,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(signing_input: str, signing_key: str) -> str:
    digest = hmac.new(
        signing_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    )
    return _b64encode(digest.digest())
