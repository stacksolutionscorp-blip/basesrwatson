"""Dependências comuns das rotas."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from cnpj_core import clean, is_valid
from fastapi import Depends, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader

from cnpj_api.auth import Cliente, require_client
from cnpj_api.search import Filtros

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Sua API key")


async def cliente(request: Request, _key: str | None = Security(_api_key_header)) -> Cliente:
    return await require_client(request)


ClienteDep = Annotated[Cliente, Depends(cliente)]


def valid_cnpj(cnpj: str) -> str:
    """Normaliza e valida o dígito verificador antes de ir ao banco (422 se inválido)."""
    c = clean(cnpj)
    if not is_valid(c):
        raise HTTPException(422, f"CNPJ inválido: {cnpj}")
    return c


def filtros(
    q: Annotated[str | None, Query(description="Razão social, nome fantasia ou CNPJ")] = None,
    cnae: Annotated[list[int], Query(description="CNAE (principal ou secundário); repita para vários")] = [],  # noqa: B006
    somente_cnae_principal: bool = False,
    uf: Annotated[list[str], Query(description="UF; repita para várias")] = [],  # noqa: B006
    municipio: Annotated[list[int], Query(description="Código SIAFI (Receita)")] = [],  # noqa: B006
    municipio_ibge: Annotated[list[int], Query(description="Código IBGE")] = [],  # noqa: B006
    lat: float | None = None,
    lng: float | None = None,
    raio_km: Annotated[float | None, Query(description="Raio em km a partir de lat/lng (máx. 200)")] = None,
    situacao: Annotated[list[int], Query(description="1 nula, 2 ativa, 3 suspensa, 4 inapta, 8 baixada")] = [],  # noqa: B006
    porte: Annotated[list[int], Query(description="0 não informado, 1 ME, 3 EPP, 5 demais")] = [],  # noqa: B006
    capital_min: Decimal | None = None,
    capital_max: Decimal | None = None,
    abertura_de: date | None = None,
    abertura_ate: date | None = None,
    simples: bool | None = None,
    mei: bool | None = None,
    matriz: bool | None = None,
) -> Filtros:
    f = Filtros(q=q, cnae=cnae, somente_cnae_principal=somente_cnae_principal, uf=uf, municipio=municipio,
                municipio_ibge=municipio_ibge, lat=lat, lng=lng, raio_km=raio_km, situacao=situacao, porte=porte,
                capital_min=capital_min, capital_max=capital_max, abertura_de=abertura_de,
                abertura_ate=abertura_ate, simples=simples, mei=mei, matriz=matriz)  # fmt: skip
    try:
        f.validate()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return f


FiltrosDep = Annotated[Filtros, Depends(filtros)]
