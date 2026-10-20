import csv
import io
import time

import psycopg
import redis
from cnpj_etl.demo import cnpj
from conftest import make_key
from openpyxl import load_workbook

MATRIZ = "11222333000181"
FILIAL = "".join(cnpj("11222333", "0002"))
HOLDING = "".join(cnpj("44555666", "0001"))
MEI = "".join(cnpj("77888999", "0001"))
ALFA = "12ABC34501DE35"


def test_health_sem_chave(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "banco": True, "redis": True, "referencia": "2026-09"}


def test_openapi_documentada(client):
    spec = client.get("/openapi.json").json()
    assert "/v1/cnpj/{cnpj}" in spec["paths"] and "/v1/busca" in spec["paths"]
    assert "APIKeyHeader" in spec["components"]["securitySchemes"]


def test_sem_chave_ou_chave_invalida(client):
    assert client.get(f"/v1/cnpj/{MATRIZ}").status_code == 401
    assert client.get(f"/v1/cnpj/{MATRIZ}", headers={"X-API-Key": "cnpj_x"}).status_code == 401


def test_bearer_tambem_aceito(client, api_key):
    r = client.get(f"/v1/cnpj/{MATRIZ}", headers={"Authorization": f"Bearer {api_key[1]}"})
    assert r.status_code == 200


def test_dv_invalido_nao_vai_ao_banco(client, auth):
    r = client.get("/v1/cnpj/11222333000182", headers=auth)
    assert r.status_code == 422 and "inválido" in r.json()["detail"]


def test_nao_encontrado(client, auth):
    assert client.get("/v1/cnpj/11444777000161", headers=auth).status_code == 404


def test_perfil_completo(client, auth, redis_url):
    r = client.get("/v1/cnpj/11.222.333.0001-81", headers=auth)  # "/" não cabe num segmento de URL
    assert r.status_code == 200
    p = r.json()
    assert p["cnpj_formatado"] == "11.222.333/0001-81"
    assert p["razao_social"] == "PADARIA SÃO JOÃO LTDA"
    assert p["situacao"]["descricao"] == "ATIVA"
    assert p["porte"] == {"codigo": 1, "descricao": "MICRO EMPRESA"}
    assert p["natureza_juridica"]["descricao"] == "Sociedade Empresária Limitada"
    assert p["cnae_principal"] == {"codigo": 1091102, "descricao": "Fabricação de produtos de padaria e confeitaria"}
    assert [c["codigo"] for c in p["cnaes_secundarios"]] == [4721102, 5611203]
    assert p["endereco"]["municipio"] == {"codigo_siafi": 7107, "codigo_ibge": 3550308, "nome": "São Paulo"}
    assert p["endereco"]["geo_precisao"] == "municipio" and p["endereco"]["lat"] == -23.5329
    assert p["contato"] == {"telefones": ["1133334444"], "email": "contato@padaria.com.br"}
    assert p["simples"]["optante"] is True and p["simples"]["mei"] is False
    assert p["qtd_estabelecimentos"] == 2
    assert p["score_risco"]["nivel"] in {"baixo", "medio", "alto"}
    assert p["referencia"] == "2026-09"
    socios = {s["nome"]: s for s in p["socios"]}
    assert socios["JOSÉ DA SILVA"]["cpf_cnpj"] == "***123456**"  # LGPD: só a máscara publicada
    assert socios["JOSÉ DA SILVA"]["qualificacao"]["descricao"] == "Sócio-Administrador"
    assert socios["HOLDING AÇÚCAR; PARTICIPAÇÕES S.A."]["tipo"] == "PJ"
    # segunda chamada vem do cache
    assert redis.Redis.from_url(redis_url).exists(f"cnpj:v1:perfil:2026-09:{MATRIZ}")
    assert client.get(f"/v1/cnpj/{MATRIZ}", headers=auth).json() == p


def test_cnpj_alfanumerico(client, auth):
    p = client.get("/v1/cnpj/12abc34501de35", headers=auth).json()
    assert p["cnpj"] == ALFA and p["endereco"]["lat"] is None


def test_baixada_tem_risco_alto(client, auth):
    p = client.get(f"/v1/cnpj/{HOLDING}", headers=auth).json()
    assert p["situacao"]["descricao"] == "BAIXADA" and p["score_risco"]["nivel"] == "alto"
    estrangeiro = next(s for s in p["socios"] if s["tipo"] == "estrangeiro")
    assert estrangeiro["representante"] == {
        "nome": "MARIA REPR", "cpf": "***987654**", "qualificacao": {"codigo": 17, "descricao": "Procurador"},
    }  # fmt: skip


