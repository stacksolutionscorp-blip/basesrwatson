"""Score de risco simples e explicável (0 = menor risco, 100 = maior).

Cada fator soma pontos e aparece na resposta, para quem integra entender o motivo.
"""

from datetime import date
from decimal import Decimal

SITUACAO_PONTOS = {1: 70, 3: 50, 4: 50, 8: 70}  # nula, suspensa, inapta, baixada


def score(
    *,
    situacao: int | None,
    data_inicio: date | None,
    capital_social: Decimal | float | None,
    data_situacao: date | None,
    situacao_especial: str | None,
    datas_entrada_socios: list[date | None],
    mei: bool | None,
    hoje: date,
) -> dict:
    fatores: list[tuple[str, int]] = []

    if situacao in SITUACAO_PONTOS:
        fatores.append(("situacao cadastral não ativa", SITUACAO_PONTOS[situacao]))
    elif situacao is None:
        fatores.append(("situação cadastral desconhecida", 30))

    if situacao_especial:
        fatores.append((f"situação especial: {situacao_especial}", 15))

    if data_inicio is None:
        fatores.append(("data de abertura desconhecida", 10))
    else:
        idade = (hoje - data_inicio).days / 365.25
        if idade < 1:
            fatores.append(("empresa com menos de 1 ano", 20))
        elif idade < 3:
            fatores.append(("empresa com menos de 3 anos", 10))

    if not mei and (capital_social is None or capital_social < 1000):
        fatores.append(("capital social abaixo de R$ 1.000", 10))

    if situacao == 2 and data_situacao and (hoje - data_situacao).days < 180 and data_inicio != data_situacao:
        fatores.append(("mudança de situação cadastral nos últimos 6 meses", 10))

    if any(d and (hoje - d).days < 180 for d in datas_entrada_socios):
        fatores.append(("entrada de sócio nos últimos 6 meses", 10))

    total = min(100, sum(p for _, p in fatores))
    nivel = "baixo" if total < 30 else "medio" if total < 60 else "alto"
    return {"score": total, "nivel": nivel, "fatores": [{"fator": f, "pontos": p} for f, p in fatores]}
