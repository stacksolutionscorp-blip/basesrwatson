"""Autenticação e rate limit por plano.

Dois caminhos levam ao mesmo ``Cliente``:
- integrações: API key no header ``X-API-Key`` (ou ``Authorization: Bearer``);
- painel web: cookie de sessão do usuário, que usa a chave "pessoal" dele (monitoramento,
  webhooks e limites funcionam igual). Requisições que alteram dados exigem o header
  ``X-Requested-With: cnpj-web`` (proteção contra CSRF) e o aceite da versão vigente dos termos.
"""

import hashlib
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

KEY_PREFIX = "cnpj_"
_LOOKUP_TTL = 60  # segundos que uma chave validada fica em memória
SESSION_COOKIE = "cnpj_sessao"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "cnpj-web"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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
    id: int  # api_key.id (a chave pessoal, no caso de sessão)
    nome: str
    prefixo: str
    plano: Plano
    usuario_id: int | None = None
    papel: str | None = None  # admin | usuario (só quando há usuário)
    via_sessao: bool = False
    termos_versao: str | None = None


def generate_key() -> tuple[str, str, bytes]:
    """Gera (chave, prefixo, hash). Só o hash é gravado; a chave é mostrada uma única vez."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, key[:12], hash_key(key)


def hash_key(key: str) -> bytes:
    return hashlib.sha256(key.encode()).digest()


token_hash = hash_key  # tokens de sessão são guardados do mesmo jeito (sha256)


def _extract(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


_COLS = """k.id, k.nome, k.prefixo, p.id AS plano_id, p.req_por_minuto, p.req_por_dia, p.lote_max,
       p.export_max, p.monitor_max, u.id AS usuario_id, u.papel, u.termos_versao"""
_SQL = f"""
SELECT {_COLS}
FROM app.api_key k JOIN app.plano p ON p.id = k.plano_id
LEFT JOIN app.usuario u ON u.id = k.usuario_id
WHERE k.hash = %s AND k.ativo AND (u.id IS NULL OR u.ativo)
"""
_SESSION_SQL = f"""
SELECT {_COLS}
FROM app.sessao s
JOIN app.usuario u ON u.id = s.usuario_id AND u.ativo
JOIN app.api_key k ON k.usuario_id = u.id AND k.pessoal AND k.ativo
JOIN app.plano p ON p.id = k.plano_id
WHERE s.token_hash = %s AND s.expira_em > now()
"""


def _cliente(row: dict, via_sessao: bool) -> Cliente:
    plano = Plano(row["plano_id"], row["req_por_minuto"], row["req_por_dia"], row["lote_max"],
                  row["export_max"], row["monitor_max"])  # fmt: skip
    return Cliente(row["id"], row["nome"], row["prefixo"], plano, row["usuario_id"], row["papel"], via_sessao,
                   row["termos_versao"])  # fmt: skip


async def _lookup(request: Request, key: str) -> Cliente | None:
    memo: dict = request.app.state.key_memo
    digest = hash_key(key)
    hit = memo.get(digest)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    async with request.app.state.pool.connection() as conn:
        row = await (await conn.execute(_SQL, (digest,))).fetchone()
    cliente = _cliente(row, False) if row else None
    memo[digest] = (cliente, time.monotonic() + _LOOKUP_TTL)
    return cliente


async def _session(request: Request, token: str) -> Cliente | None:
    async with request.app.state.pool.connection() as conn:
        row = await (await conn.execute(_SESSION_SQL, (token_hash(token),))).fetchone()
    return _cliente(row, True) if row else None


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


async def authenticate(request: Request, exige_termos: bool = True) -> Cliente:
    """Valida chave ou sessão, aplica CSRF/termos/rate limit e registra o cliente para o log de acesso."""
    key = _extract(request)
    token = request.cookies.get(SESSION_COOKIE)
    if key:
        cliente = await _lookup(request, key)
        if cliente is None:
            raise HTTPException(401, "API key inválida ou revogada", headers={"WWW-Authenticate": "Bearer"})
    elif token:
        cliente = await _session(request, token)
        if cliente is None:
            raise HTTPException(401, "sessão expirada; entre novamente")
        if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise HTTPException(403, "requisição sem o header X-Requested-With")
    else:
        raise HTTPException(401, "informe a API key no header X-API-Key", headers={"WWW-Authenticate": "Bearer"})
    request.state.cliente = cliente
    if exige_termos and cliente.via_sessao and cliente.termos_versao != request.app.state.termos_versao:
        raise HTTPException(403, "aceite os termos de uso vigentes para continuar",
                            headers={"X-Termos-Pendentes": request.app.state.termos_versao})  # fmt: skip
    request.state.rate_headers = await _rate_limit(request, cliente)
    return cliente


async def require_client(request: Request) -> Cliente:
    return await authenticate(request)
