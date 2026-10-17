"""Fluxo de monitoramento de ponta a ponta: monitorar → nova carga mensal → diff → webhook assinado."""

import asyncio
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import psycopg
import pytest
from cnpj_api import webhooks
from cnpj_api.runtime import make_pool
from cnpj_etl import demo
from cnpj_etl.demo import cnpj, estab, write_zip
from conftest import load

MATRIZ = "11222333000181"
FILIAL = "".join(cnpj("11222333", "0002"))


@pytest.fixture
def receiver():
    """Servidor HTTP local que guarda os POSTs recebidos."""
    received: list[tuple[dict, bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((dict(self.headers), body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/hook", received
    server.shutdown()


def test_monitorar_detectar_e_notificar(client, auth, settings, receiver, tmp_path):
    url, received = receiver

    # 1. monitorar e cadastrar webhook
    r = client.post("/v1/monitor", json={"cnpjs": [MATRIZ, FILIAL, "11222333000182", "11444777000161"]}, headers=auth)
    assert r.json() == {"adicionados": sorted([MATRIZ, FILIAL]), "ja_monitorados": [],
                        "nao_encontrados": ["11444777000161"], "invalidos": ["11222333000182"]}  # fmt: skip
    assert client.post("/v1/monitor", json={"cnpjs": [MATRIZ]}, headers=auth).json()["ja_monitorados"] == [MATRIZ]
    assert {m["cnpj"] for m in client.get("/v1/monitor", headers=auth).json()} == {MATRIZ, FILIAL}

    hook = client.post("/v1/webhooks", json={"url": url}, headers=auth)
    assert hook.status_code == 201
    segredo = hook.json()["segredo"]
    assert client.get("/v1/webhooks", headers=auth).json()[0]["segredo"] is None  # só aparece na criação

    teste = client.post(f"/v1/webhooks/{hook.json()['id']}/teste", headers=auth).json()
    assert teste["entregue"] is True and received[-1][0]["X-CNPJ-Event"] == "cnpj.alterado"
    received.clear()

    # 2. nova carga: matriz baixada, filial mudou de endereço, sócio PF saiu
    release = demo.make_release(tmp_path / "2026-10")
    write_zip(release / "Estabelecimentos0.zip", [
        estab("11222333", "0001", fantasia="PADARIA SÃO JOÃO", situacao="08", secundarias="4721102,5611203"),
        estab("11222333", "0002", fantasia="PADARIA FILIAL", logradouro="RUA NOVA", numero="99",
              municipio="6001", uf="RJ", cep="20040003"),
        demo.ESTABELECIMENTOS_0[2],
    ], nul=True)  # fmt: skip
    write_zip(release / "Socios0.zip", [s for s in demo.SOCIOS_0 if not s.startswith('"11222333";"2"')])
    load(settings.database_url, release, "2026-10")

    # 3. a API percebe o swap sozinha (NOTIFY) e passa a servir a base nova
    for _ in range(50):
        if client.get("/health").json()["referencia"] == "2026-10":
            break
        time.sleep(0.1)
    perfil = client.get(f"/v1/cnpj/{MATRIZ}", headers=auth).json()
    assert perfil["referencia"] == "2026-10" and perfil["situacao"]["descricao"] == "BAIXADA"  # cache invalidado

    # 4. histórico
    hist = {a["tipo"]: a for a in client.get(f"/v1/monitor/{MATRIZ}/historico", headers=auth).json()}
    assert set(hist) == {"situacao", "socios"}
    assert hist["situacao"]["antes"]["situacao"] == 2 and hist["situacao"]["depois"]["situacao"] == 8
    assert len(hist["socios"]["antes"]) == 2 and len(hist["socios"]["depois"]) == 1
    hist_filial = client.get(f"/v1/monitor/{FILIAL}/historico", headers=auth).json()
    assert {a["tipo"] for a in hist_filial} == {"endereco", "socios"}
    assert next(a for a in hist_filial if a["tipo"] == "endereco")["depois"]["logradouro"] == "RUA NOVA"

    # 5. worker entrega os webhooks assinados
    async def deliver():
        pool = make_pool(settings)
        await pool.open(wait=True)
        try:
            async with httpx.AsyncClient() as http:
                return await webhooks.deliver_due(pool, http, allow_private=True)
        finally:
            await pool.close()

    assert asyncio.run(deliver()) == 4
    assert len(received) == 4
    for headers, body in received:
        expected = "sha256=" + hmac.new(segredo.encode(), body, hashlib.sha256).hexdigest()
        assert headers["X-CNPJ-Signature"] == expected
    eventos = {(json.loads(b)["cnpj"], json.loads(b)["tipo"]) for _, b in received}
    assert eventos == {(MATRIZ, "situacao"), (MATRIZ, "socios"), (FILIAL, "endereco"), (FILIAL, "socios")}
    with psycopg.connect(settings.database_url) as c:
        assert c.execute("SELECT count(*) FROM app.webhook_entrega WHERE status = 'entregue'").fetchone()[0] == 4
    assert asyncio.run(deliver()) == 0  # nada pendente

    # 6. parar de monitorar
    assert client.delete(f"/v1/monitor/{FILIAL}", headers=auth).status_code == 204
    assert client.get(f"/v1/monitor/{FILIAL}/historico", headers=auth).status_code == 404


def test_webhook_falho_e_reagendado(settings, loaded_db):
    with psycopg.connect(loaded_db, autocommit=True) as c:
        kid = c.execute("SELECT id FROM app.api_key ORDER BY id LIMIT 1").fetchone()[0]
        wid = c.execute(
            "INSERT INTO app.webhook (api_key_id, url, segredo) "
            "VALUES (%s, 'http://127.0.0.1:9/nada', 's') RETURNING id",
            (kid,),
        ).fetchone()[0]
        aid = c.execute("SELECT id FROM app.alteracao ORDER BY id LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO app.webhook_entrega (webhook_id, alteracao_id) VALUES (%s, %s)", (wid, aid))

    async def deliver():
        pool = make_pool(settings)
        await pool.open(wait=True)
        try:
            async with httpx.AsyncClient(timeout=2) as http:
                return await webhooks.deliver_due(pool, http, allow_private=True)
        finally:
            await pool.close()

    assert asyncio.run(deliver()) == 1
    with psycopg.connect(loaded_db) as c:
        status, tentativas, prox = c.execute(
            "SELECT status, tentativas, proxima_tentativa_em > now() FROM app.webhook_entrega WHERE webhook_id = %s",
            (wid,),
        ).fetchone()
    assert (status, tentativas, prox) == ("pendente", 1, True)
