import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).parent))  # receita_fixture


@pytest.fixture(scope="session")
def database_url():
    """Banco limpo para testes de integração; TEST_DATABASE_URL deve apontar para um
    servidor onde o usuário pode criar bancos. Sem a variável, os testes são pulados."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não definida")
    parts = urlparse(url)
    name = "cnpj_etl_test"
    admin = urlunparse(parts._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {name}")
    yield urlunparse(parts._replace(path=f"/{name}"))
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
