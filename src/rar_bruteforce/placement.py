# Сводка по тому, на каких процессах и логических CPU отработал пакет проверок.

from __future__ import annotations

from typing import Any


def summarize_batch_worker_placement(metas: list[dict[str, Any]]) -> str:
    """
    Формирует строку для INFO-лога: какие воркеры пула (pid, имя) на каких CPU виделись.

    Номера CPU — снимок через psutil в момент окончания проверки пароля (ОС может переносить
    процесс между ядрами; для одного pid может быть несколько номеров в пакете).
    """
    if not metas:
        return ""
    # Ключ: (pid, имя процесса) → множество увиденных логических CPU
    acc: dict[tuple[int, str], set[int]] = {}
    for m in metas:
        pid = int(m["pid"])
        pname = str(m["process_name"])
        acc.setdefault((pid, pname), set())
        c = m.get("cpu_num")
        if c is not None:
            acc[(pid, pname)].add(int(c))
    parts: list[str] = []
    for (pid, pname), cpus in sorted(acc.items(), key=lambda x: (x[0][1], x[0][0])):
        if cpus:
            cpu_txt = ",".join(str(n) for n in sorted(cpus))
        else:
            cpu_txt = "?"
        parts.append(f"{pname} pid={pid} CPU[{cpu_txt}]")
    return (
        "Размещение последнего пакета: " + "; ".join(parts) + ". "
        "Вычисления: только CPU (GPU/NPU в этой программе для проверки RAR не используются)."
    )
