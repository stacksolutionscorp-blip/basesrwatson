"""Prospecção de leads sobre a base demo (empresas de São Paulo e Rio de Janeiro)."""

import csv
import io
from datetime import date

import psycopg
import pytest
from cnpj_api import leads
from cnpj_etl.demo import cnpj

MATRIZ = "11222333000181"
FILIAL_RJ = "".join(cnpj("11222333", "0002"))
MEI = "".join(cnpj("77888999", "0001"))
HOLDING = "".join(cnpj("44555666", "0001"))  # baixada
SP = {"lat": -23.5505, "lng": -46.634, "raio_km": 30}
WEB = {"X-Requested-With": "cnpj-web"}


def busca(client, auth, **params):
    r = client.get("/v1/leads/busca", params=params, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["resultados"]


def test_config_tem_jundiai_e_segmentos(client, auth):
    c = client.get("/v1/leads/config", headers=auth).json()
    assert c["centro"]["nome"] == "Jundiaí/SP" and c["raio_km"] == 30
    assert {s["id"] for s in c["segmentos"]} == {"pesados", "frota", "imoveis", "agro"}
    assert "fechado" in c["status"]


def test_busca_ordenada_por_score_so_ativas(client, auth):
    rows = busca(client, auth)
    cnpjs = [r["cnpj"] for r in rows]
    assert HOLDING not in cnpjs  # baixada não é lead
    assert cnpjs[0] == MATRIZ  # telefone + e-mail + mais antiga + capital
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)
    top = rows[0]
    assert top["score"] == sum(f["pontos"] for f in top["fatores"])  # score explicado = score ordenado
    assert top["telefones"][0]["numero"] == "1133334444" and top["telefones"][0]["whatsapp"] is None  # fixo
    assert top["email"] == "contato@padaria.com.br"
    assert top["decisores"][0] == {"nome": "JOSÉ DA SILVA", "qualificacao": "Sócio-Administrador", "tipo": "PF"}


def test_mei_tem_titular_como_decisor_sem_cpf(client, auth):
    mei = next(r for r in busca(client, auth) if r["cnpj"] == MEI)
    assert mei["porte"] == "MEI"
    assert mei["decisores"] == [
        {"nome": "JOSÉ DA SILVA", "qualificacao": "Titular (empresário individual)", "tipo": "PF"}
    ]
    assert "12345678900" not in str(mei)


def test_filtros_de_regiao_segmento_e_contato(client, auth):
    assert {r["cnpj"] for r in busca(client, auth, **SP)} == {MATRIZ, MEI, "12ABC34501DE35"} - {"12ABC34501DE35"}
    assert {r["cnpj"] for r in busca(client, auth, municipio_ibge=3304557)} == {FILIAL_RJ}
    # segmento "frota" inclui 4520001 (oficina mecânica), atividade do MEI
    assert {r["cnpj"] for r in busca(client, auth, segmento="frota")} == {MEI}
    assert busca(client, auth, com_email=True)[0]["cnpj"] == MATRIZ
    assert busca(client, auth, so_celular=True) == []  # a demo só tem telefone fixo
    assert MEI not in {r["cnpj"] for r in busca(client, auth, incluir_mei=False)}
    r = client.get("/v1/leads/busca", params={"segmento": "xyz"}, headers=auth)
    assert r.status_code == 422


def test_score_sql_igual_python(client, auth):
    for r in busca(client, auth, segmento="imoveis", com_telefone=False):
        assert r["score"] == sum(f["pontos"] for f in r["fatores"]), r["cnpj"]


def test_carteira_status_e_historico(client, auth):
    h = auth | WEB
    assert (
        client.put(
            f"/v1/leads/{MATRIZ}",
            json={"status": "interessado", "nota": "quer carta de 200 mil", "proximo_contato": "2026-11-05"},
            headers=h,
        ).status_code
        == 200
    )
    assert client.put(f"/v1/leads/{MATRIZ}", json={"status": "proposta"}, headers=h).status_code == 200
    # some da prospecção (já está sendo trabalhado) mas aparece se pedir
    assert MATRIZ not in {r["cnpj"] for r in busca(client, auth)}
    assert MATRIZ in {r["cnpj"] for r in busca(client, auth, ocultar_trabalhados=False)}
    cart = client.get("/v1/leads/carteira", headers=auth).json()
    item = next(r for r in cart["resultados"] if r["cnpj"] == MATRIZ)
    assert item["status"] == "proposta" and item["nota"] == "quer carta de 200 mil"  # nota anterior preservada
    assert cart["totais"]["proposta"] >= 1
    hist = client.get(f"/v1/leads/{MATRIZ}/historico", headers=auth).json()
    assert [e["status"] for e in hist[:2]] == ["proposta", "interessado"]
    assert client.put("/v1/leads/11222333000182", json={"status": "novo"}, headers=h).status_code == 422


def test_nao_contatar_bloqueia_por_telefone_e_cnpj(client, auth, loaded_db):
    h = auth | WEB
    r = client.post(
        "/v1/leads/nao-contatar", json={"telefone": "(11) 3333-4444", "motivo": "pediu por telefone"}, headers=h
    )
    assert r.status_code == 201
    # todos da demo usam o mesmo telefone → somem da prospecção
    assert busca(client, auth, ocultar_trabalhados=False) == []
    assert client.delete(f"/v1/leads/nao-contatar/{r.json()['id']}", headers=h).status_code == 204
    assert busca(client, auth, ocultar_trabalhados=False)
    client.post("/v1/leads/nao-contatar", json={"cnpj": MEI, "motivo": "LGPD"}, headers=h)
    assert MEI not in {r["cnpj"] for r in busca(client, auth, ocultar_trabalhados=False)}
    assert any(n["cnpj"] == MEI for n in client.get("/v1/leads/nao-contatar", headers=auth).json())
    with psycopg.connect(loaded_db) as c:
        assert c.execute("SELECT status FROM app.lead WHERE cnpj = %s", (MEI,)).fetchone()[0] == "sem_interesse"
    assert client.post("/v1/leads/nao-contatar", json={}, headers=h).status_code == 422


def test_exportacao(client, auth):
    r = client.get("/v1/leads/export", params={"ocultar_trabalhados": False, "formato": "csv"}, headers=auth)
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert rows and {"decisores", "telefone_1", "whatsapp", "score"} <= set(rows[0])
    assert all("12345678900" not in str(x) for x in rows)
    r = client.get("/v1/leads/export", params={"formato": "xlsx", "ocultar_trabalhados": False}, headers=auth)
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")


@pytest.mark.parametrize(
    ("tel", "esperado"),
    [("11987654321", True), ("1133334444", False), ("11887654321", False), (None, False)],
)
def test_celular(tel, esperado):
    assert leads._celular(tel) is esperado


def test_fatores_unitario():
    r = {
        "telefone1": "11987654321",
        "telefone2": None,
        "email": "a@b.com",
        "mei": False,
        "porte": 3,
        "data_inicio": date(2015, 1, 1),
        "capital_social": 150000,
        "cnae_principal": 4930201,
    }
    f = leads.fatores(r, leads.SEGMENTOS["pesados"]["cnaes"], date(2026, 10, 21))
    assert sum(x["pontos"] for x in f) == 20 + 10 + 10 + 15 + 15 + 15 + 10 == 95
