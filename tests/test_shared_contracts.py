"""Shared contract tests."""

from __future__ import annotations

import unittest

from shared.contracts import (
    DataType,
    data_type_spec,
    normalize_data_type,
)


class DataTypeContractTest(unittest.TestCase):
    def test_normalizes_blank_to_project_document(self) -> None:
        self.assertEqual(normalize_data_type(None), DataType.PROJECT_DOCUMENT)
        self.assertEqual(normalize_data_type(""), DataType.PROJECT_DOCUMENT)

    def test_rejects_unknown_data_type(self) -> None:
        with self.assertRaises(ValueError):
            normalize_data_type("unknown")

    def test_registry_marks_memory_executable(self) -> None:
        memory = data_type_spec("agent_memory")
        workflow = data_type_spec("workflow_log")

        self.assertTrue(memory.executable)
        self.assertEqual(memory.owner_service, "memory_service")
        self.assertFalse(workflow.executable)
        self.assertEqual(workflow.owner_service, "workflow_log_service")


if __name__ == "__main__":
    unittest.main()
