# Тесты SQLite-слоя: схема, фильтрация уже проверенных, вставка.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rar_bruteforce.db_sqlite import (
    AttemptRow,
    connect_db,
    filter_untested_passwords,
    init_schema,
    insert_attempts,
)


class TestSqlite(unittest.TestCase):
    """Проверка журнала попыток без реального RAR."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "t.sqlite"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_filter_skips_existing(self) -> None:
        conn = connect_db(self.db_path)
        init_schema(conn)
        ak = "/fake/archive.rar"
        insert_attempts(
            conn,
            [AttemptRow(ak, "123", "fail", "2026-01-01T00:00:00+00:00")],
        )
        fresh = filter_untested_passwords(conn, ak, ["123", "456"])
        self.assertEqual(fresh, ["456"])
        conn.close()

    def test_insert_ignore_duplicate(self) -> None:
        conn = connect_db(self.db_path)
        init_schema(conn)
        ak = "/x/a.rar"
        row = AttemptRow(ak, "p", "fail", "2026-01-01T00:00:00+00:00")
        insert_attempts(conn, [row, row])
        cur = conn.execute("SELECT COUNT(*) FROM attempts WHERE archive_key=?", (ak,))
        self.assertEqual(cur.fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
