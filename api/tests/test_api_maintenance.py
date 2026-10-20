import asyncio
from datetime import date, timedelta

import httpx
import psycopg
from cnpj_api.maintenance import MaintenanceSettings, pending_alerts, purge, send_alerts
from cnpj_api.runtime import make_pool


def run(settings, coro_fn):
    async def go():
        pool = make_pool(settings)
        await pool.open(wait=True)
        try:
            return await coro_fn(pool)
        finally:
            await pool.close()

    return asyncio.run(go())


def test_retencao_do_log_e_sessoes(settings, loaded_db, api_key):
    with psycopg.connect(loaded_db, autocommit=True) as c:
        c.execute(
            "INSERT INTO app.access_log (api_key_id, metodo, rota, caminho, status, duracao_ms, criado_em) "
            "VALUES (%s, 'GET', '/x', '/velho', 200, 1, now() - interval '400 days'), "
            "       (%s, 'GET', '/x', '/recente', 200, 1, now() - interval '10 days')",
            (api_key[0], api_key[0]),
        )
    removed = run(settings, lambda pool: purge(pool, 365))
    assert removed["access_log"] >= 1
    with psycopg.connect(loaded_db) as c:
        caminhos = {r[0] for r in c.execute("SELECT caminho FROM app.access_log WHERE rota = '/x'")}
    assert caminhos == {"/recente"}


def test_alertas_enviados_uma_vez(settings, loaded_db):
    with psycopg.connect(loaded_db, autocommit=True) as c:
        c.execute(
            "INSERT INTO ops.etl_run (referencia, status, erro) VALUES ('2026-11', 'failed', 'HTTP 404 no download')"
        )
    recebidos = []

    def handler(request: httpx.Request) -> httpx.Response:
        recebidos.append(request.read().decode())
        return httpx.Response(200)

    cfg = MaintenanceSettings(alert_url="https://hooks.example/alertas", etl_delay_days=40)

    async def go(pool):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await send_alerts(pool, client, cfg), await send_alerts(pool, client, cfg)

    primeiro, segundo = run(settings, go)
    assert primeiro >= 1 and segundo == 0  # não repete
    assert any("2026-11" in r and "falhou" in r for r in recebidos)


def test_alerta_de_base_atrasada(settings):
    futuro = date.today() + timedelta(days=60)
    alerts = run(settings, lambda pool: pending_alerts(pool, 40, hoje=futuro))
    assert any(t == "etl_atrasado" for t, _, _ in alerts)
