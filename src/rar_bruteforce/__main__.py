# Точка входа: python -m rar_bruteforce (из корня проекта с PYTHONPATH=src).

from __future__ import annotations

import sys
from pathlib import Path

from .config_loader import load_config
from .db_sqlite import connect_db, init_schema
from .logging_setup import setup_logging
from .runner import BruteForceRunner


def _resolve_project_root() -> tuple[Path, Path]:
    """Ищет каталог с Config.json: сначала относительно исходника, затем текущая рабочая папка."""
    here = Path(__file__).resolve()
    candidates = [here.parents[2], here.parents[1], Path.cwd()]
    for root in candidates:
        cfg = root / "Config.json"
        if cfg.is_file():
            return root.resolve(), cfg
    root = Path.cwd().resolve()
    return root, root / "Config.json"


def main() -> None:
    """Определяет корень проекта, поднимает логи и запускает перебор."""
    project_root, cfg_path = _resolve_project_root()
    if not cfg_path.is_file():
        print("Не найден Config.json. Запускайте из корня проекта или положите Config.json в текущий каталог.")
        raise SystemExit(2)

    logger, _info_p, _dbg_p = setup_logging(project_root, topic="bruteforce")
    logger.info("Запуск перебора пароля RAR; корень проекта: %s", project_root)
    try:
        import psutil  # noqa: F401

        logger.info(
            "Пакет psutil доступен: в логе и консоли можно выводить размещение воркеров по логическим CPU "
            "(runtime.log_worker_placement_* в Config.json)."
        )
    except ImportError:
        logger.info(
            "Установите psutil (pip install psutil), чтобы в логе показывались номера логических CPU для каждого воркера."
        )

    cfg = load_config(project_root, cfg_path)

    db_file = (cfg.dir_out / cfg.db_filename).resolve()

    def open_conn():
        c = connect_db(db_file, journal_mode=cfg.db_journal_mode)
        init_schema(c)
        return c

    runner = BruteForceRunner(cfg, conn_factory=open_conn)
    code = runner.run()
    sys.exit(code)


if __name__ == "__main__":
    main()
