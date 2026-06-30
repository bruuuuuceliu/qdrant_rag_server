"""Project service import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUARDED_ROOT = ROOT / "project_service"
FORBIDDEN_PREFIXES = (
    "ingestion_service",
    "manager_service",
    "redis_status_node",
    "retrieval_service",
    "sqlite_node",
    "storage_node",
    "task_manager_service",
    "task_service",
    "workflow_log_service",
)


def test_project_domain_modules_do_not_import_other_service_internals() -> None:
    assert _violations() == []


def _violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(GUARDED_ROOT.rglob("*.py")):
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
