"""Validação de CNPJ, incluindo o formato alfanumérico (IN RFB 2.229/2024).

As 12 primeiras posições aceitam [0-9A-Z]; os 2 dígitos verificadores são sempre
numéricos. O valor de cada caractere é ``ord(c) - 48`` (``'0'``→0 … ``'9'``→9,
``'A'``→17 … ``'Z'``→42), o que mantém o cálculo idêntico ao antigo para CNPJs
só com dígitos.
"""

import re

_STRIP = re.compile(r"[^0-9A-Za-z]")
_SHAPE = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_W1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_W2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def clean(value: str) -> str:
    """Remove pontuação e espaços e converte para maiúsculas."""
    return _STRIP.sub("", value or "").upper()


def _digit(chars: str, weights: tuple[int, ...]) -> int:
    total = sum((ord(c) - 48) * w for c, w in zip(chars, weights, strict=True))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def compute_dv(base12: str) -> str:
    """Calcula os 2 dígitos verificadores para as 12 primeiras posições."""
    base12 = clean(base12)
    if not re.fullmatch(r"[0-9A-Z]{12}", base12):
        raise ValueError("base do CNPJ deve ter 12 caracteres [0-9A-Z]")
    d1 = _digit(base12, _W1)
    d2 = _digit(base12 + str(d1), _W2)
    return f"{d1}{d2}"


def is_valid(value: str) -> bool:
    cnpj = clean(value)
    if not _SHAPE.match(cnpj):
        return False
    if len(set(cnpj)) == 1:  # 00000000000000, 11111111111111...
        return False
    return compute_dv(cnpj[:12]) == cnpj[12:]


def format_cnpj(value: str) -> str:
    """Formata como XX.XXX.XXX/XXXX-XX (não valida)."""
    c = clean(value)
    if len(c) != 14:
        raise ValueError("CNPJ deve ter 14 caracteres")
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
