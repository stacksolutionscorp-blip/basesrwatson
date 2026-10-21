"""Prospecção de leads para consórcio."""

import csv
import io
from datetime import date
from typing import Annotated, Literal

from cnpj_core import clean
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field

from cnpj_api import leads
from cnpj_api.deps import ClienteDep, valid_cnpj
from cnpj_api.runtime import LIVE

router = APIRouter(prefix="/v1/leads", tags=["leads"])


def filtros(
    lat: float | None = None,
    lng: float | None = None,
    raio_km: Annotated[float | None, Query(description="Raio a partir de lat/lng (máx. 300)")] = None,
    municipio_ibge: Annotated[list[int], Query()] = [],  # noqa: B006
    segmento: Annotated[str | None, Query(description="pesados | frota | imoveis | agro")] = None,
    cnae: Annotated[list[int], Query(description="CNAEs adicionais")] = [],  # noqa: B006
    somente_cnae_principal: bool = False,
    porte: Annotated[list[int], Query(description="1 ME, 3 EPP, 5 demais")] = [],  # noqa: B006
    capital_min: float | None = None,
    idade_min_anos: float | None = None,
    com_telefone: bool = True,
    so_celular: bool = False,
    com_email: bool = False,
    incluir_mei: bool = True,
    ocultar_trabalhados: Annotated[bool, Query(description="Esconde leads que já têm status na carteira")] = True,
    q: str | None = None,
) -> leads.FiltrosLead:
    f = leads.FiltrosLead(
        lat,
        lng,
        raio_km,
        municipio_ibge,
        segmento,
        cnae,
        somente_cnae_principal,
        porte,
        capital_min,
        idade_min_anos,
        com_telefone,
        so_celular,
        com_email,
        incluir_mei,
        ocultar_trabalhados,
        q,
    )
    try:
        f.validate()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return f


FiltrosDep = Annotated[leads.FiltrosLead, Depends(filtros)]


async def _buscar(request: Request, f: leads.FiltrosLead, limit: int, offset: int) -> list[dict]:
    sql, params = leads.build_query(f, limit, offset)
    async with request.app.state.pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
        dec = await leads.decisores(conn, rows)
    hoje = date.today()
    cnaes = f.cnaes()
    return [leads.present(r, dec[r["cnpj_basico"]], cnaes, hoje) for r in rows]


@router.get("/config", summary="Centro padrão, raio e perfis de segmento")
async def config(request: Request, _: ClienteDep):
    s = request.app.state.settings
    lat, lng = (float(x) for x in s.leads_centro.split(","))
    codigos = sorted({c for seg in leads.SEGMENTOS.values() for c in seg["cnaes"]})
    descricoes: dict[int, str] = {}
    async with request.app.state.pool.connection() as conn:
        tem_base = (await (await conn.execute(f"SELECT to_regclass('{LIVE}.cnae') IS NOT NULL AS ok")).fetchone())["ok"]
        if tem_base:
            rows = await (
                await conn.execute(f"SELECT codigo, descricao FROM {LIVE}.cnae WHERE codigo = ANY(%s)", (codigos,))
            ).fetchall()
            descricoes = {r["codigo"]: r["descricao"] for r in rows}
    return {
        "centro": {"lat": lat, "lng": lng, "nome": s.leads_centro_nome},
        "raio_km": s.leads_raio_km,
        "segmentos": [
            {
                "id": k,
                "nome": v["nome"],
                "consorcio": v["consorcio"],
                "cnaes": [{"codigo": c, "descricao": descricoes.get(c)} for c in v["cnaes"]],
            }
            for k, v in leads.SEGMENTOS.items()
        ],
        "status": list(leads.STATUS),
    }


