# Работа с SQLite: учёт проверенных паролей и дозапись при остановке.

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Iterable, Sequence


@dataclass(frozen=True)
class AttemptRow:
    """Одна строка журнала проверки."""

    archive_key: str
    password: str
    result: str
    checked_at: str


def connect_db(db_path: Path, journal_mode: str = "WAL") -> sqlite3.Connection:
    """Открывает БД, включает WAL и внешние ключи (на будущее)."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute(f"PRAGMA journal_mode={journal_mode};")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Создаёт таблицу попыток и индекс для быстрого пропуска уже проверенных."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archive_key TEXT NOT NULL,
            password TEXT NOT NULL,
            result TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            UNIQUE(archive_key, password)
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attempts_archive_password
        ON attempts(archive_key, password);
        """
    )
    conn.commit()


def filter_untested_passwords(
    conn: sqlite3.Connection,
    archive_key: str,
    passwords: Sequence[str],
) -> list[str]:
    """
    Из списка паролей оставляет только те, которых ещё нет в БД для данного архива.

    Использует один запрос с IN для пакета.
    """
    if not passwords:
        return []
    placeholders = ",".join("?" for _ in passwords)
    sql = f"SELECT password FROM attempts WHERE archive_key = ? AND password IN ({placeholders})"
    cur = conn.execute(sql, (archive_key, *passwords))
    already = {row[0] for row in cur.fetchall()}
    return [p for p in passwords if p not in already]


def insert_attempts(conn: sqlite3.Connection, rows: Iterable[AttemptRow]) -> None:
    """Пакетная вставка; при повторе того же (archive_key, password) — игнор."""
    batch = list(rows)
    if not batch:
        return
    conn.executemany(
        """
        INSERT OR IGNORE INTO attempts (archive_key, password, result, checked_at)
        VALUES (?, ?, ?, ?);
        """,
        [(r.archive_key, r.password, r.result, r.checked_at) for r in batch],
    )
    conn.commit()


def utc_now_iso() -> str:
    """Текущее время UTC в ISO-формате для поля checked_at."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def db_connection(db_path: Path, journal_mode: str = "WAL") -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер со схемой."""
    conn = connect_db(db_path, journal_mode=journal_mode)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()
