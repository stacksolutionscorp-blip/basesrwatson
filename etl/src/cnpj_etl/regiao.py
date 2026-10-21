"""Carga regional: só os estabelecimentos de uma região (e, opcionalmente, só os ativos).

Configuração (combináveis; vazias = Brasil inteiro):
- ``ETL_CENTRO="-23.1857,-46.8978"`` + ``ETL_RAIO_KM=60`` → municípios cujo centro está no raio
- ``ETL_UFS="SP,MG"`` → estados inteiros
- ``ETL_MUNICIPIOS_IBGE="3525904,3509502"`` → municípios específicos
- ``ETL_SOMENTE_ATIVAS=1`` → descarta empresas baixadas, inaptas, suspensas e nulas

Empresas, sócios e Simples são filtrados pela raiz (CNPJ básico) dos estabelecimentos mantidos,
então a base fica coerente (o perfil de uma filial da região traz a empresa e os sócios).
"""

from dataclasses import dataclass

import polars as pl
import psycopg

ATIVA = 2


@dataclass
class Regiao:
    municipios: set[int] | None  # códigos SIAFI (os da Receita); None = sem filtro de local
    somente_ativas: bool

    @property
    def ativa(self) -> bool:
        return self.municipios is not None or self.somente_ativas

    def describe(self) -> str:
        partes = []
        if self.municipios is not None:
            partes.append(f"{len(self.municipios)} municípios")
        if self.somente_ativas:
            partes.append("só ativas")
        return ", ".join(partes) or "Brasil inteiro"

    def filter_estabelecimentos(self, df: pl.DataFrame) -> pl.DataFrame:
        cond = pl.lit(True)
        if self.municipios is not None:
            cond &= pl.col("municipio").is_in(list(self.municipios))
        if self.somente_ativas:
            cond &= pl.col("situacao") == ATIVA
        return df.filter(cond)


def _parse_centro(value: str) -> tuple[float, float]:
    try:
        lat, lng = (float(x) for x in value.split(","))
    except ValueError as exc:
        raise ValueError(f"ETL_CENTRO inválido: {value!r} (use 'lat,lng', ex.: -23.1857,-46.8978)") from exc
    return lat, lng


def build(
    conn: psycopg.Connection,
    centro: str | None,
    raio_km: float | None,
    ufs: list[str],
    municipios_ibge: list[int],
    somente_ativas: bool,
) -> Regiao:
    if not (centro or ufs or municipios_ibge):
        return Regiao(None, somente_ativas)
    if bool(centro) != bool(raio_km):
        raise ValueError("ETL_CENTRO e ETL_RAIO_KM devem ser informados juntos")
    if not conn.execute("SELECT EXISTS (SELECT 1 FROM geo.municipio_ibge)").fetchone()[0]:
        raise RuntimeError("geo.municipio_ibge vazia: rode `cnpj-etl geo municipios` antes da carga regional")
    conds, params = [], []
    if centro:
        lat, lng = _parse_centro(centro)
        conds.append(
            "ST_DWithin(ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,"
            " ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)"
        )
        params += [lng, lat, raio_km * 1000]
    if ufs:
        conds.append("uf = ANY(%s)")
        params.append([u.strip().upper() for u in ufs])
    if municipios_ibge:
        conds.append("codigo_ibge = ANY(%s)")
        params.append(municipios_ibge)
    rows = conn.execute(f"SELECT codigo_siafi FROM geo.municipio_ibge WHERE {' OR '.join(conds)}", params).fetchall()
    if not rows:
        raise ValueError("o filtro regional não corresponde a nenhum município")
    return Regiao({r[0] for r in rows}, somente_ativas)
