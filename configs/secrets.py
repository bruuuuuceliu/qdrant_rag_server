"""Secret resolution helpers.

Production secrets are injected either as environment variables or as files —
the standard Docker secret / Kubernetes ``secretKeyRef`` ``mountPath`` pattern,
and the common way secret managers (Vault, AWS/SSM, etc.) materialize secrets
into a container. For every secret key ``X`` the loader also accepts an
``X_FILE`` variable holding a path whose content (trailing newline stripped)
becomes the value. Resolution is applied wherever settings load their value map,
so ``BROKER_SASL_PLAIN_PASSWORD_FILE`` and ``SERVICE_AUTH_SIGNING_KEY_FILE`` work
the same as their plain env counterparts.

An empty env value is never replaced by a file — ``X_FILE`` must point at an
existing file; otherwise the setting loader's own validation decides (e.g. the
memory broker-mode guard).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def resolve_secret_files(values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a copy of ``values`` with ``KEY_FILE`` entries resolved.

    For each ``KEY_FILE`` whose path exists, set ``values[KEY]`` to the file
    content and drop the ``KEY_FILE`` entry. ``KEY_FILE`` variables that point at
    missing files are left untouched so the settings loader can raise a clear
    validation error about the missing secret.
    """
    values = dict(values) if values is not None else dict(os.environ)
    for name in list(values):
        if not name.endswith("_FILE"):
            continue
        key = name[: -len("_FILE")]
        if not key:
            continue
        path = Path(str(values[name]))
        if path.exists() and path.is_file():
            values[key] = path.read_text(encoding="utf-8").strip()
            del values[name]
    return values


def read_secret(key: str, values: dict[str, Any] | None = None) -> str:
    """Resolve one secret from ``values`` (env default), preferring ``key_FILE``."""
    resolved = resolve_secret_files(values)
    return str(resolved.get(key, ""))


__all__ = ["read_secret", "resolve_secret_files"]
