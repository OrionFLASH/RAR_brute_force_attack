# Оркестрация фаз перебора, пул процессов, остановка и запись в SQLite.

from __future__ import annotations

import logging
import multiprocessing
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
from .logging_setup import get_logger, log_diagnostic
from .worker import pool_initializer, try_password

log = get_logger("runner")


def compute_worker_count(cfg: AppConfig) -> int:
    """
    Число процессов в пуле: по умолчанию все **логические** CPU (os.cpu_count) минус резерв.

    На процесс приходится одна параллельная проверка пароля в UnRAR; планировщик ОС разносит
    процессы по ядрам/гиперпотокам. Явный max_workers ограничивает сверху.
    """
    cpu = os.cpu_count() or 2
    n = max(1, cpu - max(0, cfg.reserve_cpu_cores))
    if cfg.max_workers is not None:
        n = min(n, max(1, cfg.max_workers))
    return n


def log_parallelism_report(cfg: AppConfig, workers: int) -> None:
    """
    Поясняет в лог, сколько CPU видит Python и сколько воркеров реально запущено.

    GPU/NPU в конфиге не включают ускорение проверки RAR в текущей версии — только предупреждение.
    """
    logical = os.cpu_count() or 2
    mp_ctx = multiprocessing.get_context("spawn")
    log.info(
        "Параллелизм: логических процессоров os.cpu_count()=%s, резерв ядер в конфиге=%s, "
        "max_workers в конфиге=%s → процессов в пуле=%s (контекст multiprocessing: %s).",
        logical,
        cfg.reserve_cpu_cores,
        cfg.max_workers if cfg.max_workers is not None else "не задан (берём все минус резерв)",
        workers,
        mp_ctx.get_start_method(),
    )
    log.info(
        "Нагрузка идёт на CPU: каждый воркер — отдельный процесс с вызовом UnRAR/rarfile; "
        "это типичный способ задействовать все доступные логические ядра под перебор."
    )
    if cfg.use_gpu or cfg.use_neural_accelerator:
        log.warning(
            "В Config.json parallelism.use_gpu=%s, use_neural_accelerator=%s. "
            "Проверка пароля через rarfile/UnRAR выполняется только на CPU; "
            "видеокарта и нейроускорители (NPU, Apple Neural Engine и т.п.) этим путём не используются. "
            "GPU-взлом RAR — отдельные инструменты (например hashcat + OpenCL/CUDA). "
            "Флаги зарезервированы и не меняют код проверки.",
            cfg.use_gpu,
            cfg.use_neural_accelerator,
        )


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


def _cleanup_pool_and_children(pool: Pool | None, force_terminate: bool) -> None:
    """
    Закрывает пул процессов и при необходимости добивает зависшие воркеры.

    При остановке по Esc/Ctrl+C (force_terminate=True) вызывается terminate(), чтобы
    не ждать завершения текущих задач в UnRAR. Затем проверяются active_children().
    """
    if pool is not None:
        try:
            if force_terminate:
                log.info("Завершение пула: принудительная остановка воркеров (terminate).")
                pool.terminate()
            else:
                pool.close()
            pool.join()
        except Exception as exc:  # noqa: BLE001 — хотим гарантированно освободить процессы
            log.warning("При закрытии пула: %s; повторный terminate.", exc)
            try:
                pool.terminate()
                pool.join()
            except Exception:
                pass

    # Дочерние процессы текущего процесса (в т.ч. «хвосты» после сбоя пула)
    children = multiprocessing.active_children()
    if children:
        log.warning("Обнаружены активные дочерние процессы (%d), завершаем.", len(children))
        for ch in children:
            try:
                ch.terminate()
            except Exception:
                pass
        time.sleep(0.2)
        for ch in list(multiprocessing.active_children()):
            try:
                ch.join(timeout=5)
            except Exception:
                pass
        still = multiprocessing.active_children()
        if still:
            log.warning("После terminate остаётся %d дочерних процессов (возможны системные трекеры).", len(still))


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
        # Чтобы не писать миллионы одинаковых предупреждений об одной и той же ошибке проверки
        self._reported_check_error_notes: set[str] = set()
        # Активный пул (для повторного Ctrl+C — немедленный terminate)
        self._active_pool: Pool | None = None
        self._esc: Any = None

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
        if self.stop_event.is_set():
            log.info("Повторное прерывание (Ctrl+C): немедленный terminate пула воркеров.")
            p = self._active_pool
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass
            return
        self.stop_event.set()
        log.info("Получен сигнал прерывания; завершаем текущий пакет и останавливаем воркеры…")

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
        log_parallelism_report(self.cfg, workers)

        signal.signal(signal.SIGINT, self._handle_sigint)
        self._esc = _start_esc_listener(self.stop_event, self.cfg.esc_key_enabled)

        ctx = get_context("spawn")
        payload = self._payload(archive_path)
        phases = build_phase_plan(self.cfg)

        conn = self._conn_factory()
        pool: Pool | None = None
        exit_code = 1
        try:
            pool = ctx.Pool(
                processes=workers,
                initializer=pool_initializer,
                initargs=(payload,),
            )
            self._active_pool = pool

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
                    # Исключаем пары (архив, пароль), уже записанные в SQLite — повторно не проверяем
                    untested = filter_untested_passwords(conn, archive_key, batch)
                    if not untested:
                        continue
                    try:
                        results = self._run_pool_batch(pool, untested)
                    except Exception as exc:  # noqa: BLE001 — пул могли убить по второму Ctrl+C
                        if self.stop_event.is_set():
                            log.warning("Пакет проверки прерван (остановка): %s", type(exc).__name__)
                            break
                        raise
                    rows: list[AttemptRow] = []
                    now = utc_now_iso()
                    for pwd, outcome, note in results:
                        r = outcome if outcome in ("ok", "fail", "error") else "error"
                        rows.append(AttemptRow(archive_key, pwd, r, now))
                        # Диагностический файл: одна строка на новый код ошибки, без потока по каждой попытке
                        if outcome == "error" and note and note not in self._reported_check_error_notes:
                            self._reported_check_error_notes.add(note)
                            log_diagnostic(
                                log,
                                logging.WARNING,
                                f"Ошибка проверки пароля (первое появление кода): {note}",
                                class_name="BruteForceRunner",
                                func_name="run",
                            )
                    insert_attempts(conn, rows)
                    for pwd, outcome, _note in results:
                        if outcome == "ok":
                            log.info("Пароль найден: %s", pwd)
                            print(f"\nУСПЕХ. Пароль: {pwd}\n", flush=True)
                            exit_code = 0
                            return exit_code
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
        finally:
            force = self.stop_event.is_set()
            _cleanup_pool_and_children(pool, force_terminate=force)
            self._active_pool = None
            esc = getattr(self, "_esc", None)
            if esc is not None:
                try:
                    esc.stop()
                except Exception:
                    pass
            conn.close()

        return exit_code
