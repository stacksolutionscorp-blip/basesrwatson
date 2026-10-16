"""Pós-carga: chaves primárias, índices, ANALYZE, verificações e swap atômico."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg import errors

from cnpj_etl.db import LIVE, NEW, PREV, connect, schema_exists, sql_text, table_count
from cnpj_etl.layouts import AUX_TABLES

log = logging.getLogger("cnpj_etl")

PRIMARY_KEYS: dict[str, list[str]] = {
    "empresa": ["cnpj_basico"],
    "estabelecimento": ["cnpj"],
    "simples": ["cnpj_basico"],
    "socio": ["id"],
    **{t: ["codigo"] for t in AUX_TABLES},
}

# Tabelas cujo tamanho é comparado com a base atual antes do swap.
CHECKED_TABLES = ["empresa", "estabelecimento", "socio", "simples"]

SWAP_CHANNEL = "cnpj_swapped"


class SanityError(RuntimeError):
    pass


def _session_tuning(conn: psycopg.Connection) -> None:
    conn.execute(f"SET maintenance_work_mem = '{os.environ.get('ETL_MAINTENANCE_WORK_MEM', '1GB')}'")
    conn.execute(f"SET max_parallel_maintenance_workers = {int(os.environ.get('ETL_PARALLEL_WORKERS', '2'))}")


def add_primary_key(conn: psycopg.Connection, table: str, schema: str = NEW) -> int:
    """Cria a PK; se houver duplicatas na fonte, mantém a última ocorrência. Devolve removidas."""
    cols = ", ".join(PRIMARY_KEYS[table])
    ddl = f"ALTER TABLE {schema}.{table} ADD PRIMARY KEY ({cols})"
    try:
        with conn.transaction():
            conn.execute(ddl)
        return 0
    except errors.UniqueViolation:
        pass
    with conn.transaction():
        removed = conn.execute(
            f"""DELETE FROM {schema}.{table} WHERE ctid IN (
                  SELECT ctid FROM (
                    SELECT ctid, row_number() OVER (PARTITION BY {cols} ORDER BY ctid DESC) AS rn
                    FROM {schema}.{table}) d
                  WHERE rn > 1)"""
        ).rowcount
        conn.execute(ddl)
    log.warning("%s: %s duplicatas removidas antes da PK", table, removed)
    return removed


def index_statements(schema: str = NEW) -> list[str]:
    text = sql_text("rf_indexes.sql").format(schema=schema)
    blocks = [b for b in text.split("-- @")[1:]]
    return [s for b in blocks if (s := b.strip())]


def create_indexes(url: str, workers: int, schema: str = NEW) -> int:
    def run(stmt: str) -> None:
        with connect(url, autocommit=True) as c:
            _session_tuning(c)
            c.execute(stmt)

    stmts = index_statements(schema)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(run, stmts))
    return len(stmts)


def analyze(conn: psycopg.Connection, schema: str = NEW) -> None:
    for table in PRIMARY_KEYS:
        conn.execute(f"ANALYZE {schema}.{table}")


def check_counts(conn: psycopg.Connection, min_ratio: float, schema: str = NEW) -> dict[str, int]:
    """Impede o swap de uma carga vazia ou muito menor que a base atual."""
    counts = {t: table_count(conn, schema, t) for t in CHECKED_TABLES}
    empty = [t for t, n in counts.items() if n == 0]
    if empty:
        raise SanityError(f"tabelas vazias na carga nova: {', '.join(empty)}")
    if schema_exists(conn, LIVE):
        for t, n in counts.items():
            old = table_count(conn, LIVE, t)
            if old and n < old * min_ratio:
                raise SanityError(f"{t}: {n} linhas na carga nova contra {old} na atual (< {min_ratio:.0%})")
    return counts


def swap(conn: psycopg.Connection, referencia: str) -> None:
    """rf → rf_prev, rf_new → rf, numa transação curta.

    Após o NOTIFY a API deve reciclar o pool de conexões (planos em cache
    referenciam as tabelas antigas por OID) e limpar o cache Redis.
    """
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout = '15s'")
        conn.execute(f"DROP SCHEMA IF EXISTS {PREV} CASCADE")
        if schema_exists(conn, LIVE):
            conn.execute(f"ALTER SCHEMA {LIVE} RENAME TO {PREV}")
        conn.execute(f"ALTER SCHEMA {NEW} RENAME TO {LIVE}")
        conn.execute(f"COMMENT ON SCHEMA {LIVE} IS '{referencia}'")
        conn.execute(f"SELECT pg_notify('{SWAP_CHANNEL}', %s)", (referencia,))


def rollback_swap(conn: psycopg.Connection) -> str | None:
    """Volta para a base anterior (rf ↔ rf_prev). Devolve a referência restaurada."""
    if not schema_exists(conn, PREV):
        raise RuntimeError("não há rf_prev para restaurar")
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout = '15s'")
        conn.execute(f"ALTER SCHEMA {LIVE} RENAME TO rf_tmp_swap")
        conn.execute(f"ALTER SCHEMA {PREV} RENAME TO {LIVE}")
        conn.execute(f"ALTER SCHEMA rf_tmp_swap RENAME TO {PREV}")
        ref = conn.execute(
            "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %s", (LIVE,)
        ).fetchone()[0]
        conn.execute(f"SELECT pg_notify('{SWAP_CHANNEL}', %s)", (ref or "",))
    return ref
