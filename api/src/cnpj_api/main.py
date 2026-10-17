"""Aplicação FastAPI."""

import asyncio
import ipaddress
import logging
import time
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import errors as psycopg_errors
from psycopg_pool import PoolTimeout
from redis import asyncio as aioredis

from cnpj_api.config import Settings, get_settings
from cnpj_api.routes import busca, consulta, conta, monitor
from cnpj_api.runtime import Cache, listen_swaps, live_referencia, make_pool

log = logging.getLogger("cnpj_api")

DESCRIPTION = """
Consulta e investigação de empresas brasileiras a partir dos **Dados Abertos CNPJ** da Receita Federal.

**Autenticação:** envie sua chave no header `X-API-Key` (ou `Authorization: Bearer <chave>`).
Os limites do plano vêm nos headers `X-RateLimit-*`; acima deles a resposta é `429` com `Retry-After`.

**LGPD:** CPFs de sócios são exibidos apenas no formato mascarado em que a Receita os publica,
e todo acesso é registrado por chave.
"""

_NO_LOG = {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st = app.state
        st.settings = settings
        st.pool = make_pool(settings)
        await st.pool.open(wait=True, timeout=30)
        st.cache = Cache(aioredis.from_url(settings.redis_url, socket_timeout=2), settings.cache_ttl)
        st.referencia = await live_referencia(st.pool)
        st.key_memo = {}
        st.log_tasks = set()
        st.http = httpx.AsyncClient(timeout=10, headers={"User-Agent": "cnpj-intel-webhooks/0.1"})

        async def on_swap(referencia: str) -> None:
            st.referencia = referencia or await live_referencia(st.pool)
            removed = await st.cache.clear()
            log.info("nova base %s no ar; %s chaves de cache removidas", st.referencia, removed)

        listener = asyncio.create_task(listen_swaps(settings.database_url, on_swap))
        log.info("API pronta; base %s", st.referencia)
        try:
            yield
        finally:
            listener.cancel()
            if st.log_tasks:
                await asyncio.gather(*st.log_tasks, return_exceptions=True)
            await st.http.aclose()
            await st.cache.redis.aclose()
            await st.pool.close()

    app = FastAPI(
        title="CNPJ Intel API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "consulta", "description": "Perfil, filiais, sócios, grafo e lote"},
            {"name": "busca", "description": "Filtros combinados, raio geográfico e exportação"},
            {"name": "monitoramento", "description": "CNPJs acompanhados, histórico e webhooks"},
            {"name": "conta", "description": "Consumo da API"},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Limit-Day",
            "X-RateLimit-Remaining-Day",
            "Retry-After",
        ],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        for k, v in getattr(request.state, "rate_headers", {}).items():
            response.headers.setdefault(k, v)
        if request.url.path not in _NO_LOG:
            route = request.scope.get("route")
            ip = request.client.host if request.client else None
            if settings.trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
                ip = fwd.split(",")[0].strip()
            ip = _valid_ip(ip)
            cliente = getattr(request.state, "cliente", None)
            entry = (
                cliente.id if cliente else None,
                request.method,
                getattr(route, "path", request.url.path),
                request.url.path,
                request.url.query or None,
                response.status_code,
                int((time.perf_counter() - t0) * 1000),
                ip,
                request.headers.get("user-agent"),
            )
            task = asyncio.create_task(_write_log(request.app, entry))
            request.app.state.log_tasks.add(task)
            task.add_done_callback(request.app.state.log_tasks.discard)
        return response

    @app.get("/health", tags=["conta"], summary="Saúde do serviço (sem autenticação)")
    async def health(request: Request):
        st = request.app.state
        db_ok = redis_ok = False
        try:
            async with st.pool.connection() as conn:
                await conn.execute("SELECT 1")
            db_ok = True
        except Exception:
            log.warning("health: banco indisponível", exc_info=True)
        try:
            redis_ok = bool(await st.cache.redis.ping())
        except Exception:
            pass
        return {"status": "ok" if db_ok else "degradado", "banco": db_ok, "redis": redis_ok,
                "referencia": st.referencia}  # fmt: skip

    @app.exception_handler(psycopg_errors.UndefinedTable)
    async def base_nao_carregada(request: Request, exc: Exception):
        return JSONResponse(
            {"detail": "base da Receita ainda não carregada; rode a carga do ETL (cnpj-etl run ou cnpj-etl demo)"},
            status_code=503,
        )

    @app.exception_handler(psycopg_errors.QueryCanceled)
    async def tempo_esgotado(request: Request, exc: Exception):
        return JSONResponse({"detail": "a consulta excedeu o tempo limite; refine os filtros"}, status_code=504)

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def banco_indisponivel(request: Request, exc: Exception):
        log.error("banco indisponível: %s", exc)
        return JSONResponse({"detail": "banco de dados indisponível; tente novamente"}, status_code=503)

    for r in (consulta.router, busca.router, monitor.router, conta.router):
        app.include_router(r)
    return app


def _valid_ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


async def _write_log(app: FastAPI, entry: tuple) -> None:
    try:
        async with app.state.pool.connection() as conn:
            await conn.execute(
                """INSERT INTO app.access_log
                   (api_key_id, metodo, rota, caminho, consulta, status, duracao_ms, ip, user_agent)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                entry,
            )
    except Exception:
        log.warning("não foi possível gravar o log de acesso", exc_info=True)


def app_factory() -> FastAPI:  # para `uvicorn --factory cnpj_api.main:app_factory`
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
