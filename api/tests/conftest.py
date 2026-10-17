"""Fixtures de integração: Postgres (TEST_DATABASE_URL) com a amostra carregada pelo ETL real e Redis
(TEST_REDIS_URL, padrão redis://localhost:6379/15). Sem TEST_DATABASE_URL os testes de integração são pulados."""

import os
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
import redis
from cnpj_api.auth import generate_key
from cnpj_api.config import Settings
from cnpj_api.main import create_app
from cnpj_core.schema import init_db
from cnpj_etl import pipeline
from cnpj_etl.config import Settings as EtlSettings
from cnpj_etl.demo import make_release
from fastapi.testclient import TestClient

MUNICIPIOS = [
    (7107, 3550308, "São Paulo", "SP", -23.5329, -46.6395),
    (6001, 3304557, "Rio de Janeiro", "RJ", -22.9129, -43.2003),
]


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não definida")
    parts = urlparse(url)
    name = "cnpj_api_test"
    admin = urlunparse(parts._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {name}")
    yield urlunparse(parts._replace(path=f"/{name}"))
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture(scope="session")
def redis_url():
    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    r = redis.Redis.from_url(url)
    try:
        r.ping()
    except redis.ConnectionError:
        pytest.skip("Redis de teste indisponível")
    r.flushdb()
    yield url
    r.flushdb()


def load(database_url: str, release_dir: Path, referencia: str) -> None:
    s = replace(EtlSettings(), database_url=database_url, index_workers=2, batch_mb=1, min_row_ratio=0.0)
    pipeline.run(s, source_dir=release_dir, referencia=referencia, force=True)


@pytest.fixture(scope="session")
def loaded_db(database_url, tmp_path_factory):
    with psycopg.connect(database_url, autocommit=True) as c:
        init_db(c)
        with c.cursor() as cur:
            cur.executemany("INSERT INTO geo.municipio_ibge VALUES (%s, %s, %s, %s, %s, %s)", MUNICIPIOS)
    load(database_url, make_release(tmp_path_factory.mktemp("2026-09")), "2026-09")
    return database_url


@pytest.fixture(scope="session")
def settings(loaded_db, redis_url):
    return replace(Settings(), database_url=loaded_db, redis_url=redis_url, pool_min=1, pool_max=5,
                   webhook_allow_private=True)  # fmt: skip


@pytest.fixture(scope="session")
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def make_key(database_url: str, plano: str = "pro", nome: str = "teste") -> tuple[int, str]:
    key, prefixo, digest = generate_key()
    with psycopg.connect(database_url, autocommit=True) as c:
        kid = c.execute(
            "INSERT INTO app.api_key (nome, prefixo, hash, plano_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (nome, prefixo, digest, plano),
        ).fetchone()[0]
    return kid, key


@pytest.fixture(scope="session")
def api_key(loaded_db):
    return make_key(loaded_db)


@pytest.fixture(scope="session")
def auth(api_key):
    return {"X-API-Key": api_key[1]}
