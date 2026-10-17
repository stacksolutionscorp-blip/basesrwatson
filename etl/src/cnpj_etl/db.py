from importlib.resources import files

import psycopg
from cnpj_core.schema import init_db  # noqa: F401 — reexportado

LIVE = "rf"
NEW = "rf_new"
PREV = "rf_prev"


def connect(url: str, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=autocommit)


def sql_text(name: str) -> str:
    return files("cnpj_etl.sql").joinpath(name).read_text(encoding="utf-8")


def schema_exists(conn: psycopg.Connection, schema: str) -> bool:
    row = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone()
    return row is not None


def live_referencia(conn: psycopg.Connection) -> str | None:
    """Referência (AAAA-MM) da base servida hoje, gravada como comentário do schema rf."""
    row = conn.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %s", (LIVE,)
    ).fetchone()
    return row[0] if row else None


def table_count(conn: psycopg.Connection, schema: str, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
