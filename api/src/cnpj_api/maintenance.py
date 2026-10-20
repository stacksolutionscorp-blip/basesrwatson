"""Rotinas periódicas do worker: retenção de dados e alertas operacionais.

Retenção:
- ``app.access_log``: mantido por ``API_LOG_RETENCAO_DIAS`` (padrão 365). O Marco Civil da Internet
  (art. 15) exige guardar registros de acesso a aplicações por no mínimo 6 meses.
- sessões expiradas e entregas de webhook concluídas há mais de 90 dias.

Alertas (enviados para ``ALERTA_WEBHOOK_URL`` — Slack, Discord, Teams/Power Automate ou qualquer
endpoint que aceite JSON — e sempre registrados no log e em ``app.alerta``):
- a última carga da Receita falhou;
- nenhuma carga bem-sucedida há mais de ``ALERTA_ETL_ATRASO_DIAS`` dias (a Receita publica todo mês);
- entregas de webhook esgotaram as tentativas nas últimas 24 h.
Cada alerta é enviado uma vez por ocorrência (chave única em ``app.alerta``).
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date

import httpx
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("cnpj_api")


@dataclass(frozen=True)
class MaintenanceSettings:
    log_retention_days: int = field(default_factory=lambda: int(os.environ.get("API_LOG_RETENCAO_DIAS", "365")))
    alert_url: str | None = field(default_factory=lambda: os.environ.get("ALERTA_WEBHOOK_URL") or None)
    etl_delay_days: int = field(default_factory=lambda: int(os.environ.get("ALERTA_ETL_ATRASO_DIAS", "40")))
    interval_seconds: int = field(default_factory=lambda: int(os.environ.get("MANUTENCAO_INTERVALO_S", "3600")))


async def purge(pool: AsyncConnectionPool, retention_days: int) -> dict[str, int]:
    out = {}
    async with pool.connection() as conn:
        # em lotes, para não segurar locks longos numa tabela grande
        total = 0
        while True:
            cur = await conn.execute(
                """DELETE FROM app.access_log WHERE id IN (
                       SELECT id FROM app.access_log
                       WHERE criado_em < now() - make_interval(days => %s) LIMIT 50000)""",
                (retention_days,),
            )
            total += cur.rowcount
            if cur.rowcount < 50000:
                break
        out["access_log"] = total
        out["sessoes"] = (await conn.execute("DELETE FROM app.sessao WHERE expira_em < now()")).rowcount
        out["entregas"] = (
            await conn.execute(
                "DELETE FROM app.webhook_entrega WHERE status = 'entregue' AND entregue_em < now() - interval '90 days'"
            )
        ).rowcount
    return out


async def pending_alerts(
    pool: AsyncConnectionPool, etl_delay_days: int, hoje: date | None = None
) -> list[tuple[str, str, str]]:
    """(tipo, chave, mensagem) dos alertas que ainda não foram enviados."""
    hoje = hoje or date.today()
    found: list[tuple[str, str, str]] = []
    async with pool.connection() as conn:
        last = await (
            await conn.execute("SELECT id, referencia, status, erro FROM ops.etl_run ORDER BY id DESC LIMIT 1")
        ).fetchone()
        if last and last["status"] == "failed":
            found.append(("etl_falhou", str(last["id"]),
                          f"A carga {last['referencia']} da base da Receita falhou: {last['erro']}"))  # fmt: skip
        ok = await (
            await conn.execute(
                """SELECT max(finalizado_em)::date AS dia FROM ops.etl_run
                   WHERE status = 'success' AND referencia ~ '^\\d{4}-\\d{2}$'"""
            )
        ).fetchone()
        if ok and ok["dia"] and (hoje - ok["dia"]).days > etl_delay_days:
            semana = hoje.isocalendar()
            dias = (hoje - ok["dia"]).days
            msg = (
                f"Nenhuma carga da Receita concluída há {dias} dias (última em {ok['dia']}). "
                "Verifique o serviço etl e se a Receita mudou o endereço dos arquivos (RF_BASE_URL)."
            )
            found.append(("etl_atrasado", f"{semana.year}-W{semana.week:02d}", msg))
        falhas = await (
            await conn.execute(
                """SELECT count(*) AS n, string_agg(DISTINCT w.url, ', ') AS urls
                   FROM app.webhook_entrega e JOIN app.webhook w ON w.id = e.webhook_id
                   WHERE e.status = 'falhou' AND e.proxima_tentativa_em > now() - interval '1 day'"""
            )
        ).fetchone()
        if falhas and falhas["n"]:
            msg = f"{falhas['n']} entregas de webhook esgotaram as tentativas nas últimas 24 h: {falhas['urls']}"
            found.append(("webhooks_falhando", hoje.isoformat(), msg))
        if not found:
            return []
        sent = await (
            await conn.execute(
                """SELECT tipo, chave FROM app.alerta
                   WHERE (tipo, chave) IN (SELECT * FROM unnest(%s::text[], %s::text[]))""",
                ([t for t, _, _ in found], [c for _, c, _ in found]),
            )
        ).fetchall()
    already = {(r["tipo"], r["chave"]) for r in sent}
    return [a for a in found if (a[0], a[1]) not in already]


async def send_alerts(pool: AsyncConnectionPool, client: httpx.AsyncClient, settings: MaintenanceSettings) -> int:
    alerts = await pending_alerts(pool, settings.etl_delay_days)
    for tipo, chave, mensagem in alerts:
        log.error("ALERTA [%s] %s", tipo, mensagem)
        if settings.alert_url:
            texto = f"⚠️ CNPJ Intel — {mensagem}"
            try:
                r = await client.post(settings.alert_url, json={"text": texto, "content": texto})
                r.raise_for_status()
            except httpx.HTTPError:
                log.warning("não foi possível enviar o alerta para ALERTA_WEBHOOK_URL", exc_info=True)
                continue  # tenta de novo no próximo ciclo
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.alerta (tipo, chave, mensagem) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (tipo, chave, mensagem),
            )
    return len(alerts)


async def run_maintenance(pool: AsyncConnectionPool, settings: MaintenanceSettings | None = None) -> None:
    settings = settings or MaintenanceSettings()
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                removed = await purge(pool, settings.log_retention_days)
                if any(removed.values()):
                    log.info("limpeza: %s", removed)
                await send_alerts(pool, client, settings)
            except Exception:
                log.exception("erro na manutenção periódica")
            await asyncio.sleep(settings.interval_seconds)
