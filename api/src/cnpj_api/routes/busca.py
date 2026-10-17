import csv
import io
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook

from cnpj_api import search
from cnpj_api.deps import ClienteDep, FiltrosDep
from cnpj_api.schemas import ListaEstabelecimentos

router = APIRouter(prefix="/v1", tags=["busca"])

EXPORT_COLUMNS = [
    "cnpj", "matriz", "razao_social", "nome_fantasia", "situacao", "data_inicio", "cnae_principal", "porte",
    "capital_social", "municipio", "uf", "cep", "lat", "lng", "distancia_km",
]  # fmt: skip


@router.get("/busca", response_model=ListaEstabelecimentos, summary="Busca com filtros combinados")
async def busca(
    request: Request,
    _: ClienteDep,
    f: FiltrosDep,
    pagina: Annotated[int, Query(ge=1, le=1000)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Filtros por CNAE, UF, município, raio em km, situação, porte, capital, data de abertura,
    Simples/MEI e texto. Com raio, os resultados vêm ordenados por distância."""
    sql, params = search.build_query(f, por_pagina + 1, (pagina - 1) * por_pagina)
    async with request.app.state.pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    return {
        "resultados": [search.present(r) for r in rows[:por_pagina]],
        "paginacao": {"pagina": pagina, "por_pagina": por_pagina, "tem_mais": len(rows) > por_pagina},
    }


async def _rows(request: Request, f: search.Filtros, limit: int) -> AsyncIterator[dict]:
    sql, params = search.build_query(f, limit)
    async with request.app.state.pool.connection() as conn, conn.transaction():
        async with conn.cursor(name="export") as cur:  # cursor no servidor: não carrega tudo na memória
            await cur.execute(sql, params)
            while batch := await cur.fetchmany(2000):
                for row in batch:
                    yield search.present(row)


@router.get("/export", summary="Exportação CSV/XLSX dos resultados de busca")
async def export(
    request: Request,
    cliente: ClienteDep,
    f: FiltrosDep,
    formato: Literal["csv", "xlsx"] = "csv",
    limite: Annotated[int | None, Query(ge=1, description="Máximo de linhas (limitado pelo plano)")] = None,
):
    """Mesmos filtros de /v1/busca. CSV separado por ';' com BOM (abre direto no Excel)."""
    maximo = cliente.plano.export_max
    if limite is not None and limite > maximo:
        raise HTTPException(422, f"seu plano permite exportar até {maximo} linhas")
    limit = limite or maximo

    if formato == "csv":

        async def gen() -> AsyncIterator[bytes]:
            yield "﻿".encode()
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            async for row in _rows(request, f, limit):
                writer.writerow(row)
                if buf.tell() > 64 * 1024:
                    yield buf.getvalue().encode()
                    buf.seek(0)
                    buf.truncate()
            yield buf.getvalue().encode()

        return StreamingResponse(gen(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": 'attachment; filename="empresas.csv"'})  # fmt: skip

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("empresas")
    ws.append(EXPORT_COLUMNS)
    async for row in _rows(request, f, limit):
        ws.append([row[c] for c in EXPORT_COLUMNS])
    out = io.BytesIO()
    wb.save(out)
    return Response(
        out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="empresas.xlsx"'},
    )
