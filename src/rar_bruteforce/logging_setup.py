# Настройка логирования в каталог log с шаблоном имён и отдельным файлом диагностики.

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class _DebugContextFilter(logging.Filter):
    """Добавляет в запись поля class_name и func_name (для расширенного формата в файле диагностики)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.class_name = getattr(record, "class_name", "-")
        record.func_name = record.funcName
        return True


class _MinLevelFilter(logging.Filter):
    """Пропускает записи не ниже заданного уровня (для файла только WARNING+)."""

    def __init__(self, min_level: int) -> None:
        super().__init__()
        self._min = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self._min


def setup_logging(project_root: Path, topic: str = "bruteforce") -> tuple[logging.Logger, Path, Path]:
    """
    Создаёт каталог log.

    - INFO-файл и консоль: уровень INFO и выше (основной ход работы).
    - Файл DEBUG_(тема)_...: по требованию ТЗ имя сохранено; внутрь пишутся только
      WARNING, ERROR, CRITICAL (ошибки, предупреждения, системные сбои) — без потока
      записей о каждой проверке пароля.

    Имя файла: Уровень_(тема)_годмесяцдень_час.log
    """
    log_dir = project_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H")
    info_path = log_dir / f"INFO_({topic})_{stamp}.log"
    debug_path = log_dir / f"DEBUG_({topic})_{stamp}.log"

    root = logging.getLogger("rar_bruteforce")
    root.handlers.clear()
    # Общий уровень пакета — INFO: отладочный шум сторонних библиотек и «каждый пароль» не идёт в лог
    root.setLevel(logging.INFO)

    fmt_info = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt_diagnostic = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(message)s [class: %(class_name)s | def: %(func_name)s]",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh_info = logging.FileHandler(info_path, encoding="utf-8")
    fh_info.setLevel(logging.INFO)
    fh_info.setFormatter(fmt_info)

    # Файл DEBUG_*: только предупреждения и ошибки (не уровень DEBUG и не каждая попытка пароля)
    fh_diagnostic = logging.FileHandler(debug_path, encoding="utf-8")
    fh_diagnostic.setLevel(logging.WARNING)
    fh_diagnostic.addFilter(_MinLevelFilter(logging.WARNING))
    fh_diagnostic.addFilter(_DebugContextFilter())
    fh_diagnostic.setFormatter(fmt_diagnostic)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt_info)

    root.addHandler(fh_info)
    root.addHandler(fh_diagnostic)
    root.addHandler(sh)

    # Сторонние модули не засоряют наши файлы отладкой
    logging.getLogger("rarfile").setLevel(logging.WARNING)

    return root, info_path, debug_path


def log_diagnostic(
    logger: logging.Logger,
    level: int,
    message: str,
    class_name: str,
    func_name: str,
) -> None:
    """Запись в файл диагностики (WARNING/ERROR) с полями class/def в формате строки."""
    logger.log(level, message, extra={"class_name": class_name, "func_name": func_name})


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Возвращает дочерний логгер пакета."""
    if name:
        return logging.getLogger(f"rar_bruteforce.{name}")
    return logging.getLogger("rar_bruteforce")
