"""Local runner smoke tests."""

from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


class LocalRunnerTest(unittest.TestCase):
    def test_no_server_dry_run_writes_state_and_reports_placement(self) -> None:
        with TemporaryDirectory() as tempdir:
            runtime_dir = Path(tempdir) / "run"
            data_dir = Path(tempdir) / "data"
            result = _run_local(
                [
                    "--no-server",
                    "--no-qdrant",
                    "--project-id",
                    "smoke",
                    "--project-type",
                    "website",
                ],
                runtime_dir=runtime_dir,
                data_dir=data_dir,
            )

            state = (runtime_dir / "state.env").read_text(encoding="utf-8")

        self.assertIn("config_profile:      local", result.stdout)
        self.assertIn("placement_db:", result.stdout)
        self.assertIn("placement_mode:      project_single", result.stdout)
        self.assertIn("retrieval_mode:      local", result.stdout)
        self.assertIn("Setup complete", result.stdout)
        self.assertIn("RAG_LOCAL_DATA_DIR=", state)
        self.assertIn("RETRIEVAL_INDEX_REQUEST_TOPIC=retrieval.index.requests", state)
        self.assertEqual(result.returncode, 0)

    def test_split_no_server_reports_external_workers_and_sqlite_queue(self) -> None:
        with TemporaryDirectory() as tempdir:
            result = _run_local(
                [
                    "--split-services",
                    "--no-server",
                    "--project-id",
                    "smoke",
                    "--project-type",
                    "website",
                ],
                runtime_dir=Path(tempdir) / "run",
                data_dir=Path(tempdir) / "data",
            )

        self.assertIn("ingestion_mode:      external", result.stdout)
        self.assertIn("queue_broker:        sqlite", result.stdout)
        self.assertIn("ingestion_index_pub: true", result.stdout)
        self.assertIn("project_client_mode: grpc", result.stdout)

    def test_external_retrieval_http_no_server_reports_http_mode(self) -> None:
        with TemporaryDirectory() as tempdir:
            result = _run_local(
                [
                    "--external-retrieval-http",
                    "--no-server",
                    "--project-id",
                    "smoke",
                    "--project-type",
                    "website",
                ],
                runtime_dir=Path(tempdir) / "run",
                data_dir=Path(tempdir) / "data",
            )

        self.assertIn("retrieval_http:      127.0.0.1:8081", result.stdout)
        self.assertIn("retrieval_mode:      http", result.stdout)
        self.assertIn("project_client_mode: local", result.stdout)

    def test_rejects_unsupported_external_http_split_mode_before_setup(self) -> None:
        with TemporaryDirectory() as tempdir:
            result = _run_local(
                [
                    "--external-retrieval-http",
                    "--split-services",
                    "--no-server",
                ],
                runtime_dir=Path(tempdir) / "run",
                data_dir=Path(tempdir) / "data",
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported local runner mode", result.stderr)

    def test_stop_clean_removes_runtime_state_without_docker(self) -> None:
        root = _root()
        with TemporaryDirectory() as tempdir:
            runtime_dir = Path(tempdir) / "run"
            data_dir = Path(tempdir) / "data"
            _run_local(
                ["--no-server", "--no-qdrant"],
                runtime_dir=runtime_dir,
                data_dir=data_dir,
            )

            subprocess.run(
                [str(root / "examples" / "local" / "stop-all.sh"), "--clean", "--no-docker"],
                cwd=root,
                env={
                    "PATH": "/usr/bin:/bin",
                    "RAG_LOCAL_RUNTIME_DIR": str(runtime_dir),
                    "RAG_LOCAL_DATA_DIR": str(data_dir),
                },
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertFalse(runtime_dir.exists())


def _run_local(
    args: list[str],
    *,
    runtime_dir: Path,
    data_dir: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    root = _root()
    return subprocess.run(
        [str(root / "examples" / "local" / "run-all.sh"), *args],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin",
            "RAG_LOCAL_RUNTIME_DIR": str(runtime_dir),
            "RAG_LOCAL_DATA_DIR": str(data_dir),
            "RAG_EMBEDDING_PROVIDER": "local",
        },
        text=True,
        capture_output=True,
        check=check,
    )


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    unittest.main()
