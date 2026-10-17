"""Carga completa contra um PostgreSQL real (requer TEST_DATABASE_URL)."""

import asyncio
from dataclasses import replace

import httpx
import psycopg
import pytest
from cnpj_etl import finalize, pipeline
from cnpj_etl.config import Settings
from cnpj_etl.db import connect, init_db, live_referencia, schema_exists
from cnpj_etl.demo import cnpj, make_release
from cnpj_etl.geocode import nominatim


@pytest.fixture(scope="module")
def settings(database_url, tmp_path_factory):
    s = replace(Settings(), database_url=database_url, data_dir=tmp_path_factory.mktemp("data"),
                index_workers=2, batch_mb=1)  # fmt: skip
    with connect(database_url, autocommit=True) as c:
        init_db(c)
        c.execute(
            """INSERT INTO geo.municipio_ibge VALUES
               (7107, 3550308, 'São Paulo', 'SP', -23.5329, -46.6395),
               (6001, 3304557, 'Rio de Janeiro', 'RJ', -22.9129, -43.2003)"""
        )
    return s


@pytest.fixture(scope="module")
def release_dir(tmp_path_factory):
    return make_release(tmp_path_factory.mktemp("2026-09"))


@pytest.fixture
def conn(settings):
    with connect(settings.database_url, autocommit=True) as c:
        yield c


def q(conn, sql, *args):
    return conn.execute(sql, args or None).fetchall()


def test_primeira_carga(settings, release_dir, conn):
    result = pipeline.run(settings, source_dir=release_dir, referencia="2026-09")
    assert result.status == "success"
    assert result.counts["empresa"] == 4  # 5 linhas, 1 duplicata removida
    assert result.counts["estabelecimento"] == 5
    assert result.counts["socio"] == 4
    assert result.counts["simples"] == 2
    assert live_referencia(conn) == "2026-09"
    assert not schema_exists(conn, "rf_new")

    emp = q(
        conn,
        "SELECT razao_social, razao_social_norm, capital_social, porte FROM rf.empresa WHERE cnpj_basico = '44555666'",
    )
    assert emp == [
        ("HOLDING AÇÚCAR; PARTICIPAÇÕES S.A.", "HOLDING ACUCAR; PARTICIPACOES S.A.", pytest.approx(1500000.50), 5)
    ]

    (row,) = q(
        conn,
        """SELECT cnaes_secundarios, geo_precisao, ST_Y(geom::geometry), ST_X(geom::geometry), data_inicio
                        FROM rf.estabelecimento WHERE cnpj = '11222333000181'""",
    )
    assert row[0] == [4721102, 5611203]
    assert row[1] == 1 and row[2] == pytest.approx(-23.5329) and row[3] == pytest.approx(-46.6395)
    # CNPJ alfanumérico e município sem centroide
    assert q(conn, "SELECT geom IS NULL FROM rf.estabelecimento WHERE cnpj = '12ABC34501DE35'") == [(True,)]


def test_indices_e_buscas(conn):
    idx = {r[0] for r in q(conn, "SELECT indexdef FROM pg_indexes WHERE schemaname = 'rf'")}
    assert any("gin_trgm_ops" in i and "razao_social_norm" in i for i in idx)
    assert any("gist (geom)" in i for i in idx)
    pks = q(
        conn,
        """SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
                     WHERE n.nspname = 'rf' AND c.contype = 'p'""",
    )
    assert pks == [(len(finalize.PRIMARY_KEYS),)]

    # trigram
    assert q(conn, "SELECT cnpj_basico FROM rf.empresa WHERE razao_social_norm % 'PADARIA SAO JOAO'") == [("11222333",)]
    # CNAE secundário
    assert q(conn, "SELECT cnpj FROM rf.estabelecimento WHERE cnaes_secundarios @> ARRAY[5611203]") == [
        ("11222333000181",)
    ]
    # raio de 10 km a partir da Praça da Sé
    near = q(
        conn,
        """SELECT cnpj FROM rf.estabelecimento
                      WHERE ST_DWithin(geom, ST_MakePoint(-46.6340, -23.5505)::geography, 10000) ORDER BY cnpj""",
    )
    assert ("11222333000181",) in near and ("".join(cnpj("11222333", "0002")),) not in near
    # mesma pessoa em duas empresas (grafo)
    assert q(
        conn,
        """SELECT count(DISTINCT cnpj_basico) FROM rf.socio
                      WHERE chave_pessoa = 'JOSE DA SILVA|***123456**'""",
    ) == [(2,)]


