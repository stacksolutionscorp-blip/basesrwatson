"""Carga regional: raio a partir de Jundiaí, UFs e só ativas (requer TEST_DATABASE_URL)."""

from dataclasses import replace
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from cnpj_etl import pipeline
from cnpj_etl.config import Settings
from cnpj_etl.db import connect, init_db
from cnpj_etl.demo import cnpj, make_release

JUNDIAI = "-23.1857,-46.8978"
MATRIZ = "11222333000181"
MEI = "".join(cnpj("77888999", "0001"))


@pytest.fixture(scope="module")
def db(database_url):
    parts = urlparse(database_url)
    admin = urlunparse(parts._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS cnpj_regiao_test WITH (FORCE)")
        c.execute("CREATE DATABASE cnpj_regiao_test")
    url = urlunparse(parts._replace(path="/cnpj_regiao_test"))
    with connect(url, autocommit=True) as c:
        init_db(c)
        c.execute(
            """INSERT INTO geo.municipio_ibge VALUES
               (7107, 3550308, 'São Paulo', 'SP', -23.5329, -46.6395),
               (6001, 3304557, 'Rio de Janeiro', 'RJ', -22.9129, -43.2003),
               (6619, 3525904, 'Jundiaí', 'SP', -23.1857, -46.8978)"""
        )
    yield url
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS cnpj_regiao_test WITH (FORCE)")


def carregar(db, tmp_path, ref, **kw):
    s = replace(Settings(), database_url=db, batch_mb=1, index_workers=2, min_row_ratio=0.0, **kw)
    return pipeline.run(s, source_dir=make_release(tmp_path / ref), referencia=ref, force=True)


def linhas(db, sql):
    with connect(db) as c:
        return {r[0] for r in c.execute(sql).fetchall()}


def test_raio_de_jundiai_so_ativas(db, tmp_path):
    r = carregar(db, tmp_path, "2026-09", regiao_centro=JUNDIAI, regiao_raio_km=60, somente_ativas=True)
    # São Paulo (~45 km) entra; Rio de Janeiro e o município sem centroide ficam de fora; a baixada também
    assert linhas(db, "SELECT cnpj FROM rf.estabelecimento") == {MATRIZ, MEI}
    # empresas, sócios e Simples seguem as raízes mantidas
    assert linhas(db, "SELECT cnpj_basico FROM rf.empresa") == {"11222333", "77888999"}
    assert linhas(db, "SELECT DISTINCT cnpj_basico FROM rf.socio") == {"11222333"}
    assert linhas(db, "SELECT cnpj_basico FROM rf.simples") == {"11222333", "77888999"}
    assert r.counts["estabelecimento"] == 2


def test_uf_inteira_com_inativas(db, tmp_path):
    carregar(db, tmp_path, "2026-10", regiao_ufs=["RJ", "sp"])
    assert len(linhas(db, "SELECT cnpj FROM rf.estabelecimento")) == 4  # todas menos a de município sem centroide


def test_raio_curto_sem_municipios(db, tmp_path):
    with pytest.raises(ValueError, match="nenhum município"):
        carregar(db, tmp_path, "2026-11", regiao_centro="-3.0,-60.0", regiao_raio_km=10)


def test_centro_sem_raio(db, tmp_path):
    with pytest.raises(ValueError, match="juntos"):
        carregar(db, tmp_path, "2026-12", regiao_centro=JUNDIAI)
