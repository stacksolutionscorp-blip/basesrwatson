"""Entrega de webhooks de alteração (fila em app.webhook_entrega).

Cada POST leva o corpo JSON assinado em ``X-CNPJ-Signature: sha256=<hex>``
(HMAC-SHA256 com o segredo do webhook). Falhas são retentadas com backoff;
após a última tentativa a entrega fica como ``falhou``.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("cnpj_api")

BACKOFF = [timedelta(minutes=m) for m in (1, 5, 30, 120, 360, 1440)]
EVENTO = "cnpj.alterado"

_FILA = """
SELECT we.id, we.tentativas, w.url, w.segredo,
       a.id AS alteracao_id, a.cnpj, a.referencia, a.tipo, a.antes, a.depois, a.detectado_em
FROM app.webhook_entrega we
JOIN app.webhook w ON w.id = we.webhook_id
JOIN app.alteracao a ON a.id = we.alteracao_id
WHERE we.status = 'pendente' AND we.proxima_tentativa_em <= now() AND w.ativo
ORDER BY we.proxima_tentativa_em
LIMIT %s
FOR UPDATE OF we SKIP LOCKED
"""


def payload(row: dict) -> dict:
    return {
        "evento": EVENTO,
        "id": row["alteracao_id"],
        "cnpj": row["cnpj"],
        "tipo": row["tipo"],
        "referencia": row["referencia"],
        "antes": row["antes"],
        "depois": row["depois"],
        "detectado_em": row["detectado_em"],
    }


def sign(segredo: str, body: bytes) -> str:
    return "sha256=" + hmac.new(segredo.encode(), body, hashlib.sha256).hexdigest()


class UrlNaoPermitida(ValueError):
    pass


async def check_url(url: str, allow_private: bool) -> None:
    """Impede SSRF: recusa destinos em loopback, rede privada, link-local (metadados de nuvem) etc."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UrlNaoPermitida("URL deve ser http(s) com host")
    if allow_private:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443)
    except OSError as exc:
        raise UrlNaoPermitida(f"host não resolve: {parts.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UrlNaoPermitida(f"destino não permitido (endereço interno {ip})")


async def post(
    client: httpx.AsyncClient, url: str, segredo: str, data: dict, allow_private: bool = False
) -> tuple[int | None, str | None]:
    """Envia um evento. Devolve (status HTTP, erro)."""
    try:
        await check_url(url, allow_private)
    except UrlNaoPermitida as exc:
        return None, str(exc)
    body = json.dumps(data, default=str, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "X-CNPJ-Event": data["evento"],
               "X-CNPJ-Signature": sign(segredo, body)}  # fmt: skip
    try:
        r = await client.post(url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return r.status_code, None if r.is_success else f"HTTP {r.status_code}"


async def deliver_due(
    pool: AsyncConnectionPool, client: httpx.AsyncClient, batch: int = 50, allow_private: bool = False
) -> int:
    """Processa um lote de entregas vencidas. Devolve quantas foram tentadas."""
    async with pool.connection() as conn, conn.transaction():
        rows = await (await conn.execute(_FILA, (batch,))).fetchall()
        if not rows:
            return 0
        results = await asyncio.gather(*(post(client, r["url"], r["segredo"], payload(r), allow_private) for r in rows))
        for row, (status, erro) in zip(rows, results, strict=True):
            tentativas = row["tentativas"] + 1
            if erro is None:
                await conn.execute(
                    """UPDATE app.webhook_entrega SET status = 'entregue', tentativas = %s,
                       ultimo_status_http = %s, ultimo_erro = NULL, entregue_em = now() WHERE id = %s""",
                    (tentativas, status, row["id"]),
                )
                continue
            final = tentativas > len(BACKOFF)
            await conn.execute(
                """UPDATE app.webhook_entrega SET status = %s, tentativas = %s, ultimo_status_http = %s,
                   ultimo_erro = %s, proxima_tentativa_em = now() + %s WHERE id = %s""",
                ("falhou" if final else "pendente", tentativas, status, erro,
                 BACKOFF[min(tentativas, len(BACKOFF)) - 1], row["id"]),
            )  # fmt: skip
            log.warning("webhook %s → %s (tentativa %s)", row["url"], erro, tentativas)
    return len(rows)


async def run_worker(pool: AsyncConnectionPool, interval: float = 10.0, allow_private: bool = False) -> None:
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "cnpj-intel-webhooks/0.1"}) as client:
        while True:
            try:
                while await deliver_due(pool, client, allow_private=allow_private):
                    pass
            except Exception:
                log.exception("erro ao entregar webhooks")
            await asyncio.sleep(interval)
