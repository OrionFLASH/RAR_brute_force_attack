# Генераторы кандидатов паролей по фазам: числа, словарь, гибрид.

from __future__ import annotations

import itertools
from typing import Iterable, Iterator

from .config_loader import AppConfig, WordlistSpec


def _length_ok(cfg: AppConfig, s: str) -> bool:
    n = len(s)
    return cfg.pwd_min_len <= n <= cfg.pwd_max_len


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
    Фаза «словарь» для одного файла: построчное чтение, фильтр по длине пароля.

    Параметры строки (кодировка, макс. длина строки в файле) берутся из spec.
    """
    path = spec.path
    if not path.is_file():
        return
    enc = spec.encoding
    prefix = spec.skip_lines_starting_with
    max_len_line = spec.max_line_length
    with open(path, encoding=enc, errors="ignore") as f:
        for line in f:
            s = line.rstrip("\r\n")
            if prefix and s.startswith(prefix):
                continue
            if len(s) > max_len_line:
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
    Фаза «гибрид» для одного словаря: слово + цифры/спецсимволы и комбинации.

    Файл читается потоково повторно для каждого spec (не загружает весь словарь в RAM).
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

    def variants_for_word(word: str) -> Iterable[str]:
        # Суффиксы из цифр (включая пустой при min_len=0)
        dmin = cfg.hybrid_suffix_digits_min_len
        dmax = cfg.hybrid_suffix_digits_max_len
        for ds in _iter_digit_strings(dmin, dmax):
            cand = word + ds
            if _length_ok(cfg, cand):
                yield cand
        # Префиксы из цифр
        pmax = cfg.hybrid_prefix_digits_max_len
        if pmax > 0:
            for ds in _iter_digit_strings(1, pmax):
                cand = ds + word
                if _length_ok(cfg, cand):
                    yield cand
        # Слово + спецсимвол
        for sp in specials:
            cand = word + sp
            if _length_ok(cfg, cand):
                yield cand
            cand2 = sp + word
            if _length_ok(cfg, cand2):
                yield cand2
        # Слово + спец + одна цифра
        if cfg.hybrid_combine_word_special_digit:
            for sp in specials:
                for ch in "0123456789":
                    cand = word + sp + ch
                    if _length_ok(cfg, cand):
                        yield cand

    with open(path, encoding=enc, errors="ignore") as f:
        for line in f:
            s = line.rstrip("\r\n")
            if prefix and s.startswith(prefix):
                continue
            if len(s) > max_len_line:
                continue
            if not s:
                continue
            yield from variants_for_word(s)