def test_filiais(client, auth):
    for ref in (MATRIZ, "11222333"):
        r = client.get(f"/v1/cnpj/{ref}/filiais", headers=auth).json()
        assert [x["cnpj"] for x in r["resultados"]] == [MATRIZ, FILIAL]
    r = client.get(f"/v1/cnpj/{MATRIZ}/filiais?por_pagina=1", headers=auth).json()
    assert len(r["resultados"]) == 1 and r["paginacao"]["tem_mais"] is True


def test_busca_filtros(client, auth):
    def cnpjs(**params):
        r = client.get("/v1/busca", params=params, headers=auth)
        assert r.status_code == 200, r.text
        return {x["cnpj"] for x in r.json()["resultados"]}

    assert cnpjs(uf="RJ") == {FILIAL}
    assert cnpjs(cnae=5611203) == {MATRIZ}  # CNAE secundário
    assert cnpjs(cnae=5611203, somente_cnae_principal=True) == set()
    assert cnpjs(situacao=8) == {HOLDING}
    assert cnpjs(mei=True) == {MEI}
    assert cnpjs(capital_min=1_000_000) == {HOLDING}
    assert cnpjs(q="padaria") == {MATRIZ, FILIAL}
    assert cnpjs(q="11.222.333/0001-81") == {MATRIZ}
    assert cnpjs(municipio_ibge=3304557) == {FILIAL}
    assert cnpjs(abertura_de="2015-01-01", uf="SP") >= {MATRIZ}


def test_busca_por_raio(client, auth):
    r = client.get("/v1/busca", params={"lat": -23.5505, "lng": -46.6340, "raio_km": 10}, headers=auth).json()
    found = [x["cnpj"] for x in r["resultados"]]
    assert set(found) == {MATRIZ, HOLDING, MEI}  # SP; RJ fora do raio; alfanumérico sem coordenada
    assert all(x["distancia_km"] < 10 for x in r["resultados"])
    assert client.get("/v1/busca", params={"lat": -23.5}, headers=auth).status_code == 422


def test_socios(client, auth):
    r = client.get("/v1/socios", params={"nome": "jose da silva"}, headers=auth).json()
    (pessoa,) = r["resultados"]
    assert pessoa["cpf_cnpj"] == "***123456**"
    assert {e["cnpj_basico"] for e in pessoa["empresas"]} == {"11222333", "44555666"}
    assert client.get("/v1/socios", params={"nome": "jose", "cpf": "999999"}, headers=auth).json() == {"resultados": []}


def test_sugestoes(client, auth):
    r = client.get("/v1/sugestoes", params={"q": "pada"}, headers=auth).json()
    assert {e["cnpj"] for e in r["empresas"]} == {MATRIZ, FILIAL}
    r = client.get("/v1/sugestoes", params={"q": "jose"}, headers=auth).json()
    assert r["socios"][0]["nome"] == "JOSÉ DA SILVA"
    r = client.get("/v1/sugestoes", params={"q": "11222333000181"}, headers=auth).json()
    assert r["empresas"][0]["origem"] == "cnpj"


def test_grafo(client, auth):
    g = client.get(f"/v1/grafo/{MATRIZ}", headers=auth).json()
    ids = {n["id"] for n in g["nodes"]}
    assert {"empresa:11222333", "empresa:44555666", "pessoa:JOSE DA SILVA|***123456**"} <= ids
    assert any(n["label"] == "JOHN SMITH" for n in g["nodes"])  # 2º nível: sócio da holding
    edges = {(e["source"], e["target"]) for e in g["edges"]}
    assert ("empresa:44555666", "empresa:11222333") in edges  # holding é sócia da padaria
    assert ("pessoa:JOSE DA SILVA|***123456**", "empresa:44555666") in edges
    assert g["truncado"] is False
    g1 = client.get(f"/v1/grafo/{MATRIZ}?niveis=1", headers=auth).json()
    assert not any(n["label"] == "JOHN SMITH" for n in g1["nodes"])


