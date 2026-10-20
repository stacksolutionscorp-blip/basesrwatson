"""DDL dos schemas persistentes (ops, geo, app), compartilhado entre ETL e API."""

from importlib.resources import files


def base_sql() -> str:
    return files("cnpj_core.sql").joinpath("base.sql").read_text(encoding="utf-8")


_INIT_LOCK = 0x434E5049  # "CNPI"


def init_db(conn) -> None:
    """Cria extensões e schemas persistentes. Idempotente; ``conn`` é uma conexão psycopg.

    API, worker e ETL chamam ao subir; o advisory lock evita que dois ``CREATE ... IF NOT EXISTS``
    simultâneos colidam num banco novo.
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (_INIT_LOCK,))
    try:
        conn.execute(base_sql())
        if not conn.autocommit:
            conn.commit()
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_INIT_LOCK,))
        if not conn.autocommit:
            conn.commit()
