# Дочерний процесс: проверка одного пароля (инициализация один раз на воркер).

from __future__ import annotations

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


def try_password(password: str) -> Tuple[str, CheckOutcome, str]:
    """
    Проверяет один пароль.

    Возвращает (пароль, результат ok|fail|error, пояснение).
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
        return password, outcome, note
    unrar_tool = str(_W.get("unrar_tool") or "") or None
    outcome, note = check_password_rarfile(archive, password, unrar_tool)
    return password, outcome, note
