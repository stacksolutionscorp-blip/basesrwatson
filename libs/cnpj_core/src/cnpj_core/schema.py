"""DDL dos schemas persistentes (ops, geo, app), compartilhado entre ETL e API."""

from importlib.resources import files


def base_sql() -> str:
    return files("cnpj_core.sql").joinpath("base.sql").read_text(encoding="utf-8")


def init_db(conn) -> None:
    """Cria extensões e schemas persistentes. Idempotente; ``conn`` é uma conexão psycopg."""
    conn.execute(base_sql())
    if not conn.autocommit:
        conn.commit()
