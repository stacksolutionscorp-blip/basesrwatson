"""Recursos compartilhados: pool do Postgres, cache Redis e ouvinte do swap mensal."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis
from redis.exceptions import RedisError

from cnpj_api.config import Settings

log = logging.getLogger("cnpj_api")

LIVE = "rf"
SWAP_CHANNEL = "cnpj_swapped"


async def _configure(conn: psycopg.AsyncConnection) -> None:
    conn.row_factory = dict_row
    # Sem prepared statements no servidor: após o swap (rename de schema) os
    # planos em cache apontariam para as tabelas antigas por OID.
    conn.prepare_threshold = None


def make_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        settings.database_url,
        min_size=settings.pool_min,
        max_size=settings.pool_max,
        kwargs={
            "autocommit": True,
            # JIT ajuda consultas analíticas longas; numa API só adiciona centenas de ms de compilação.
            "options": f"-c statement_timeout={settings.statement_timeout_ms} -c jit=off",
        },
        configure=_configure,
        open=False,
    )


async def live_referencia(pool: AsyncConnectionPool) -> str | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT obj_description(oid, 'pg_namespace') AS ref FROM pg_namespace WHERE nspname = %s", (LIVE,)
            )
        ).fetchone()
    return row["ref"] if row else None


class Cache:
    """Cache JSON no Redis. Se o Redis cair, a API segue funcionando sem cache."""

    PREFIX = "cnpj:v1:"

    def __init__(self, redis: aioredis.Redis | None, ttl: int):
        self.redis = redis
        self.ttl = ttl

    async def get(self, key: str) -> Any | None:
        if self.redis is None:
            return None
        try:
            raw = await self.redis.get(self.PREFIX + key)
        except RedisError:
            log.warning("redis indisponível (get)")
            return None
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(self.PREFIX + key, json.dumps(value, default=str), ex=self.ttl)
        except RedisError:
            log.warning("redis indisponível (set)")

    async def clear(self) -> int:
        if self.redis is None:
            return 0
        n = 0
        try:
            async for key in self.redis.scan_iter(match=self.PREFIX + "*", count=1000):
                n += await self.redis.delete(key)
        except RedisError:
            log.warning("redis indisponível (clear)")
        return n


async def listen_swaps(url: str, on_swap: Callable[[str], Awaitable[None]]) -> None:
    """Escuta NOTIFY cnpj_swapped (emitido pelo ETL) e reconecta se a conexão cair."""
    delay = 1
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
                await conn.execute(f"LISTEN {SWAP_CHANNEL}")
                delay = 1
                async for note in conn.notifies():
                    await on_swap(note.payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("ouvinte de swap desconectado; nova tentativa em %ss", delay, exc_info=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
