# Загрузка и валидация Config.json (пути относительно корня проекта).

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class WordlistSpec:
    """
    Один словарь: путь, метка для логов и параметры чтения строк.

    Порядок записей в конфиге задаёт порядок фаз от простого к сложному.
    """

    path: Path
    label: str
    encoding: str
    max_line_length: int
    skip_lines_starting_with: str


@dataclass
class AppConfig:
    """Снимок настроек приложения после чтения JSON и окружения."""

    project_root: Path
    dir_in: Path
    dir_out: Path
    archive_file: str
    db_filename: str
    db_journal_mode: str
    pwd_min_len: int
    pwd_max_len: int
    charset: str
    numeric_charset: str
    wordlists: list[WordlistSpec]
    hybrid_enabled: bool
    hybrid_suffix_digits_min_len: int
    hybrid_suffix_digits_max_len: int
    hybrid_suffix_specials: list[str]
    hybrid_prefix_digits_max_len: int
    hybrid_combine_word_special_digit: bool
    checker_mode: str
    unrar_path: str
    unrar_command: str
    unrar_timeout_sec: int
    rarfile_open_timeout_sec: int
    max_workers: Optional[int]
    reserve_cpu_cores: int
    batch_size: int
    # Зарезервировано: UnRAR/rarfile не используют GPU/NPU; при true — только предупреждение в логе
    use_gpu: bool
    use_neural_accelerator: bool
    esc_key_enabled: bool
    progress_log_every_sec: int
    # Лог: на каких процессах/CPU отработал пакет (см. placement, нужен psutil для номера CPU)
    log_worker_placement_every_batch: bool
    log_worker_placement_on_progress: bool


def _as_path(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def _parse_wordlists_block(
    project_root: Path,
    raw: dict[str, Any],
) -> list[WordlistSpec]:
    """
    Собирает упорядоченный список словарей.

    Поддерживается блок `wordlists` с `defaults` и `entries`.
    Устаревший ключ `wordlist` (один файл) превращается в список из одного элемента.
    """
    if "wordlists" in raw:
        block = raw["wordlists"] or {}
        defaults = block.get("defaults") or {}
        enc_def = str(defaults.get("encoding", "utf-8"))
        max_len_def = int(defaults.get("max_line_length", 128))
        skip_def = str(defaults.get("skip_lines_starting_with", "#"))
        entries = block.get("entries") or []
        out: list[WordlistSpec] = []
        for i, item in enumerate(entries):
            if isinstance(item, str):
                rel = item
                label = Path(rel).stem or f"wl{i}"
                enc = enc_def
                max_line = max_len_def
                skip = skip_def
            else:
                rel = str(item["path"])
                label = str(item.get("label") or Path(rel).stem or f"wl{i}")
                enc = str(item.get("encoding", enc_def))
                max_line = int(item.get("max_line_length", max_len_def))
                skip = str(item.get("skip_lines_starting_with", skip_def))
            out.append(
                WordlistSpec(
                    path=_as_path(project_root, rel),
                    label=label,
                    encoding=enc,
                    max_line_length=max_line,
                    skip_lines_starting_with=skip,
                )
            )
        return out

    # Обратная совместимость: один ключ wordlist
    wl = raw.get("wordlist") or {}
    path = _as_path(project_root, str(wl["path"]))
    return [
        WordlistSpec(
            path=path,
            label=path.stem or "default",
            encoding=str(wl.get("encoding", "utf-8")),
            max_line_length=int(wl.get("max_line_length", 128)),
            skip_lines_starting_with=str(wl.get("skip_lines_starting_with", "#")),
        )
    ]


def load_config(project_root: Path, config_path: Optional[Path] = None) -> AppConfig:
    """
    Читает Config.json, подмешивает .env (UNRAR_PATH и др.).

    Корень проекта — каталог, где лежит Config.json (если не передан явно).
    """
    load_dotenv(project_root / ".env", override=False)
    cfg_file = config_path or (project_root / "Config.json")
    with open(cfg_file, encoding="utf-8") as f:
        raw: dict[str, Any] = json.load(f)

    d_in = _as_path(project_root, raw["directories"]["in"])
    d_out = _as_path(project_root, raw["directories"]["out"])
    d_out.mkdir(parents=True, exist_ok=True)

    wordlists = _parse_wordlists_block(project_root, raw)

    unrar_path = (raw.get("checker") or {}).get("unrar_path") or ""
    unrar_path = os.environ.get("UNRAR_PATH", unrar_path)

    par = raw.get("parallelism") or {}
    max_workers = par.get("max_workers")
    if max_workers is not None:
        max_workers = int(max_workers)

    hybrid = raw.get("hybrid") or {}
    rt = raw.get("runtime") or {}

    return AppConfig(
        project_root=project_root.resolve(),
        dir_in=d_in,
        dir_out=d_out,
        archive_file=str(raw["archive_file"]),
        db_filename=str(raw["database"]["filename"]),
        db_journal_mode=str(raw["database"].get("journal_mode", "WAL")),
        pwd_min_len=int(raw["password"]["min_length"]),
        pwd_max_len=int(raw["password"]["max_length"]),
        charset=str(raw["password"]["charset"]),
        numeric_charset=str(raw["password"]["numeric_charset"]),
        wordlists=wordlists,
        hybrid_enabled=bool(hybrid.get("enabled", True)),
        hybrid_suffix_digits_min_len=int(hybrid.get("suffix_digits_min_len", 0)),
        hybrid_suffix_digits_max_len=int(hybrid.get("suffix_digits_max_len", 2)),
        hybrid_suffix_specials=list(hybrid.get("suffix_specials", [])),
        hybrid_prefix_digits_max_len=int(hybrid.get("prefix_digits_max_len", 2)),
        hybrid_combine_word_special_digit=bool(hybrid.get("combine_word_plus_special_plus_digit", True)),
        checker_mode=str(raw["checker"]["mode"]).lower(),
        unrar_path=str(unrar_path),
        unrar_command=str(raw["checker"].get("unrar_command", "t")),
        unrar_timeout_sec=int(raw["checker"].get("unrar_timeout_sec", 120)),
        rarfile_open_timeout_sec=int(raw["checker"].get("rarfile_open_timeout_sec", 120)),
        max_workers=max_workers,
        reserve_cpu_cores=int(par.get("reserve_cpu_cores", 1)),
        batch_size=max(1, int(par.get("batch_size", 32))),
        use_gpu=bool(par.get("use_gpu", False)),
        use_neural_accelerator=bool(par.get("use_neural_accelerator", False)),
        esc_key_enabled=bool(rt.get("esc_key_enabled", True)),
        progress_log_every_sec=max(5, int(rt.get("progress_log_every_sec", 30))),
        log_worker_placement_every_batch=bool(rt.get("log_worker_placement_every_batch", False)),
        log_worker_placement_on_progress=bool(rt.get("log_worker_placement_on_progress", True)),
    )
