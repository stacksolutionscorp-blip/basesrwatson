"""Autenticação por API key (header ``X-API-Key`` ou ``Authorization: Bearer``) e rate limit por plano."""

import hashlib
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

KEY_PREFIX = "cnpj_"
_LOOKUP_TTL = 60  # segundos que uma chave validada fica em memória


@dataclass(frozen=True)
class Plano:
    id: str
    req_por_minuto: int
    req_por_dia: int
    lote_max: int
    export_max: int
    monitor_max: int


@dataclass(frozen=True)
class Cliente:
    id: int
    nome: str
    prefixo: str
    plano: Plano


def generate_key() -> tuple[str, str, bytes]:
    """Gera (chave, prefixo, hash). Só o hash é gravado; a chave é mostrada uma única vez."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, key[:12], hash_key(key)


def hash_key(key: str) -> bytes:
    return hashlib.sha256(key.encode()).digest()


def _extract(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


_SQL = """
SELECT k.id, k.nome, k.prefixo, p.id AS plano_id, p.req_por_minuto, p.req_por_dia,
       p.lote_max, p.export_max, p.monitor_max
FROM app.api_key k JOIN app.plano p ON p.id = k.plano_id
WHERE k.hash = %s AND k.ativo
"""


async def _lookup(request: Request, key: str) -> Cliente | None:
    memo: dict = request.app.state.key_memo
    digest = hash_key(key)
    hit = memo.get(digest)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    async with request.app.state.pool.connection() as conn:
        row = await (await conn.execute(_SQL, (digest,))).fetchone()
    cliente = None
    if row:
        plano = Plano(row["plano_id"], row["req_por_minuto"], row["req_por_dia"], row["lote_max"],
                      row["export_max"], row["monitor_max"])  # fmt: skip
        cliente = Cliente(row["id"], row["nome"], row["prefixo"], plano)
    memo[digest] = (cliente, time.monotonic() + _LOOKUP_TTL)
    return cliente


async def _rate_limit(request: Request, cliente: Cliente) -> dict[str, str]:
    redis = request.app.state.cache.redis
    if redis is None:
        return {}
    now = int(time.time())
    minute_key = f"rl:{cliente.id}:m:{now // 60}"
    day_key = f"rl:{cliente.id}:d:{now // 86400}"
    try:
        pipe = redis.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, 120)
        pipe.incr(day_key)
        pipe.expire(day_key, 172800)
        per_min, _, per_day, _ = await pipe.execute()
    except RedisError:
        return {}  # sem Redis, não bloqueia o cliente
    p = cliente.plano
    headers = {
        "X-RateLimit-Limit": str(p.req_por_minuto),
        "X-RateLimit-Remaining": str(max(0, p.req_por_minuto - per_min)),
        "X-RateLimit-Limit-Day": str(p.req_por_dia),
        "X-RateLimit-Remaining-Day": str(max(0, p.req_por_dia - per_day)),
    }
    if per_min > p.req_por_minuto:
        raise HTTPException(429, "limite de requisições por minuto excedido",
                            headers=headers | {"Retry-After": str(60 - now % 60)})  # fmt: skip
    if per_day > p.req_por_dia:
        raise HTTPException(429, "limite diário de requisições excedido",
                            headers=headers | {"Retry-After": str(86400 - now % 86400)})  # fmt: skip
    return headers


async def require_client(request: Request) -> Cliente:
    """Dependência FastAPI: valida a chave, aplica o rate limit e registra o cliente para o log."""
    key = _extract(request)
    if not key:
        raise HTTPException(401, "informe a API key no header X-API-Key", headers={"WWW-Authenticate": "Bearer"})
    cliente = await _lookup(request, key)
    if cliente is None:
        raise HTTPException(401, "API key inválida ou revogada", headers={"WWW-Authenticate": "Bearer"})
    request.state.cliente = cliente
    request.state.rate_headers = await _rate_limit(request, cliente)
    return cliente
