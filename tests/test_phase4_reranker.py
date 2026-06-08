"""Phase 4 tests: reranker wrapper."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from retrieval_service.services.reranker import RerankerService, _rerank_texts


class RerankTextsTest(unittest.TestCase):
    def test_ranks_by_score_descending(self) -> None:
        model = MagicMock()
        model.predict.return_value = [0.1, 0.9, 0.5]

        result = _rerank_texts(model, "What is X?", ["a", "b", "c"])

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], 1)  # idx 1 has highest score
        self.assertAlmostEqual(result[0][1], 0.9)

    def test_handles_empty_list(self) -> None:
        model = MagicMock()
        model.predict.return_value = []

        result = _rerank_texts(model, "q", [])

        self.assertEqual(result, [])

    def test_returns_float_scores(self) -> None:
        model = MagicMock()
        model.predict.return_value = [0.5]

        result = _rerank_texts(model, "q", ["text"])

        self.assertIsInstance(result[0][1], float)


class RerankerServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_rerank_empty_pairs(self) -> None:
        service = RerankerService()

        result = await service.rerank("query", [])

        self.assertEqual(result, [])

    async def test_rerank_sorts_and_returns_reordered(self) -> None:
        service = RerankerService()
        service._model = MagicMock()
        service._executor = MagicMock()

        pairs = [
            ({"text": "A", "id": "1"}, 0.5),
            ({"text": "B", "id": "2"}, 0.4),
        ]

        async def _fake_executor(executor, fn, model, query, texts):
            return [(1, 0.8), (0, 0.3)]

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = _fake_executor
            result = await service.rerank("query", pairs)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0]["text"], "B")  # higher score first
        self.assertAlmostEqual(result[0][1], 0.8)


if __name__ == "__main__":
    unittest.main()
