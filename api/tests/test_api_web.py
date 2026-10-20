"""Painel web: login por cookie, termos de uso, CSRF, administração e auditoria."""

import time

import psycopg
import pytest
from cnpj_api.main import create_app
from cnpj_api.users import create_user_sync, hash_password, validate_password, verify_password
from fastapi.testclient import TestClient

MATRIZ = "11222333000181"
WEB = {"X-Requested-With": "cnpj-web"}
SENHA = "senha-forte-123"


@pytest.fixture(scope="module")
def admin_user(loaded_db):
    with psycopg.connect(loaded_db, autocommit=True) as c:
        uid = create_user_sync(c, "Admin@Empresa.com", "Admin", SENHA, "admin")
    return uid, "admin@empresa.com"


@pytest.fixture(scope="module")
def web(settings, admin_user):
    with TestClient(create_app(settings)) as c:
        yield c


def login(client, email, senha=SENHA):
    return client.post("/v1/auth/login", json={"email": email, "senha": senha})


def aceitar_termos(client):
    versao = client.get("/v1/termos").json()["versao"]
    assert client.post("/v1/auth/termos", json={"versao": versao}, headers=WEB).status_code == 200


def test_senha():
    h = hash_password("abc12345678")
    assert verify_password("abc12345678", h) and not verify_password("abc12345679", h)
    assert h.startswith("scrypt$") and "abc12345678" not in h
    with pytest.raises(ValueError):
        validate_password("curta1")
    with pytest.raises(ValueError):
        validate_password("somenteletras")


def test_termos_publicos(web):
    t = web.get("/v1/termos").json()
    assert t["versao"] and "LGPD" in t["texto"]


def test_login_errado(web, admin_user):
    assert login(web, admin_user[1], "errada-123456").status_code == 401
    assert login(web, "ninguem@x.com").status_code == 401


def test_fluxo_de_sessao_e_termos(web, admin_user, loaded_db):
    r = login(web, "ADMIN@empresa.com")  # e-mail sem diferenciar maiúsculas
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "cnpj_sessao=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()

    eu = web.get("/v1/auth/eu").json()
    assert eu["email"] == "admin@empresa.com" and eu["papel"] == "admin" and eu["termos_pendentes"] is True

    # sem aceitar os termos, consultas são bloqueadas
    r = web.get(f"/v1/cnpj/{MATRIZ}")
    assert r.status_code == 403 and "termos" in r.json()["detail"]
    assert web.post("/v1/auth/termos", json={"versao": "velha"}, headers=WEB).status_code == 409
    aceitar_termos(web)
    assert web.get("/v1/auth/eu").json()["termos_pendentes"] is False
    assert web.get(f"/v1/cnpj/{MATRIZ}").status_code == 200

    # log de acesso registra o usuário
    time.sleep(0.3)
    with psycopg.connect(loaded_db) as c:
        n = c.execute(
            "SELECT count(*) FROM app.access_log WHERE usuario_id = %s AND caminho = %s",
            (admin_user[0], f"/v1/cnpj/{MATRIZ}"),
        ).fetchone()[0]
    assert n >= 1


def test_csrf_em_requisicoes_que_alteram(web):
    r = web.post("/v1/monitor", json={"cnpjs": [MATRIZ]})
    assert r.status_code == 403 and "X-Requested-With" in r.json()["detail"]
    r = web.post("/v1/monitor", json={"cnpjs": [MATRIZ]}, headers=WEB)
    assert r.status_code == 200
    assert MATRIZ in {m["cnpj"] for m in web.get("/v1/monitor").json()}  # GET não exige o header


def test_lookups(web):
    assert [c["codigo"] for c in web.get("/v1/cnaes", params={"q": "padaria"}).json()] == [1091102, 4721102]
    assert [c["codigo"] for c in web.get("/v1/cnaes", params={"q": "4721-1"}).json()] == [4721102]
    mun = web.get("/v1/municipios", params={"q": "sao pa"}).json()
    assert mun[0]["codigo_ibge"] == 3550308 and mun[0]["uf"] == "SP"


