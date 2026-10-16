"""Carga dos ZIPs em rf_new via COPY."""

from pathlib import Path

import polars as pl
import psycopg

from cnpj_etl import transform
from cnpj_etl.db import NEW, sql_text
from cnpj_etl.layouts import Dataset
from cnpj_etl.reader import iter_batches
from cnpj_etl.runlog import RunLog


def create_schema(conn: psycopg.Connection, schema: str = NEW) -> None:
    with conn.transaction():
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(sql_text("rf_tables.sql").format(schema=schema))


def copy_df(conn: psycopg.Connection, schema: str, table: str, df: pl.DataFrame) -> None:
    cols = ", ".join(df.columns)
    data = df.write_csv(include_header=False, null_value="")
    sql = f"COPY {schema}.{table} ({cols}) FROM STDIN WITH (FORMAT csv, FREEZE)"
    with conn.cursor().copy(sql) as cp:
        cp.write(data.encode("utf-8"))


class GeoLookup:
    """Centroides de município + cache de geocodificação, consultado por lote."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        rows = conn.execute("SELECT codigo_siafi, lat, lng FROM geo.municipio_ibge").fetchall()
        self.centroids = pl.DataFrame(
            rows, schema={"municipio": pl.Int32, "lat": pl.Float64, "lng": pl.Float64}, orient="row"
        )
        self.has_cache = conn.execute("SELECT EXISTS (SELECT 1 FROM geo.geocode WHERE lat IS NOT NULL)").fetchone()[0]

    def hits(self, hashes: pl.Series) -> pl.DataFrame:
        schema = {"endereco_hash": pl.String, "lat": pl.Float64, "lng": pl.Float64, "precisao": pl.Int16}
        keys = [bytes.fromhex(h[2:]) for h in hashes.drop_nulls().unique().to_list()]
        if not self.has_cache or not keys:
            return pl.DataFrame(schema=schema)
        rows = self.conn.execute(
            """SELECT '\\x' || encode(endereco_hash, 'hex'), lat, lng, precisao
               FROM geo.geocode WHERE lat IS NOT NULL AND endereco_hash = ANY(%s)""",
            (keys,),
        ).fetchall()
        return pl.DataFrame(rows, schema=schema, orient="row")

    def apply(self, df: pl.DataFrame) -> pl.DataFrame:
        return transform.attach_geo(df, self.hits(df["endereco_hash"]), self.centroids)


def load_dataset(
    conn: psycopg.Connection,
    runlog: RunLog,
    ds: Dataset,
    paths: list[Path],
    batch_bytes: int,
    schema: str = NEW,
) -> int:
    """Carrega todos os arquivos de um dataset numa única transação (COPY FREEZE)."""
    fn = transform.transform_for(ds.name)
    geo = GeoLookup(conn) if ds.name == "estabelecimento" else None
    total = 0
    with conn.transaction():
        conn.execute(f"TRUNCATE {schema}.{ds.name}")  # habilita FREEZE nesta transação
        for path in paths:
            with runlog.step("load", path.name) as st:
                for batch in iter_batches(path, ds.columns, batch_bytes):
                    df, rejected = fn(batch.df)
                    if geo is not None:
                        df = geo.apply(df).select(transform.ESTABELECIMENTO_COLUMNS)
                    copy_df(conn, schema, ds.name, df)
                    st.linhas += df.height
                    st.linhas_rejeitadas += rejected + batch.malformed
                total += st.linhas
    return total
