# Генераторы кандидатов паролей по фазам: числа, словарь, гибрид.

from __future__ import annotations

import itertools
from typing import Iterable, Iterator

from .config_loader import AppConfig, WordlistSpec


def _length_ok(cfg: AppConfig, s: str) -> bool:
    """Пароль подходит по длине: от min_length до max_length включительно."""
    n = len(s)
    return cfg.pwd_min_len <= n <= cfg.pwd_max_len


def _effective_suffix_digit_lengths(cfg: AppConfig, lw: int) -> tuple[int, int] | None:
    """
    Диапазон длин суффикса из цифр для склейки word+ds (длина слова lw).

    Учитываются hybrid_suffix_digits_* и ограничения пароля min/max.
    Возвращает None, если ни один суффикс из цифр не может дать допустимую длину.
    """
    rem = cfg.pwd_max_len - lw
    if rem < 0:
        return None
    need_digits = max(0, cfg.pwd_min_len - lw)
    d_lo = cfg.hybrid_suffix_digits_min_len
    d_hi = cfg.hybrid_suffix_digits_max_len
    eff_lo = max(d_lo, need_digits)
    eff_hi = min(d_hi, rem)
    if eff_lo > eff_hi:
        return None
    return (eff_lo, eff_hi)


def _effective_prefix_digit_lengths(cfg: AppConfig, lw: int) -> tuple[int, int] | None:
    """
    Диапазон длин префикса из цифр для ds+word.

    None — нет ни одного допустимого префикса (с учётом min/max пароля).
    """
    rem = cfg.pwd_max_len - lw
    if rem < 1:
        return None
    need_total_digits = max(0, cfg.pwd_min_len - lw)
    eff_lo = max(1, need_total_digits)
    eff_hi = min(cfg.hybrid_prefix_digits_max_len, rem)
    if eff_lo > eff_hi:
        return None
    return (eff_lo, eff_hi)


def iter_numeric_passwords(cfg: AppConfig) -> Iterator[str]:
    """
    Фаза 1: все комбинации только из numeric_charset, длины от min до max.

    Внимание: при max_length=8 это до 10^8 вариантов для цифр — перебор идёт потоково.
    """
    chars = cfg.numeric_charset
    if not chars:
        return
    for length in range(cfg.pwd_min_len, cfg.pwd_max_len + 1):
        for tup in itertools.product(chars, repeat=length):
            yield "".join(tup)


def iter_dictionary_passwords(cfg: AppConfig, spec: WordlistSpec) -> Iterator[str]:
    """
    Фаза «словарь»: только строки, у которых длина пароля в [min_length, max_length].

    Строки длиннее max_length (и короче min_length) не перебираются — в UnRAR не уходят.
    """
    path = spec.path
    if not path.is_file():
        return
    enc = spec.encoding
    prefix = spec.skip_lines_starting_with
    max_len_line = spec.max_line_length
    # Не читаем как пароль строки заведомо длиннее лимита пароля
    cap_line = min(max_len_line, cfg.pwd_max_len)
    with open(path, encoding=enc, errors="ignore") as f:
        for line in f:
            s = line.rstrip("\r\n")
            if prefix and s.startswith(prefix):
                continue
            if len(s) > cap_line:
                continue
            if not _length_ok(cfg, s):
                continue
            yield s


def _iter_digit_strings(min_len: int, max_len: int) -> Iterator[str]:
    """
    Строки из цифр длиной от min_len до max_len (включительно).

    Для длины L перебираются все значения от 0 до 10^L-1 с дополнением нулями слева (00…09 для L=2).
    """
    if max_len < min_len or min_len < 0:
        return
    for length in range(min_len, max_len + 1):
        if length == 0:
            yield ""
            continue
        for n in range(0, 10**length):
            yield str(n).zfill(length)


def iter_hybrid_passwords(cfg: AppConfig, spec: WordlistSpec) -> Iterator[str]:
    """
    Фаза «гибрид»: слово из словаря + цифры/спецсимволы.

    Все кандидаты заранее укладываются в [min_length, max_length]; лишние комбинации не генерируются.
    Слова длиннее max_length пропускаются — к ним нельзя добавить суффикс без превышения лимита.
    """
    if not cfg.hybrid_enabled:
        return
    path = spec.path
    if not path.is_file():
        return

    specials = cfg.hybrid_suffix_specials or []
    enc = spec.encoding
    prefix = spec.skip_lines_starting_with
    max_len_line = spec.max_line_length
    cap_line = min(max_len_line, cfg.pwd_max_len)

    def variants_for_word(word: str) -> Iterable[str]:
        lw = len(word)
        # Полное слово длиннее max_length — ни word+suffix, ни prefix+word не впишутся в лимит
        if lw > cfg.pwd_max_len:
            return
        rng = _effective_suffix_digit_lengths(cfg, lw)
        if rng is not None:
            eff_lo, eff_hi = rng
            for ds in _iter_digit_strings(eff_lo, eff_hi):
                cand = word + ds
                if _length_ok(cfg, cand):
                    yield cand
        pr = _effective_prefix_digit_lengths(cfg, lw)
        if pr is not None:
            eff_lo, eff_hi = pr
            for ds in _iter_digit_strings(eff_lo, eff_hi):
                cand = ds + word
                if _length_ok(cfg, cand):
                    yield cand
        for sp in specials:
            z = len(sp)
            t_w = lw + z
            if cfg.pwd_min_len <= t_w <= cfg.pwd_max_len:
                yield word + sp
            t_p = z + lw
            if cfg.pwd_min_len <= t_p <= cfg.pwd_max_len:
                yield sp + word
        if cfg.hybrid_combine_word_special_digit:
            for sp in specials:
                z = len(sp)
                for ch in "0123456789":
                    t = lw + z + 1
                    if cfg.pwd_min_len <= t <= cfg.pwd_max_len:
                        yield word + sp + ch

    with open(path, encoding=enc, errors="ignore") as f:
        for line in f:
            s = line.rstrip("\r\n")
            if prefix and s.startswith(prefix):
                continue
            if len(s) > cap_line:
                continue
            if not s:
                continue
            yield from variants_for_word(s)
