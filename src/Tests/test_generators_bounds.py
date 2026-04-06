# Проверка: словарь и гибрид не выдают пароли вне [min_length, max_length].

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rar_bruteforce.config_loader import AppConfig, WordlistSpec
from rar_bruteforce.generators import iter_dictionary_passwords, iter_hybrid_passwords


def _cfg(**over) -> AppConfig:
    base = dict(
        project_root=Path("."),
        dir_in=Path("IN"),
        dir_out=Path("OUT"),
        archive_file="a.rar",
        db_filename="db.sqlite",
        db_journal_mode="WAL",
        pwd_min_len=4,
        pwd_max_len=6,
        charset="a",
        numeric_charset="0",
        wordlists=[],
        hybrid_enabled=True,
        hybrid_suffix_digits_min_len=0,
        hybrid_suffix_digits_max_len=2,
        hybrid_suffix_specials=["_"],
        hybrid_prefix_digits_max_len=2,
        hybrid_combine_word_special_digit=True,
        checker_mode="rarfile",
        unrar_path="",
        unrar_command="t",
        unrar_timeout_sec=120,
        rarfile_open_timeout_sec=120,
        max_workers=1,
        reserve_cpu_cores=0,
        batch_size=4,
        use_gpu=False,
        use_neural_accelerator=False,
        esc_key_enabled=False,
        progress_log_every_sec=5,
        log_worker_placement_every_batch=False,
        log_worker_placement_on_progress=False,
    )
    base.update(over)
    return AppConfig(**base)  # type: ignore[arg-type]


class TestGeneratorLengthBounds(unittest.TestCase):
    """Все кандидаты из словаря и гибрида укладываются в лимиты длины."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dictionary_skips_wrong_length(self) -> None:
        p = self.root / "w.txt"
        p.write_text("ab\nabcdefgh\n1234\n12\n", encoding="utf-8")
        spec = WordlistSpec(p, "t", "utf-8", 64, "#")
        cfg = _cfg(pwd_min_len=4, pwd_max_len=6)
        out = list(iter_dictionary_passwords(cfg, spec))
        self.assertEqual(out, ["1234"])

    def test_hybrid_all_lengths_in_range(self) -> None:
        p = self.root / "w.txt"
        p.write_text("ab\n", encoding="utf-8")
        spec = WordlistSpec(p, "t", "utf-8", 64, "#")
        cfg = _cfg(pwd_min_len=4, pwd_max_len=6)
        for cand in iter_hybrid_passwords(cfg, spec):
            self.assertGreaterEqual(len(cand), 4, cand)
            self.assertLessEqual(len(cand), 6, cand)

    def test_hybrid_skips_too_long_base_word(self) -> None:
        p = self.root / "w.txt"
        p.write_text("abcdefg\n", encoding="utf-8")
        spec = WordlistSpec(p, "t", "utf-8", 64, "#")
        cfg = _cfg(pwd_min_len=1, pwd_max_len=5)
        out = list(iter_hybrid_passwords(cfg, spec))
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
