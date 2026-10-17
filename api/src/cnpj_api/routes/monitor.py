import secrets
from typing import Annotated

import httpx
from cnpj_core import clean, is_valid
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from cnpj_api import webhooks
from cnpj_api.deps import ClienteDep, valid_cnpj
from cnpj_api.runtime import LIVE
from cnpj_api.schemas import Alteracao, MonitorEntrada, MonitorItem, Webhook, WebhookEntrada

router = APIRouter(prefix="/v1", tags=["monitoramento"])


@router.post("/monitor", summary="Monitorar CNPJs")
async def adicionar(body: MonitorEntrada, request: Request, cliente: ClienteDep):
    """A cada atualização mensal da Receita, mudanças de situação, endereço ou quadro societário
    destes CNPJs geram um registro no histórico e um POST nos webhooks cadastrados."""
    limpos = {clean(c) for c in body.cnpjs}
    invalidos = sorted(c for c in limpos if not is_valid(c))
    validos = sorted(limpos - set(invalidos))
    async with request.app.state.pool.connection() as conn, conn.transaction():
        existentes = {
            r["cnpj"]
            for r in await (
                await conn.execute(f"SELECT cnpj FROM {LIVE}.estabelecimento WHERE cnpj = ANY(%s)", (validos,))
            ).fetchall()
        }
        atual = (
            await (
                await conn.execute("SELECT count(*) AS n FROM app.monitor WHERE api_key_id = %s", (cliente.id,))
            ).fetchone()
        )["n"]
        novos = await (
            await conn.execute(
                """SELECT c FROM unnest(%s::text[]) c
                   WHERE NOT EXISTS (SELECT 1 FROM app.monitor m WHERE m.api_key_id = %s AND m.cnpj = c)""",
                (sorted(existentes), cliente.id),
            )
        ).fetchall()
        novos = [r["c"] for r in novos]
        if atual + len(novos) > cliente.plano.monitor_max:
            raise HTTPException(422, f"seu plano permite monitorar até {cliente.plano.monitor_max} CNPJs")
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO app.monitor (api_key_id, cnpj) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                [(cliente.id, c) for c in novos],
            )
    return {
        "adicionados": novos,
        "ja_monitorados": sorted(existentes - set(novos)),
        "nao_encontrados": sorted(set(validos) - existentes),
        "invalidos": invalidos,
    }


@router.get("/monitor", response_model=list[MonitorItem], summary="CNPJs monitorados")
async def listar(
    request: Request,
    cliente: ClienteDep,
    pagina: Annotated[int, Query(ge=1)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    async with request.app.state.pool.connection() as conn:
        return await (
            await conn.execute(
                "SELECT cnpj, criado_em FROM app.monitor WHERE api_key_id = %s ORDER BY criado_em, cnpj "
                "LIMIT %s OFFSET %s",
                (cliente.id, por_pagina, (pagina - 1) * por_pagina),
            )
        ).fetchall()


@router.delete("/monitor/{cnpj}", status_code=204, summary="Parar de monitorar")
async def remover(cnpj: str, request: Request, cliente: ClienteDep):
    c = valid_cnpj(cnpj)
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute("DELETE FROM app.monitor WHERE api_key_id = %s AND cnpj = %s", (cliente.id, c))
    if cur.rowcount == 0:
        raise HTTPException(404, "CNPJ não está sendo monitorado")
    return Response(status_code=204)


@router.get("/monitor/{cnpj}/historico", response_model=list[Alteracao], summary="Histórico de alterações")
async def historico(cnpj: str, request: Request, cliente: ClienteDep):
    c = valid_cnpj(cnpj)
    async with request.app.state.pool.connection() as conn:
        monitorado = await (
            await conn.execute("SELECT 1 FROM app.monitor WHERE api_key_id = %s AND cnpj = %s", (cliente.id, c))
        ).fetchone()
        if not monitorado:
            raise HTTPException(404, "CNPJ não está sendo monitorado por esta chave")
        return await (
            await conn.execute("SELECT * FROM app.alteracao WHERE cnpj = %s ORDER BY detectado_em DESC, id DESC", (c,))
        ).fetchall()


@router.post("/webhooks", response_model=Webhook, status_code=201, summary="Cadastrar webhook")
async def criar_webhook(body: WebhookEntrada, request: Request, cliente: ClienteDep):
    """O segredo é mostrado só agora. Use-o para validar ``X-CNPJ-Signature`` em cada POST recebido."""
    try:
        await webhooks.check_url(body.url, request.app.state.settings.webhook_allow_private)
    except webhooks.UrlNaoPermitida as exc:
        raise HTTPException(422, str(exc)) from exc
    segredo = secrets.token_urlsafe(24)
    async with request.app.state.pool.connection() as conn:
        row = await (
            await conn.execute(
                "INSERT INTO app.webhook (api_key_id, url, segredo) VALUES (%s, %s, %s) "
                "RETURNING id, url, ativo, criado_em",
                (cliente.id, body.url, segredo),
            )
        ).fetchone()
    return row | {"segredo": segredo}


@router.get("/webhooks", response_model=list[Webhook], summary="Webhooks cadastrados")
async def listar_webhooks(request: Request, cliente: ClienteDep):
    async with request.app.state.pool.connection() as conn:
        return await (
            await conn.execute(
                "SELECT id, url, ativo, criado_em FROM app.webhook WHERE api_key_id = %s ORDER BY id", (cliente.id,)
            )
        ).fetchall()


@router.delete("/webhooks/{webhook_id}", status_code=204, summary="Remover webhook")
async def remover_webhook(webhook_id: int, request: Request, cliente: ClienteDep):
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute("DELETE FROM app.webhook WHERE id = %s AND api_key_id = %s", (webhook_id, cliente.id))
    if cur.rowcount == 0:
        raise HTTPException(404, "webhook não encontrado")
    return Response(status_code=204)


@router.post("/webhooks/{webhook_id}/teste", summary="Enviar um evento de teste")
async def testar_webhook(webhook_id: int, request: Request, cliente: ClienteDep):
    """Envia agora um evento ``cnpj.alterado`` fictício (id 0) para validar a integração."""
    async with request.app.state.pool.connection() as conn:
        w = await (
            await conn.execute(
                "SELECT url, segredo FROM app.webhook WHERE id = %s AND api_key_id = %s", (webhook_id, cliente.id)
            )
        ).fetchone()
    if not w:
        raise HTTPException(404, "webhook não encontrado")
    data = {"evento": webhooks.EVENTO, "id": 0, "cnpj": "11222333000181", "tipo": "situacao", "referencia": "teste",
            "antes": {"situacao": 2}, "depois": {"situacao": 8}, "detectado_em": None, "teste": True}  # fmt: skip
    client: httpx.AsyncClient = request.app.state.http
    status, erro = await webhooks.post(
        client, w["url"], w["segredo"], data, request.app.state.settings.webhook_allow_private
    )
    return {"entregue": erro is None, "status_http": status, "erro": erro}
