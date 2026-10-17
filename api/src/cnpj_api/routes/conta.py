from typing import Annotated

from fastapi import APIRouter, Query, Request

from cnpj_api.deps import ClienteDep
from cnpj_api.schemas import Uso

router = APIRouter(prefix="/v1", tags=["conta"])


@router.get("/uso", response_model=Uso, summary="Consumo da API por esta chave")
async def uso(request: Request, cliente: ClienteDep, dias: Annotated[int, Query(ge=1, le=90)] = 30):
    async with request.app.state.pool.connection() as conn:
        por_dia = await (
            await conn.execute(
                """SELECT criado_em::date AS dia, count(*) AS requisicoes,
                          count(*) FILTER (WHERE status >= 400) AS erros
                   FROM app.access_log
                   WHERE api_key_id = %s AND criado_em >= current_date - %s
                   GROUP BY 1 ORDER BY 1""",
                (cliente.id, dias - 1),
            )
        ).fetchall()
        por_rota = await (
            await conn.execute(
                """SELECT rota, count(*) AS n FROM app.access_log
                   WHERE api_key_id = %s AND criado_em >= current_date - %s
                   GROUP BY 1 ORDER BY 2 DESC""",
                (cliente.id, dias - 1),
            )
        ).fetchall()
    p = cliente.plano
    return {
        "chave": cliente.prefixo + "…",
        "plano": p.id,
        "limites": {
            "req_por_minuto": p.req_por_minuto,
            "req_por_dia": p.req_por_dia,
            "lote_max": p.lote_max,
            "export_max": p.export_max,
            "monitor_max": p.monitor_max,
        },
        "dias": por_dia,
        "por_rota": {r["rota"]: r["n"] for r in por_rota},
    }