def test_lote(client, auth):
    body = {"cnpjs": [MATRIZ, "11222333000182", "11444777000161", "12.ABC.345/01DE-35"]}
    r = client.post("/v1/lote", json=body, headers=auth).json()["resultados"]
    assert [x["ok"] for x in r] == [True, False, False, True]
    assert r[1]["erro"] == "CNPJ inválido" and r[2]["erro"] == "não encontrado"
    assert r[0]["dados"]["razao_social"] == "PADARIA SÃO JOÃO LTDA"


def test_lote_respeita_plano(client, loaded_db):
    _, key = make_key(loaded_db, plano="free")
    r = client.post("/v1/lote", json={"cnpjs": [MATRIZ] * 51}, headers={"X-API-Key": key})
    assert r.status_code == 422 and "50" in r.json()["detail"]


def test_export_csv_e_xlsx(client, auth):
    r = client.get("/v1/export", params={"uf": "SP", "formato": "csv"}, headers=auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert {x["cnpj"] for x in rows} == {MATRIZ, HOLDING, MEI, ALFA}
    r = client.get("/v1/export", params={"uf": "SP", "formato": "xlsx"}, headers=auth)
    ws = load_workbook(io.BytesIO(r.content)).active
    values = list(ws.values)
    assert values[0][0] == "cnpj" and len(values) == 5


def test_rate_limit(client, loaded_db):
    with psycopg.connect(loaded_db, autocommit=True) as c:
        c.execute("INSERT INTO app.plano VALUES ('mini', 'Mini', 3, 100, 10, 10, 1) ON CONFLICT DO NOTHING")
    _, key = make_key(loaded_db, plano="mini")
    h = {"X-API-Key": key}
    codes = [client.get(f"/v1/cnpj/{MATRIZ}", headers=h).status_code for _ in range(4)]
    assert (codes[:3] == [200, 200, 200] and codes[3] == 429) or 429 in codes  # janela de 1 min pode virar
    r = client.get(f"/v1/cnpj/{MATRIZ}", headers=h)
    assert r.status_code == 429 and "Retry-After" in r.headers
    ok = client.get("/health")
    assert ok.status_code == 200  # health não consome cota


def test_log_de_acesso_e_uso(client, auth, api_key, loaded_db):
    client.get(f"/v1/cnpj/{MATRIZ}", headers=auth)
    time.sleep(0.3)  # o log é gravado em segundo plano
    with psycopg.connect(loaded_db) as c:
        rows = c.execute(
            "SELECT rota, caminho, status FROM app.access_log WHERE api_key_id = %s AND caminho = %s",
            (api_key[0], f"/v1/cnpj/{MATRIZ}"),
        ).fetchall()
    assert rows and rows[-1] == ("/v1/cnpj/{cnpj}", f"/v1/cnpj/{MATRIZ}", 200)
    uso = client.get("/v1/uso", headers=auth).json()
    assert uso["plano"] == "pro" and uso["por_rota"]["/v1/cnpj/{cnpj}"] >= 1
    assert sum(d["requisicoes"] for d in uso["dias"]) >= 1


def test_headers_de_rate_limit(client, auth):
    r = client.get(f"/v1/cnpj/{MATRIZ}", headers=auth)
    assert int(r.headers["X-RateLimit-Limit"]) == 300
    assert int(r.headers["X-RateLimit-Remaining"]) < 300


def test_sem_base_carregada_responde_503(client, auth, loaded_db):
    with psycopg.connect(loaded_db, autocommit=True) as c:
        c.execute("ALTER SCHEMA rf RENAME TO rf_oculto")
    try:
        r = client.get("/v1/cnpj/11444777000161", headers=auth)
        assert r.status_code == 503 and "ainda não carregada" in r.json()["detail"]
    finally:
        with psycopg.connect(loaded_db, autocommit=True) as c:
            c.execute("ALTER SCHEMA rf_oculto RENAME TO rf")


def test_cpf_na_razao_social_e_mascarado(client, auth):
    p = client.get(f"/v1/cnpj/{MEI}", headers=auth).json()
    assert p["razao_social"] == "JOSÉ DA SILVA ***456789**"
    busca = client.get("/v1/busca", params={"mei": True}, headers=auth).json()["resultados"]
    assert busca[0]["razao_social"] == "JOSÉ DA SILVA ***456789**"
    # o CPF completo não serve para localizar a pessoa pela busca textual
    assert client.get("/v1/busca", params={"q": "12345678900"}, headers=auth).json()["resultados"] == []
    r = client.get("/v1/export", params={"mei": True}, headers=auth)
    assert "12345678900" not in r.content.decode("utf-8-sig")