@router.get("/busca", summary="Buscar leads (ordenados pelo score)")
async def busca(
    request: Request,
    _: ClienteDep,
    f: FiltrosDep,
    pagina: Annotated[int, Query(ge=1, le=500)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 25,
):
    """Só empresas ativas. Sempre exclui CNPJs, telefones e e-mails da lista "não contatar"."""
    rows = await _buscar(request, f, por_pagina + 1, (pagina - 1) * por_pagina)
    return {
        "resultados": rows[:por_pagina],
        "paginacao": {"pagina": pagina, "por_pagina": por_pagina, "tem_mais": len(rows) > por_pagina},
    }


EXPORT_COLS = [
    "cnpj",
    "razao_social",
    "nome_fantasia",
    "score",
    "decisores",
    "telefone_1",
    "telefone_2",
    "whatsapp",
    "email",
    "atividade",
    "municipio",
    "uf",
    "bairro",
    "endereco",
    "cep",
    "porte",
    "capital_social",
    "idade_anos",
    "distancia_km",
    "status",
]


def _linha(r: dict) -> dict:
    tels = r["telefones"]
    return {
        "cnpj": r["cnpj_formatado"],
        "razao_social": r["razao_social"],
        "nome_fantasia": r["nome_fantasia"],
        "score": r["score"],
        "decisores": "; ".join(f"{d['nome']} ({d['qualificacao']})" for d in r["decisores"]),
        "telefone_1": tels[0]["numero"] if tels else "",
        "telefone_2": tels[1]["numero"] if len(tels) > 1 else "",
        "whatsapp": next((t["whatsapp"] for t in tels if t["whatsapp"]), ""),
        "email": r["email"] or "",
        "atividade": f"{r['cnae_principal']['codigo']} {r['cnae_principal']['descricao'] or ''}".strip(),
        "municipio": r["municipio"],
        "uf": r["uf"],
        "bairro": r["bairro"],
        "endereco": r["endereco"],
        "cep": r["cep"],
        "porte": r["porte"],
        "capital_social": r["capital_social"],
        "idade_anos": r["idade_anos"],
        "distancia_km": r["distancia_km"],
        "status": r["status"],
    }


@router.get("/export", summary="Exportar leads (CSV/XLSX) para planilha ou CRM")
async def export(
    request: Request,
    cliente: ClienteDep,
    f: FiltrosDep,
    formato: Literal["csv", "xlsx"] = "csv",
    limite: Annotated[int, Query(ge=1)] = 1000,
):
    limite = min(limite, cliente.plano.export_max)
    rows = [_linha(r) for r in await _buscar(request, f, limite, 0)]
    if formato == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_COLS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
        return StreamingResponse(
            iter(["﻿" + buf.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
        )
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("leads")
    ws.append(EXPORT_COLS)
    for r in rows:
        ws.append([r[c] for c in EXPORT_COLS])
    out = io.BytesIO()
    wb.save(out)
    return Response(
        out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="leads.xlsx"'},
    )


# ---------------------------------------------------------------- carteira


class AtualizaLead(BaseModel):
    status: Literal["novo", "contatado", "interessado", "proposta", "fechado", "sem_interesse"]
    nota: str | None = Field(None, max_length=2000)
    proximo_contato: date | None = None


@router.put("/{cnpj}", summary="Atualizar status/anotação de um lead")
async def atualizar(cnpj: str, body: AtualizaLead, request: Request, cliente: ClienteDep):
    c = valid_cnpj(cnpj)
    async with request.app.state.pool.connection() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO app.lead (cnpj, status, responsavel_id, nota, proximo_contato)
               VALUES (%(c)s, %(s)s, %(u)s, %(n)s, %(p)s)
               ON CONFLICT (cnpj) DO UPDATE SET status = EXCLUDED.status,
                   responsavel_id = coalesce(EXCLUDED.responsavel_id, app.lead.responsavel_id),
                   nota = coalesce(EXCLUDED.nota, app.lead.nota),
                   proximo_contato = EXCLUDED.proximo_contato, atualizado_em = now()""",
            {"c": c, "s": body.status, "u": cliente.usuario_id, "n": body.nota, "p": body.proximo_contato},
        )
        await conn.execute(
            "INSERT INTO app.lead_evento (cnpj, usuario_id, status, nota) VALUES (%s, %s, %s, %s)",
            (c, cliente.usuario_id, body.status, body.nota),
        )
    return {"ok": True}


@router.get("/carteira", summary="Leads trabalhados (com status)")
async def carteira(
    request: Request,
    _: ClienteDep,
    status: Annotated[list[str], Query()] = [],  # noqa: B006
    pagina: Annotated[int, Query(ge=1)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=200)] = 50,
):
    estados = status or [s for s in leads.STATUS if s != "novo"]
    sql = f"""
WITH alvo AS (
    SELECT e.cnpj, {leads.score_sql(None)} AS score, NULL::float8 AS distancia_km, lx.atualizado_em
    FROM app.lead lx
    JOIN {LIVE}.estabelecimento e ON e.cnpj = lx.cnpj
    JOIN {LIVE}.empresa emp ON emp.cnpj_basico = e.cnpj_basico
    LEFT JOIN {LIVE}.simples s ON s.cnpj_basico = e.cnpj_basico
    WHERE lx.status = ANY(%(st)s)
    ORDER BY lx.atualizado_em DESC
    LIMIT %(limit)s OFFSET %(offset)s
)
{leads.DETALHE.format(fonte=f"alvo a JOIN {LIVE}.estabelecimento e ON e.cnpj = a.cnpj")}
ORDER BY a.atualizado_em DESC
"""
    params = {"st": estados, "limit": por_pagina + 1, "offset": (pagina - 1) * por_pagina}
    async with request.app.state.pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
        dec = await leads.decisores(conn, rows)
        resumo = await (await conn.execute("SELECT status, count(*) AS n FROM app.lead GROUP BY status")).fetchall()
    hoje = date.today()
    return {
        "resultados": [leads.present(r, dec[r["cnpj_basico"]], [], hoje) for r in rows[:por_pagina]],
        "paginacao": {"pagina": pagina, "por_pagina": por_pagina, "tem_mais": len(rows) > por_pagina},
        "totais": {r["status"]: r["n"] for r in resumo},
    }


@router.get("/{cnpj}/historico", summary="Histórico de status e anotações do lead")
async def historico(cnpj: str, request: Request, _: ClienteDep):
    c = valid_cnpj(cnpj)
    async with request.app.state.pool.connection() as conn:
        return await (
            await conn.execute(
                """SELECT ev.criado_em, ev.status, ev.nota, u.nome AS usuario
                   FROM app.lead_evento ev LEFT JOIN app.usuario u ON u.id = ev.usuario_id
                   WHERE ev.cnpj = %s ORDER BY ev.id DESC""",
                (c,),
            )
        ).fetchall()


# ---------------------------------------------------------------- não contatar


class NaoContatar(BaseModel):
    cnpj: str | None = None
    telefone: str | None = None
    email: str | None = None
    motivo: str | None = Field(None, max_length=500)


@router.post("/nao-contatar", status_code=201, summary="Registrar pedido de não contato")
async def nao_contatar(body: NaoContatar, request: Request, cliente: ClienteDep):
    """Bloqueia o CNPJ, o telefone e/ou o e-mail em todas as buscas e exportações futuras."""
    cnpj = valid_cnpj(body.cnpj) if body.cnpj else None
    tel = clean(body.telefone or "") or None
    email = (body.email or "").strip().lower() or None
    if not (cnpj or tel or email):
        raise HTTPException(422, "informe CNPJ, telefone ou e-mail")
    async with request.app.state.pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute(
                """INSERT INTO app.nao_contatar (cnpj, telefone, email, motivo, usuario_id)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (cnpj, tel, email, body.motivo, cliente.usuario_id),
            )
        ).fetchone()
        if cnpj:  # some da prospecção e fica registrado na carteira
            await conn.execute(
                """INSERT INTO app.lead (cnpj, status, responsavel_id, nota) VALUES (%s, 'sem_interesse', %s, %s)
                   ON CONFLICT (cnpj) DO UPDATE SET status = 'sem_interesse', atualizado_em = now()""",
                (cnpj, cliente.usuario_id, "pediu para não ser contatado"),
            )
            await conn.execute(
                "INSERT INTO app.lead_evento (cnpj, usuario_id, status, nota) VALUES (%s, %s, 'sem_interesse', %s)",
                (cnpj, cliente.usuario_id, f"não contatar: {body.motivo or 'sem motivo informado'}"),
            )
    return {"id": row["id"]}


@router.get("/nao-contatar", summary="Lista de não contatar")
async def listar_nao_contatar(request: Request, _: ClienteDep):
    async with request.app.state.pool.connection() as conn:
        return await (
            await conn.execute(
                """SELECT n.id, n.cnpj, n.telefone, n.email, n.motivo, n.criado_em, u.nome AS usuario
                   FROM app.nao_contatar n LEFT JOIN app.usuario u ON u.id = n.usuario_id
                   ORDER BY n.id DESC LIMIT 1000"""
            )
        ).fetchall()


@router.delete("/nao-contatar/{item_id}", status_code=204, summary="Remover da lista de não contatar")
async def remover_nao_contatar(item_id: int, request: Request, _: ClienteDep):
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute("DELETE FROM app.nao_contatar WHERE id = %s", (item_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "item não encontrado")
    return Response(status_code=204)
