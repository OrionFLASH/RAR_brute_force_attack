# Тест сводки размещения воркеров по CPU.

from __future__ import annotations

import unittest

from rar_bruteforce.placement import summarize_batch_worker_placement


class TestPlacement(unittest.TestCase):
    """Проверка текста сводки для лога."""

    def test_summarize_groups_by_pid(self) -> None:
        metas = [
            {"pid": 100, "process_name": "SpawnPoolWorker-1", "cpu_num": 3},
            {"pid": 100, "process_name": "SpawnPoolWorker-1", "cpu_num": 5},
            {"pid": 200, "process_name": "SpawnPoolWorker-2", "cpu_num": 1},
        ]
        s = summarize_batch_worker_placement(metas)
        self.assertIn("SpawnPoolWorker-1", s)
        self.assertIn("pid=100", s)
        self.assertIn("CPU[3,5]", s)
        self.assertIn("pid=200", s)
        self.assertIn("CPU[1]", s)
        self.assertIn("только CPU", s)
        self.assertIn("GPU/NPU", s)

    def test_missing_cpu_num(self) -> None:
        metas = [{"pid": 1, "process_name": "x", "cpu_num": None}]
        s = summarize_batch_worker_placement(metas)
        self.assertIn("CPU[?]", s)


if __name__ == "__main__":
    unittest.main()
