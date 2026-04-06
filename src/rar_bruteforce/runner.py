# Оркестрация фаз перебора, пул процессов, остановка и запись в SQLite.

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator

from multiprocessing import Pool, get_context

from .config_loader import AppConfig
from .db_sqlite import AttemptRow, filter_untested_passwords, insert_attempts, utc_now_iso
from .generators import iter_dictionary_passwords, iter_hybrid_passwords, iter_numeric_passwords
from .logging_setup import get_logger, log_debug
from .worker import pool_initializer, try_password

log = get_logger("runner")


def compute_worker_count(cfg: AppConfig) -> int:
    """
    Число воркеров: все доступные ядра минус резерв, чтобы ОС оставалась отзывчивой.

    Явный max_workers в конфиге ограничивает сверху.
    """
    cpu = os.cpu_count() or 2
    n = max(1, cpu - max(0, cfg.reserve_cpu_cores))
    if cfg.max_workers is not None:
        n = min(n, max(1, cfg.max_workers))
    return n


def _batched(it: Iterator[str], size: int) -> Iterator[list[str]]:
    """Нарезает итератор на списки фиксированного размера."""
    buf: list[str] = []
    for item in it:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def _start_esc_listener(stop: threading.Event, enabled: bool) -> Any:
    """
    Слушатель Esc через pynput (неблокирующий). Если библиотеки нет — только Ctrl+C.

    Возвращает объект Listener или None.
    """
    if not enabled:
        return None
    try:
        from pynput import keyboard  # type: ignore[import-untyped]
    except Exception:
        log.info("Клавиша Esc недоступна (нет pynput); используйте Ctrl+C для остановки.")
        return None

    def on_press(key: keyboard.Key | keyboard.KeyCode) -> None:
        try:
            if key == keyboard.Key.esc:
                stop.set()
        except Exception:
            stop.set()

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    return listener


def build_phase_plan(cfg: AppConfig) -> list[tuple[str, Iterator[str]]]:
    """
    План фаз от простого к сложному:

    1) Числовой перебор.
    2) Для каждого словаря по порядку в конфиге — фаза dictionary (простые словари первыми).
    3) Для каждого словаря в том же порядке — фаза hybrid (расширения; тяжёлый xato — последним).
    """
    plan: list[tuple[str, Iterator[str]]] = [("numeric", iter_numeric_passwords(cfg))]
    for spec in cfg.wordlists:
        plan.append((f"dictionary[{spec.label}]", iter_dictionary_passwords(cfg, spec)))
    if cfg.hybrid_enabled:
        for spec in cfg.wordlists:
            plan.append((f"hybrid[{spec.label}]", iter_hybrid_passwords(cfg, spec)))
    return plan


