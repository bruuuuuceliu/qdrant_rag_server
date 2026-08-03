"""Identity sources that initialize and refresh user profiles.

``IdentitySource`` is the port memory_service depends on for profile
enrichment (FR-4.2). ``FakeIdentitySource`` seeds deterministic users for local
dev/tests; ``BrokerIdentitySource`` applies ``identity.user.events`` consumed
from the broker. Both apply events through the same repository-backed logic so
the fake exercises the production code path.
"""

from __future__ import annotations

from typing import Any, Protocol

from memory_service.models import UserProfile, iso_utc_now
from memory_service.repository import MemoryRepository

IDENTITY_USER_REGISTERED = "identity.user.registered"
IDENTITY_USER_STATUS_CHANGED = "identity.user.status_changed"

_BASIC_INFO_FIELDS = ("email", "display_name", "role", "account_status")


class IdentitySource(Protocol):
    """Port for applying identity events to the profile store."""

    async def on_user_registered(self, event: dict[str, Any]) -> UserProfile:
        ...

    async def on_user_status_changed(self, event: dict[str, Any]) -> UserProfile | None:
        ...


class FakeIdentitySource:
    """Deterministic identity source seeding fixed local users."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def seed(self) -> None:
        for user_id, email, display_name, role in (
            ("user_1", "user1@example.com", "User One", "tier_1"),
            ("user_2", "user2@example.com", "User Two", "tier_1"),
        ):
            await self.on_user_registered(
                {
                    "event_type": IDENTITY_USER_REGISTERED,
                    "user_id": user_id,
                    "email": email,
                    "display_name": display_name,
                    "role": role,
                    "account_status": "active",
                }
            )

    async def on_user_registered(self, event: dict[str, Any]) -> UserProfile:
        return await _apply_registered_event(self._repository, event)

    async def on_user_status_changed(self, event: dict[str, Any]) -> UserProfile | None:
        return await _apply_status_changed_event(self._repository, event)


class BrokerIdentitySource:
    """Applies ``identity.user.events`` payloads consumed from the broker."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def handle_event(self, event: dict[str, Any]) -> UserProfile | None:
        event_type = str(event.get("event_type", ""))
        if event_type == IDENTITY_USER_REGISTERED:
            return await self.on_user_registered(event)
        if event_type == IDENTITY_USER_STATUS_CHANGED:
            return await self.on_user_status_changed(event)
        return None

    async def on_user_registered(self, event: dict[str, Any]) -> UserProfile:
        return await _apply_registered_event(self._repository, event)

    async def on_user_status_changed(self, event: dict[str, Any]) -> UserProfile | None:
        return await _apply_status_changed_event(self._repository, event)


async def _apply_registered_event(
    repository: MemoryRepository,
    event: dict[str, Any],
) -> UserProfile:
    user_id = str(event.get("user_id", "")).strip()
    if not user_id:
        raise ValueError("identity.user.registered event requires user_id")
    now = iso_utc_now()
    existing = await repository.get_profile(user_id)
    event_revision = _event_revision(event)
    if (
        existing is not None
        and event_revision is not None
        and existing.identity_revision >= event_revision
    ):
        # Replayed or out-of-order event: keep the profile at its current revision.
        return existing
    revision = (
        event_revision
        if event_revision is not None
        else (existing.identity_revision if existing is not None else 0) + 1
    )
    basic_info = dict(existing.basic_info) if existing is not None else {}
    for field_name in _BASIC_INFO_FIELDS:
        value = event.get(field_name)
        if value is not None and str(value).strip():
            basic_info[field_name] = str(value)
    profile = UserProfile(
        user_id=user_id,
        basic_info=basic_info,
        identity_revision=revision,
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
    )
    await _upsert_profile(repository, profile)
    return profile


async def _apply_status_changed_event(
    repository: MemoryRepository,
    event: dict[str, Any],
) -> UserProfile | None:
    user_id = str(event.get("user_id", "")).strip()
    if not user_id:
        raise ValueError("identity.user.status_changed event requires user_id")
    existing = await repository.get_profile(user_id)
    if existing is None:
        # A status event arriving before registration: reconcile lazily on the
        # next registered event. Do not fabricate a profile from a partial event.
        return None
    event_revision = _event_revision(event)
    if (
        event_revision is not None
        and existing.identity_revision >= event_revision
    ):
        return existing
    basic_info = dict(existing.basic_info)
    changed = False
    for field_name in ("role", "account_status"):
        value = event.get(field_name)
        if value is not None and str(value).strip():
            basic_info[field_name] = str(value)
            changed = True
    if not changed:
        return existing
    now = iso_utc_now()
    profile = UserProfile(
        user_id=user_id,
        basic_info=basic_info,
        identity_revision=(
            event_revision
            if event_revision is not None
            else existing.identity_revision + 1
        ),
        created_at=existing.created_at,
        updated_at=now,
    )
    await _upsert_profile(repository, profile)
    return profile


def _event_revision(event: dict[str, Any]) -> int | None:
    value = event.get("identity_revision")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _upsert_profile(repository: MemoryRepository, profile: UserProfile) -> None:
    async with repository.transaction() as tx:
        tx.upsert_profile(profile)
