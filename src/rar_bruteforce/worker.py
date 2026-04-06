# Дочерний процесс: проверка одного пароля (инициализация один раз на воркер).

from __future__ import annotations

import multiprocessing
import os
import threading
from pathlib import Path
from typing import Any, Dict, Tuple

from .checker import CheckOutcome, check_password_rarfile, check_password_unrar_cli

# Глобальное состояние процесса-воркера (заполняется в initializer пула)
_W: Dict[str, Any] = {}


def pool_initializer(payload: Dict[str, Any]) -> None:
    """
    Вызывается один раз при старте каждого процесса в пуле.

    payload содержит пути и параметры проверки (сериализуемый dict).
    """
    global _W
    _W = dict(payload)


def collect_execution_meta() -> Dict[str, Any]:
    """
    Метаданные после проверки пароля: процесс, поток, логический CPU (если доступен).

    Проверка RAR идёт на CPU; GPU/NPU не задействуются — поля для единообразия в логе.
    """
    meta: Dict[str, Any] = {
        "pid": os.getpid(),
        "process_name": multiprocessing.current_process().name,
        "thread_name": threading.current_thread().name,
        "compute_backend": "CPU",
        "gpu_npu_used": False,
        "cpu_num": None,
    }
    try:
        import psutil

        meta["cpu_num"] = psutil.Process().cpu_num()
    except Exception:
        pass
    return meta


def try_password(password: str) -> Tuple[str, CheckOutcome, str, Dict[str, Any]]:
    """
    Проверяет один пароль.

    Возвращает (пароль, результат ok|fail|error, пояснение, метаданные размещения воркера).
    """
    archive = Path(_W["archive_path"])
    mode = str(_W["checker_mode"])
    if mode == "unrar":
        outcome, note = check_password_unrar_cli(
            archive,
            password,
            str(_W["unrar_path"]),
            str(_W["unrar_command"]),
            int(_W["unrar_timeout_sec"]),
        )
    else:
        unrar_tool = str(_W.get("unrar_tool") or "") or None
        outcome, note = check_password_rarfile(archive, password, unrar_tool)
    meta = collect_execution_meta()
    return password, outcome, note, meta
