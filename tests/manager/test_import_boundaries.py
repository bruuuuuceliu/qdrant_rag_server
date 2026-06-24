"""Manager core import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]

GUARDED_FILES = (
    ROOT / "manager_service" / "clients.py",
    ROOT / "manager_service" / "service.py",
    ROOT / "manager_service" / "server" / "app.py",
)

FORBIDDEN_PREFIXES = (
    "project_service",
    "retrieval_service",
    "ingestion_service",
    "qdrant_client",
)


class ManagerImportBoundaryTest(unittest.TestCase):
    def test_manager_core_does_not_import_service_internals(self) -> None:
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
