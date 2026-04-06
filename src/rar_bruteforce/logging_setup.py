# Настройка логирования в каталог log с шаблоном имён и форматом DEBUG.

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class _DebugContextFilter(logging.Filter):
    """Добавляет в запись поля class_name и func_name для формата DEBUG."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Имя логгера часто совпадает с модулем; для класса берём из extra
        record.class_name = getattr(record, "class_name", "-")
        record.func_name = record.funcName
        return True


class _OnlyDebugFilter(logging.Filter):
    """В файл DEBUG попадают только строки уровня DEBUG (строгий формат сообщения)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.DEBUG


def setup_logging(project_root: Path, topic: str = "bruteforce") -> tuple[logging.Logger, Path, Path]:
    """
    Создаёт каталог log, два файла INFO и DEBUG, возвращает корневой логгер проекта.

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
    root.setLevel(logging.DEBUG)

    fmt_info = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt_debug = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(message)s [class: %(class_name)s | def: %(func_name)s]",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh_info = logging.FileHandler(info_path, encoding="utf-8")
    fh_info.setLevel(logging.INFO)
    fh_info.setFormatter(fmt_info)

    fh_debug = logging.FileHandler(debug_path, encoding="utf-8")
    fh_debug.setLevel(logging.DEBUG)
    fh_debug.addFilter(_OnlyDebugFilter())
    fh_debug.addFilter(_DebugContextFilter())
    fh_debug.setFormatter(fmt_debug)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt_info)

    root.addHandler(fh_info)
    root.addHandler(fh_debug)
    root.addHandler(sh)

    return root, info_path, debug_path


def log_debug(logger: logging.Logger, message: str, class_name: str, func_name: str) -> None:
    """Пишет DEBUG с обязательными полями class/def через extra."""
    logger.debug(message, extra={"class_name": class_name, "func_name": func_name})


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Возвращает дочерний логгер пакета."""
    if name:
        return logging.getLogger(f"rar_bruteforce.{name}")
    return logging.getLogger("rar_bruteforce")
