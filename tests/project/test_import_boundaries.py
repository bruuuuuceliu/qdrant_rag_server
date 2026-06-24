"""Project service import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUARDED_FILES = (
    ROOT / "project_service" / "domain_app.py",
    ROOT / "project_service" / "domain_handler.py",
    ROOT / "project_service" / "planning.py",
    ROOT / "project_service" / "tasks.py",
)
FORBIDDEN_PREFIXES = (
    "manager_service",
    "workflow_log_service",
    "ingestion_service",
)


def test_project_domain_modules_do_not_import_other_service_internals() -> None:
    assert _violations() == []


def _violations() -> list[str]:
    violations: list[str] = []
    for path in GUARDED_FILES:
        for module in _imports(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    return violations


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
