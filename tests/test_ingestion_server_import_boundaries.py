"""Ingestion server import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

GUARDED_FILES = (
    ROOT / "ingestion_service" / "server" / "app.py",
    ROOT / "ingestion_service" / "server" / "consumer.py",
)

FORBIDDEN_PREFIXES = (
    "manager_service",
    "project_service",
    "retrieval_service",
    "qdrant_client",
)


class IngestionServerImportBoundaryTest(unittest.TestCase):
    def test_ingestion_server_queue_modules_do_not_import_other_service_internals(self) -> None:
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
