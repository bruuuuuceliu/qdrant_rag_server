"""Runtime checks for the documented local composition script."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "examples" / "local" / "run-all.sh"


def test_local_runner_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(RUNNER)], cwd=ROOT, check=True)


def test_local_runner_uses_isolated_local_broker_and_redis_namespaces(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    env = dict(os.environ)
    env.update(
        {
            "PYTHON_BIN": sys.executable,
            "RAG_LOCAL_RUNTIME_DIR": str(runtime_dir),
            "RAG_LOCAL_ENV_FILE": str(tmp_path / "missing-local.env"),
        }
    )
    env.pop("BROKER_TOPIC_PREFIX", None)
    env.pop("REDIS_TASK_STATUS_KEY_PREFIX", None)

    result = subprocess.run(
        [
            str(RUNNER),
            "--no-server",
            "--no-qdrant",
            "--project-id",
            "runner-test",
            "--project-type",
            "website",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    state = (runtime_dir / "state.env").read_text(encoding="utf-8")
    assert "BROKER_TOPIC_PREFIX=qdrant-rag-local." in state
    assert "REDIS_TASK_STATUS_KEY_PREFIX=qdrant-rag-local:task:" in state
    assert "Setup complete; services were not started" in result.stdout


def test_local_runner_rejects_smoke_without_services(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.update(
        {
            "PYTHON_BIN": sys.executable,
            "RAG_LOCAL_RUNTIME_DIR": str(tmp_path / "runtime"),
            "RAG_LOCAL_ENV_FILE": str(tmp_path / "missing-local.env"),
        }
    )

    result = subprocess.run(
        [str(RUNNER), "--smoke", "--no-server"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--smoke cannot be combined with --no-server" in result.stderr
