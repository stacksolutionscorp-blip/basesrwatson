"""Tabela SIAFI (código da Receita) ↔ IBGE com centroides dos municípios.

Fonte padrão: github.com/kelvins/municipios-brasileiros (colunas codigo_ibge,
nome, latitude, longitude, codigo_uf, siafi_id, ...).
"""

import io

import httpx
import polars as pl
import psycopg

from cnpj_etl.db import LIVE, schema_exists

UF_IBGE = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA",
    31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR", 42: "SC", 43: "RS",
    50: "MS", 51: "MT", 52: "GO", 53: "DF",
}  # fmt: skip


def parse(csv_text: str) -> pl.DataFrame:
    df = pl.read_csv(io.StringIO(csv_text), infer_schema_length=0)
    return df.select(
        codigo_siafi=pl.col("siafi_id").cast(pl.Int32),
        codigo_ibge=pl.col("codigo_ibge").cast(pl.Int32),
        nome=pl.col("nome"),
        uf=pl.col("codigo_uf").cast(pl.Int32).replace_strict(UF_IBGE, return_dtype=pl.String),
        lat=pl.col("latitude").cast(pl.Float64),
        lng=pl.col("longitude").cast(pl.Float64),
    ).drop_nulls()


def load(conn: psycopg.Connection, url: str) -> tuple[int, int]:
    """Atualiza geo.municipio_ibge e preenche o centroide onde a base viva não tem geom.

    Devolve (municípios carregados, estabelecimentos atualizados).
    """
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    df = parse(resp.text)
    with conn.transaction():
        conn.execute("TRUNCATE geo.municipio_ibge")
        with conn.cursor().copy(
            "COPY geo.municipio_ibge (codigo_siafi, codigo_ibge, nome, uf, lat, lng) FROM STDIN"
        ) as cp:
            for row in df.iter_rows():
                cp.write_row(row)
    updated = 0
    if schema_exists(conn, LIVE):
        updated = conn.execute(
            f"""UPDATE {LIVE}.estabelecimento e
                SET geom = ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography, geo_precisao = 1
                FROM geo.municipio_ibge m
                WHERE e.geom IS NULL AND m.codigo_siafi = e.municipio"""
        ).rowcount
    return df.height, updated
