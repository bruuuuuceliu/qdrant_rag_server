"""Retrieval API import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

GUARDED_FILES = (
    ROOT / "retrieval_service" / "retrieval" / "contracts.py",
    ROOT / "retrieval_service" / "retrieval" / "handler.py",
    ROOT / "retrieval_service" / "server" / "app.py",
    ROOT / "retrieval_service" / "server" / "http.py",
    ROOT / "retrieval_service" / "server" / "queue.py",
)

FORBIDDEN_PREFIXES = (
    "manager_service",
    "project_service",
    "ingestion_service",
    "project_service.server.grpc.generated",
    "retrieval_service.server.grpc.generated",
    "grpc",
)


class RetrievalApiImportBoundaryTest(unittest.TestCase):
    def test_retrieval_api_server_modules_do_not_import_transport_or_other_services(self) -> None:
        violations: list[str] = []
        for path in GUARDED_FILES:
            for module in _imports(path):
                if module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")

        self.assertEqual(violations, [])


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


if __name__ == "__main__":
    unittest.main()