class BruteForceRunner:
    """Запуск фаз перебора с записью результатов в БД и корректной остановкой."""

    def __init__(self, cfg: AppConfig, conn_factory: Callable[[], sqlite3.Connection]) -> None:
        self.cfg = cfg
        self._conn_factory = conn_factory
        self.stop_event = threading.Event()

    def _archive_path(self) -> Path:
        p = (self.cfg.dir_in / self.cfg.archive_file).resolve()
        return p

    def _db_path(self) -> Path:
        return (self.cfg.dir_out / self.cfg.db_filename).resolve()

    def _payload(self, archive_path: Path) -> dict:
        """Словарь для инициализации воркеров (должен быть picklable)."""
        tool = self.cfg.unrar_path.strip() if self.cfg.checker_mode == "rarfile" else ""
        return {
            "archive_path": str(archive_path),
            "checker_mode": self.cfg.checker_mode,
            "unrar_path": self.cfg.unrar_path,
            "unrar_command": self.cfg.unrar_command,
            "unrar_timeout_sec": self.cfg.unrar_timeout_sec,
            "unrar_tool": tool,
        }

    def _run_pool_batch(self, pool: Pool, passwords: list[str]) -> list[tuple[str, str, str]]:
        """Выполняет проверку пакета паролей в пуле."""
        return list(pool.map(try_password, passwords, chunksize=1))

    def _handle_sigint(self, signum: int, frame: object | None) -> None:
        self.stop_event.set()
        log.info("Получен сигнал прерывания; завершаем после текущего пакета…")

    def _log_missing_wordlists(self) -> None:
        """Предупреждение, если какие-то файлы словарей отсутствуют на диске."""
        missing = [w for w in self.cfg.wordlists if not w.path.is_file()]
        if missing:
            for w in missing:
                log.warning("Словарь не найден (фазы для него будут пропущены): %s", w.path)
        if not self.cfg.wordlists:
            log.warning("Список словарей пуст: фазы dictionary/hybrid не дадут кандидатов.")

    def run(self) -> int:
        """
        Выполняет все фазы. Возвращает код выхода: 0 — пароль найден, 1 — нет, 2 — ошибка.
        """
        archive_path = self._archive_path()
        if not archive_path.is_file():
            log.error("Архив не найден: %s", archive_path)
            return 2

        archive_key = str(archive_path)
        db_path = self._db_path()
        log.info("Архив: %s", archive_path)
        log.info("База попыток: %s", db_path)
        self._log_missing_wordlists()

        workers = compute_worker_count(self.cfg)
        log.info("Число процессов-воркеров: %s (логические ядра с учётом резерва)", workers)

        signal.signal(signal.SIGINT, self._handle_sigint)
        self._esc = _start_esc_listener(self.stop_event, self.cfg.esc_key_enabled)

        ctx = get_context("spawn")
        payload = self._payload(archive_path)
        phases = build_phase_plan(self.cfg)

        conn = self._conn_factory()
        try:
            with ctx.Pool(
                processes=workers,
                initializer=pool_initializer,
                initargs=(payload,),
            ) as pool:
                total_checked = 0
                t0 = time.monotonic()
                last_prog = t0

                for phase_name, gen in phases:
                    if self.stop_event.is_set():
                        log.info("Остановка до фазы %s", phase_name)
                        break
                    log.info("Старт фазы: %s", phase_name)
                    for batch in _batched(gen, self.cfg.batch_size):
                        if self.stop_event.is_set():
                            break
                        untested = filter_untested_passwords(conn, archive_key, batch)
                        if not untested:
                            continue
                        results = self._run_pool_batch(pool, untested)
                        rows: list[AttemptRow] = []
                        now = utc_now_iso()
                        for pwd, outcome, note in results:
                            r = outcome if outcome in ("ok", "fail", "error") else "error"
                            rows.append(AttemptRow(archive_key, pwd, r, now))
                            if outcome == "error" and note:
                                log_debug(
                                    log,
                                    f"Ошибка проверки пароля: {note}",
                                    class_name="BruteForceRunner",
                                    func_name="run",
                                )
                        insert_attempts(conn, rows)
                        for pwd, outcome, _note in results:
                            if outcome == "ok":
                                log.info("Пароль найден: %s", pwd)
                                print(f"\nУСПЕХ. Пароль: {pwd}\n", flush=True)
                                return 0
                        total_checked += len(rows)
                        now_m = time.monotonic()
                        if now_m - last_prog >= self.cfg.progress_log_every_sec:
                            last_prog = now_m
                            rate = total_checked / max(1e-9, (now_m - t0))
                            log.info(
                                "Фаза %s: проверено всего %s паролей (~%.1f пар/с)",
                                phase_name,
                                total_checked,
                                rate,
                            )
                    if self.stop_event.is_set():
                        break

                if self.stop_event.is_set():
                    log.info("Работа остановлена пользователем; данные записаны в БД.")
                else:
                    log.info("Перебор завершён, пароль не найден в заданных фазах.")
                return 1
        finally:
            conn.close()
