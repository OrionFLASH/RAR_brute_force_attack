# Проверка пароля: режим rarfile (по умолчанию) или вызов unrar.

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal, Tuple

import rarfile

# Тип результата проверки для записи в БД
CheckOutcome = Literal["ok", "fail", "error"]


def check_password_rarfile(archive_path: Path, password: str, unrar_tool: str | None) -> Tuple[CheckOutcome, str]:
    """
    Проверяет пароль через библиотеку rarfile (внутри используется UnRAR).

    Если задан unrar_tool — подставляется в rarfile.UNRAR_TOOL для дочернего процесса.
    Возвращает (исход, короткое сообщение об ошибке при error/fail).
    """
    if unrar_tool:
        rarfile.UNRAR_TOOL = unrar_tool
    try:
        with rarfile.RarFile(str(archive_path)) as rf:
            rf.setpassword(password)
            names = rf.namelist()
            if not names:
                return "fail", "empty_archive"
            # Читаем первый элемент — достаточно для проверки пароля
            rf.read(names[0])
        return "ok", ""
    except rarfile.RarWrongPassword:
        return "fail", "wrong_password"
    except rarfile.BadRarFile:
        return "error", "bad_rar"
    except rarfile.RarCannotExec:
        return "error", "unrar_missing"
    except Exception as exc:  # noqa: BLE001 — хотим залогировать любую аномалию
        return "error", type(exc).__name__


def check_password_unrar_cli(
    archive_path: Path,
    password: str,
    unrar_path: str,
    command: str,
    timeout_sec: int,
) -> Tuple[CheckOutcome, str]:
    """
    Проверяет пароль вызовом unrar (например: unrar t -pПАРОЛЬ архив.rar).

    Код возврата 0 обычно означает успех теста.
    """
    if not unrar_path:
        return "error", "unrar_path_empty"
    # Пароль передаём аргументом списка — без shell
    pwd_arg = f"-p{password}"
    cmd = [unrar_path, command, pwd_arg, str(archive_path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode == 0:
            return "ok", ""
        # Неверный пароль — ненулевой код; детали в stderr не всегда стабильны
        return "fail", f"rc={proc.returncode}"
    except subprocess.TimeoutExpired:
        return "error", "timeout"
    except FileNotFoundError:
        return "error", "unrar_not_found"
    except Exception as exc:  # noqa: BLE001
        return "error", type(exc).__name__
