"""Shared prereqs + container runner for the SA<->RAG broker interop live tests.

The closeout lookup and identity tests run SA's real ``MemoryBrokerClient``
inside a throwaway container on ``rag-memory-test`` exactly like the committed
``test_sa_broker_interop.py``. Keeping that harness here lets the committed test
stay untouched while the two new opt-in live tests reuse it.

Why the client runs inside a container: the production Redpanda INTERNAL
listener advertises ``redpanda-rag-local:19092`` (the ``rag-memory-test`` DNS
alias), which the host cannot resolve. A host-run aiokafka client would
bootstrap to ``127.0.0.1:19092`` and then fail to reach the advertised node
address. Running the client in a container on ``rag-memory-test`` resolves the
alias natively and exercises the real production transport path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# simple_agent checkout (read-only mount into the client container).
SIMPLE_AGENT_ROOT = Path(
    os.environ.get("SIMPLE_AGENT_ROOT", "/home/bruce/workspace/simple_agent")
)
RAG_IMAGE = os.environ.get("RAG_INTEROP_IMAGE", "qdrant-rag-server:latest")
NETWORK = os.environ.get("RAG_INTEROP_NETWORK", "rag-memory-test")
MEMORY_READYZ_URL = os.environ.get("RAG_MEMORY_READYZ_URL", "http://127.0.0.1:9012/readyz")
RETRIEVAL_READYZ_URL = os.environ.get(
    "RAG_RETRIEVAL_READYZ_URL", "http://127.0.0.1:9007/readyz"
)
RETRIEVAL_INDEX_READYZ_URL = os.environ.get(
    "RAG_RETRIEVAL_INDEX_READYZ_URL", "http://127.0.0.1:9008/readyz"
)
QDRANT_READYZ_URL = os.environ.get("RAG_QDRANT_READYZ_URL", "http://127.0.0.1:6333/readyz")
BOOTSTRAP = os.environ.get("REDPANDA_BOOTSTRAP_SERVERS", "redpanda-rag-local:19092")
SIGNING_KEY = os.environ.get("SERVICE_AUTH_SIGNING_KEY", "")
ISSUER = os.environ.get("SERVICE_AUTH_TOKEN_ISSUER", "simple-agent-local")
AUDIENCE = os.environ.get("SERVICE_AUTH_TOKEN_AUDIENCE", "simple-agent-internal")


def require_live_infra() -> None:
    if os.environ.get("RAG_LIVE_INFRA") != "1":
        pytest.skip("set RAG_LIVE_INFRA=1 to run live infrastructure tests")


def _readyz_or_skip(
    url: str, what: str, *, ready_marker: str = '"ready":true'
) -> str:
    """Fetch a readiness probe, skipping unless it reports ready.

    RAG workers render ``RuntimeHealth`` JSON with a ``"ready":true`` field.
    Qdrant's ``/readyz`` reports "all shards are ready" (a 200 is itself the
    ready signal), so ``ready_marker=""`` turns off the body check for it.
    """
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        pytest.skip(f"{what} not ready at {url}: {body}")
    except Exception as exc:  # noqa: BLE001 - any unreachability means skip
        pytest.skip(f"{what} not reachable at {url}: {exc}")
    if ready_marker and ready_marker not in body:
        pytest.skip(f"{what} not ready at {url}: {body}")
    return body


def require_prereqs(*, need_identity: bool = False, need_retrieval: bool = False) -> None:
    if not (SIMPLE_AGENT_ROOT / "libs/service-auth/src").is_dir() or not (
        SIMPLE_AGENT_ROOT / "services/conversation-server/src"
    ).is_dir():
        pytest.skip(
            f"simple_agent checkout not present at {SIMPLE_AGENT_ROOT}; "
            "skipping SA<->RAG broker interop"
        )
    if not SIGNING_KEY:
        pytest.skip(
            "SERVICE_AUTH_SIGNING_KEY is required and must match the RAG memory "
            "worker's SERVICE_AUTH_SIGNING_KEY"
        )
    if shutil.which("docker") is None:
        pytest.skip("docker is not available")
    inspect_net = subprocess.run(
        ["docker", "network", "inspect", NETWORK], capture_output=True, text=True
    )
    if inspect_net.returncode != 0:
        pytest.skip(
            f"docker network {NETWORK!r} not present; bring up the RAG production "
            "compose first (see the test module docstrings)"
        )
    memory_body = _readyz_or_skip(MEMORY_READYZ_URL, "RAG memory worker")
    if need_identity and '"identity_mode":"broker"' not in memory_body:
        pytest.skip(
            "RAG memory worker is not consuming identity events "
            f"(identity_mode != broker) at {MEMORY_READYZ_URL}: {memory_body}"
        )
    if need_identity and '"broker_identity_consumer":true' not in memory_body:
        pytest.skip(
            "RAG memory worker's identity consumer is not attached "
            f"at {MEMORY_READYZ_URL}: {memory_body}"
        )
    if need_retrieval:
        _readyz_or_skip(RETRIEVAL_READYZ_URL, "RAG retrieval worker")
        _readyz_or_skip(RETRIEVAL_INDEX_READYZ_URL, "RAG retrieval-index worker")
        _readyz_or_skip(QDRANT_READYZ_URL, "Qdrant", ready_marker="")
        if '"index_mode":"broker"' not in memory_body or (
            '"search_mode":"broker"' not in memory_body
        ):
            pytest.skip(
                "RAG memory worker is not wired for broker retrieval "
                f"(index/search modes) at {MEMORY_READYZ_URL}: {memory_body}"
            )
    inspect_image = subprocess.run(
        ["docker", "image", "inspect", RAG_IMAGE], capture_output=True
    )
    if inspect_image.returncode != 0:
        pytest.skip(f"RAG image {RAG_IMAGE!r} not built")


def run_client_in_container(
    tmp_path: Path, script_text: str, *, label: str
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / f"{label}.py"
    script.write_text(script_text, encoding="utf-8")
    cmd = [
        "docker", "run", "--rm",
        "--network", NETWORK,
        "-e", f"REDPANDA_BOOTSTRAP_SERVERS={BOOTSTRAP}",
        "-e", f"SERVICE_AUTH_SIGNING_KEY={SIGNING_KEY}",
        "-e", f"SERVICE_AUTH_TOKEN_ISSUER={ISSUER}",
        "-e", f"SERVICE_AUTH_TOKEN_AUDIENCE={AUDIENCE}",
        "-v", f"{SIMPLE_AGENT_ROOT}:/sa:ro",
        "-v", f"{script}:/app/{label}.py:ro",
        "--entrypoint", "python3",
        RAG_IMAGE,
        f"/app/{label}.py",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)
