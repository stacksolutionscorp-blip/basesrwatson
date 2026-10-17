import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from cnpj_api import risk, webhooks
from cnpj_api.search import Filtros, build_query

HOJE = date(2026, 10, 17)


def base(**kw):
    args = dict(situacao=2, data_inicio=date(2010, 1, 1), capital_social=Decimal("50000"),
                data_situacao=date(2010, 1, 1), situacao_especial=None, datas_entrada_socios=[date(2010, 1, 1)],
                mei=False, hoje=HOJE)  # fmt: skip
    return risk.score(**(args | kw))


def test_risco_baixo_para_empresa_antiga_ativa():
    assert base() == {"score": 0, "nivel": "baixo", "fatores": []}


def test_risco_alto_para_baixada():
    r = base(situacao=8)
    assert r["score"] == 70 and r["nivel"] == "alto"


def test_risco_soma_fatores_e_limita_a_100():
    r = base(situacao=4, data_inicio=HOJE - timedelta(days=100), capital_social=None, situacao_especial="FALIDO",
             datas_entrada_socios=[HOJE - timedelta(days=10)])  # fmt: skip
    assert r["score"] == 100
    assert {f["fator"] for f in r["fatores"]} >= {"empresa com menos de 1 ano", "entrada de sócio nos últimos 6 meses"}


def test_risco_mei_nao_penaliza_capital():
    assert base(mei=True, capital_social=Decimal("0"))["score"] == 0
    assert base(mei=False, capital_social=Decimal("0"))["score"] == 10


def test_risco_mudanca_recente_de_situacao():
    r = base(data_situacao=HOJE - timedelta(days=30))
    assert r["fatores"] == [{"fator": "mudança de situação cadastral nos últimos 6 meses", "pontos": 10}]


@pytest.mark.parametrize(
    ("filtros", "erro"),
    [
        (Filtros(lat=-23.5), "juntos"),
        (Filtros(lat=-23.5, lng=-46.6, raio_km=500), "raio_km"),
        (Filtros(lat=-123.5, lng=-46.6, raio_km=5), "coordenadas"),
        (Filtros(q="ab"), "3 caracteres"),
    ],
)
def test_filtros_invalidos(filtros, erro):
    with pytest.raises(ValueError, match=erro):
        filtros.validate()


def test_build_query_cnpj_no_texto_vira_filtro_exato():
    sql, params = build_query(Filtros(q="11.222.333/0001-81"), 10)
    assert "e.cnpj = %(doc)s" in sql and params["doc"] == "11222333000181"
    sql, params = build_query(Filtros(q="padaria 50%_"), 10)
    assert params["q"] == "%PADARIA 50\\%\\_%"  # curingas escapados


def test_build_query_raio_ordena_por_distancia():
    sql, _ = build_query(Filtros(lat=-23.5, lng=-46.6, raio_km=5), 10)
    assert "ST_DWithin" in sql and "ORDER BY distancia_km" in sql


def test_assinatura_webhook():
    assert webhooks.sign("segredo", b'{"a":1}') == (
        "sha256=" + __import__("hmac").new(b"segredo", b'{"a":1}', "sha256").hexdigest()
    )


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/x", "http://10.0.0.5/x", "http://169.254.169.254/latest", "http://[::1]/", "ftp://example.com"],
)
def test_webhook_bloqueia_destinos_internos(url):
    with pytest.raises(webhooks.UrlNaoPermitida):
        asyncio.run(webhooks.check_url(url, allow_private=False))


def test_webhook_permite_interno_quando_configurado():
    asyncio.run(webhooks.check_url("http://127.0.0.1:9/x", allow_private=True))
