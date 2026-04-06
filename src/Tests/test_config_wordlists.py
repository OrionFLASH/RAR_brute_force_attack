# Тесты разбора блока wordlists и обратной совместимости с ключом wordlist.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rar_bruteforce.config_loader import load_config


class TestWordlistsConfig(unittest.TestCase):
    """Проверка порядка и полей словарей в Config.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, obj: dict) -> Path:
        p = self.root / name
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return p

    def test_multiple_entries_order(self) -> None:
        cfg_path = self._write(
            "Config.json",
            {
                "directories": {"in": "IN", "out": "OUT"},
                "archive_file": "a.rar",
                "database": {"filename": "db.sqlite"},
                "password": {
                    "min_length": 1,
                    "max_length": 4,
                    "charset": "a",
                    "numeric_charset": "0",
                },
                "wordlists": {
                    "defaults": {"encoding": "utf-8", "max_line_length": 10, "skip_lines_starting_with": "#"},
                    "entries": [
                        {"path": "wordlists/small.txt", "label": "first"},
                        {"path": "wordlists/big.txt", "label": "xato_10m", "max_line_length": 200},
                    ],
                },
                "hybrid": {"enabled": False},
                "checker": {"mode": "rarfile", "unrar_path": ""},
                "parallelism": {"max_workers": 1, "reserve_cpu_cores": 0, "batch_size": 2},
                "runtime": {"esc_key_enabled": False, "progress_log_every_sec": 5},
            },
        )
        cfg = load_config(self.root, cfg_path)
        self.assertEqual(len(cfg.wordlists), 2)
        self.assertEqual(cfg.wordlists[0].label, "first")
        self.assertEqual(cfg.wordlists[1].label, "xato_10m")
        self.assertEqual(cfg.wordlists[1].max_line_length, 200)

    def test_legacy_wordlist_key(self) -> None:
        cfg_path = self._write(
            "Config.json",
            {
                "directories": {"in": "IN", "out": "OUT"},
                "archive_file": "a.rar",
                "database": {"filename": "db.sqlite"},
                "password": {
                    "min_length": 1,
                    "max_length": 4,
                    "charset": "a",
                    "numeric_charset": "0",
                },
                "wordlist": {"path": "wordlists/one.txt", "encoding": "latin-1", "max_line_length": 50},
                "hybrid": {"enabled": False},
                "checker": {"mode": "rarfile", "unrar_path": ""},
                "parallelism": {"max_workers": 1, "reserve_cpu_cores": 0, "batch_size": 2},
                "runtime": {"esc_key_enabled": False, "progress_log_every_sec": 5},
            },
        )
        cfg = load_config(self.root, cfg_path)
        self.assertEqual(len(cfg.wordlists), 1)
        self.assertEqual(cfg.wordlists[0].encoding, "latin-1")
        self.assertEqual(cfg.wordlists[0].max_line_length, 50)

    def test_parallelism_accelerator_flags_default_false(self) -> None:
        cfg_path = self._write(
            "Config.json",
            {
                "directories": {"in": "IN", "out": "OUT"},
                "archive_file": "a.rar",
                "database": {"filename": "db.sqlite"},
                "password": {
                    "min_length": 1,
                    "max_length": 4,
                    "charset": "a",
                    "numeric_charset": "0",
                },
                "wordlists": {"defaults": {"max_line_length": 10}, "entries": []},
                "hybrid": {"enabled": False},
                "checker": {"mode": "rarfile", "unrar_path": ""},
                "parallelism": {"max_workers": 1, "reserve_cpu_cores": 0, "batch_size": 2},
                "runtime": {"esc_key_enabled": False, "progress_log_every_sec": 5},
            },
        )
        cfg = load_config(self.root, cfg_path)
        self.assertFalse(cfg.use_gpu)
        self.assertFalse(cfg.use_neural_accelerator)

    def test_parallelism_accelerator_flags_true(self) -> None:
        cfg_path = self._write(
            "Config.json",
            {
                "directories": {"in": "IN", "out": "OUT"},
                "archive_file": "a.rar",
                "database": {"filename": "db.sqlite"},
                "password": {
                    "min_length": 1,
                    "max_length": 4,
                    "charset": "a",
                    "numeric_charset": "0",
                },
                "wordlists": {"defaults": {"max_line_length": 10}, "entries": []},
                "hybrid": {"enabled": False},
                "checker": {"mode": "rarfile", "unrar_path": ""},
                "parallelism": {
                    "max_workers": 1,
                    "reserve_cpu_cores": 0,
                    "batch_size": 2,
                    "use_gpu": True,
                    "use_neural_accelerator": True,
                },
                "runtime": {"esc_key_enabled": False, "progress_log_every_sec": 5},
            },
        )
        cfg = load_config(self.root, cfg_path)
        self.assertTrue(cfg.use_gpu)
        self.assertTrue(cfg.use_neural_accelerator)


if __name__ == "__main__":
    unittest.main()
