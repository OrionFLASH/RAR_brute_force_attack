#!/usr/bin/env python3
# Точка входа из корня проекта: python main.py (виртуальное окружение должно быть активировано).

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> Path:
    """Добавляет каталог src в sys.path, чтобы пакет rar_bruteforce импортировался без PYTHONPATH."""
    root = Path(__file__).resolve().parent
    src = root / "src"
    s = str(src)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


if __name__ == "__main__":
    _ensure_src_on_path()
    # Импорт после правки пути
    from rar_bruteforce.__main__ import main

    main()