def test_log_de_execucao(conn):
    (run,) = q(conn, "SELECT id, status, referencia FROM ops.etl_run ORDER BY id DESC LIMIT 1")
    assert run[1:] == ("success", "2026-09")
    steps = q(
        conn, "SELECT etapa, arquivo, linhas, linhas_rejeitadas, status FROM ops.etl_step WHERE run_id = %s", run[0]
    )
    loads = {a: (n, rej) for e, a, n, rej, _ in steps if e == "load"}
    assert loads["Empresas0.zip"] == (3, 0) and loads["Estabelecimentos1.zip"] == (2, 0)
    keys = next(s for s in steps if s[0] == "keys")
    assert keys[3] == 1  # duplicata removida
    assert {s[0] for s in steps} >= {"load", "keys", "index", "check", "swap"}
    assert all(s[4] == "success" for s in steps)


def test_mesma_referencia_e_pulada(settings, release_dir):
    assert pipeline.run(settings, source_dir=release_dir, referencia="2026-09").status == "skipped"


def test_segunda_carga_mantem_anterior(settings, release_dir, conn):
    pipeline.run(settings, source_dir=release_dir, referencia="2026-10")
    assert live_referencia(conn) == "2026-10"
    assert schema_exists(conn, "rf_prev")
    assert q(conn, "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = 'rf_prev'") == [
        ("2026-09",)
    ]


def test_carga_suspeita_nao_faz_swap(settings, tmp_path, conn):
    small = make_release(tmp_path / "2026-11", small=True)
    with pytest.raises(finalize.SanityError):
        pipeline.run(settings, source_dir=small, referencia="2026-11")
    assert live_referencia(conn) == "2026-10"
    assert not schema_exists(conn, "rf_new")
    assert q(conn, "SELECT status FROM ops.etl_run WHERE referencia = '2026-11'") == [("failed",)]


def test_rollback(conn):
    assert finalize.rollback_swap(conn) == "2026-09"
    assert live_referencia(conn) == "2026-09"
    assert finalize.rollback_swap(conn) == "2026-10"


def test_swap_notifica_api(settings, release_dir):
    with psycopg.connect(settings.database_url, autocommit=True) as listener:
        listener.execute(f"LISTEN {finalize.SWAP_CHANNEL}")
        pipeline.run(settings, source_dir=release_dir, referencia="2026-12")
        notes = list(listener.notifies(timeout=2, stop_after=1))
    assert notes and notes[0].payload == "2026-12"


def test_geocode_grava_cache_e_atualiza_base(settings, conn):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("street", "").startswith("123 RUA DAS FLORES"):
            return httpx.Response(200, json=[{"lat": "-23.55", "lon": "-46.64", "address": {"house_number": "123"}}])
        return httpx.Response(200, json=[])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://n") as c:
            return await nominatim.run(
                conn, "http://n", "test", rps=1000, concurrency=4, limit=100, todas=True, client=c
            )

    done, found = asyncio.run(go())
    # endereços distintos com logradouro e UF brasileira: 4 (o 5º é igual ao da matriz)
    assert done == q(conn, "SELECT count(DISTINCT endereco_hash) FROM rf.estabelecimento")[0][0]
    assert found >= 1
    rows = q(conn, "SELECT geo_precisao FROM rf.estabelecimento WHERE cnpj = '11222333000181'")
    assert rows == [(4,)]
    # nada pendente numa segunda passada (não encontrados ficam em cache)
    assert asyncio.run(go()) == (0, 0)
    # a próxima carga reaproveita o cache
    assert q(conn, "SELECT count(*) FROM geo.geocode WHERE lat IS NULL") == [(done - found,)]