def test_admin_usuarios_e_chaves(web, settings):
    novo = {"email": "ana@empresa.com", "nome": "Ana", "senha": "outra-senha-99", "plano": "free"}
    assert web.post("/v1/admin/usuarios", json=novo, headers=WEB).status_code == 201
    assert web.post("/v1/admin/usuarios", json=novo, headers=WEB).status_code == 409
    fraca = novo | {"email": "b@empresa.com", "senha": "aaaaaaaaaaaa"}
    assert web.post("/v1/admin/usuarios", json=fraca, headers=WEB).status_code == 422
    usuarios = {u["email"]: u for u in web.get("/v1/admin/usuarios").json()}
    assert usuarios["ana@empresa.com"]["plano"] == "free"

    # usuário comum não acessa o admin
    with TestClient(create_app(settings)) as ana:
        assert login(ana, "ana@empresa.com", "outra-senha-99").status_code == 200
        aceitar_termos(ana)
        assert ana.get("/v1/admin/usuarios").status_code == 403
        assert ana.get("/v1/auth/eu").json()["plano"]["id"] == "free"
        # admin promove o plano: vale na hora
        uid = usuarios["ana@empresa.com"]["id"]
        assert web.patch(f"/v1/admin/usuarios/{uid}", json={"plano": "pro"}, headers=WEB).status_code == 200
        assert ana.get("/v1/auth/eu").json()["plano"]["id"] == "pro"
        # desativar encerra a sessão
        assert web.patch(f"/v1/admin/usuarios/{uid}", json={"ativo": False}, headers=WEB).status_code == 200
        assert ana.get("/v1/auth/eu").status_code == 401

    # chave de integração: exibida uma vez, funciona, revogação vale na hora
    r = web.post("/v1/admin/chaves", json={"nome": "ERP", "plano": "pro"}, headers=WEB).json()
    chave = r["chave"]
    assert web.get(f"/v1/cnpj/{MATRIZ}", headers={"X-API-Key": chave}).status_code == 200
    assert any(k["nome"] == "ERP" for k in web.get("/v1/admin/chaves").json())
    assert web.patch(f"/v1/admin/chaves/{r['id']}", json={"ativo": False}, headers=WEB).status_code == 200
    assert web.get(f"/v1/cnpj/{MATRIZ}", headers={"X-API-Key": chave}).status_code == 401


def test_admin_nao_se_rebaixa(web, admin_user):
    r = web.patch(f"/v1/admin/usuarios/{admin_user[0]}", json={"papel": "usuario"}, headers=WEB)
    assert r.status_code == 422


def test_admin_operacao_e_auditoria(web):
    etl = web.get("/v1/admin/etl").json()
    assert etl["execucoes"][0]["status"] == "success" and etl["execucoes"][0]["etapas"]
    planos = {p["id"] for p in web.get("/v1/admin/planos").json()}
    assert {"free", "pro", "enterprise"} <= planos
    plano = {"nome": "Parceiro", "req_por_minuto": 100, "req_por_dia": 5000, "lote_max": 100,
             "export_max": 1000, "monitor_max": 50}  # fmt: skip
    assert web.put("/v1/admin/planos/parceiro", json=plano, headers=WEB).status_code == 200
    assert any(p["id"] == "parceiro" for p in web.get("/v1/admin/planos").json())
    acessos = web.get("/v1/admin/acessos", params={"caminho": MATRIZ}).json()
    assert acessos and all(MATRIZ in a["caminho"] for a in acessos)
    assert any(a["usuario_email"] == "admin@empresa.com" for a in acessos)
    assert isinstance(web.get("/v1/admin/uso").json(), list)
    assert isinstance(web.get("/v1/admin/webhooks").json(), list)


def test_troca_de_senha_e_logout(web, admin_user):
    nova = "nova-senha-456"
    r = web.post("/v1/auth/senha", json={"atual": "errada-0000", "nova": nova}, headers=WEB)
    assert r.status_code == 401
    assert web.post("/v1/auth/senha", json={"atual": SENHA, "nova": nova}, headers=WEB).status_code == 200
    assert web.post("/v1/auth/logout").status_code == 200
    assert web.get("/v1/auth/eu").status_code == 401
    assert login(web, admin_user[1], nova).status_code == 200


def test_limite_de_tentativas_de_login(web, admin_user):
    codes = [login(web, "alvo@empresa.com", "x" * 12).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_logins_com_sucesso_nao_bloqueiam(settings, admin_user):
    with TestClient(create_app(settings)) as c:
        assert all(login(c, admin_user[1], "nova-senha-456").status_code == 200 for _ in range(15))
