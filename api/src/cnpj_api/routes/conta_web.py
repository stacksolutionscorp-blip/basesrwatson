"""Login, sessão e termos de uso do painel web."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from cnpj_api import users
from cnpj_api.auth import SESSION_COOKIE, Cliente, authenticate, token_hash
from cnpj_api.netutil import valid_ip

router = APIRouter(prefix="/v1", tags=["conta"])


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    senha: str = Field(min_length=1, max_length=200)


class Aceite(BaseModel):
    versao: str


class TrocaSenha(BaseModel):
    atual: str
    nova: str = Field(min_length=users.MIN_SENHA, max_length=200)


async def sessao_sem_termos(request: Request) -> Cliente:
    cliente = await authenticate(request, exige_termos=False)
    if not cliente.via_sessao:
        raise HTTPException(400, "rota exclusiva do painel web (sessão)")
    return cliente


SessaoDep = Annotated[Cliente, Depends(sessao_sem_termos)]


def _attempts_key(request: Request, email: str) -> str:
    ip = request.client.host if request.client else "?"
    return f"login:falhas:{email.strip().lower()}:{ip}"


async def _blocked(request: Request, key: str) -> bool:
    try:
        n = await request.app.state.cache.redis.get(key)
    except RedisError:
        return False
    return int(n or 0) >= request.app.state.settings.login_max_tentativas


async def _register_failure(request: Request, key: str) -> None:
    """Só senhas erradas contam; o bloqueio dura 15 minutos a partir da última falha."""
    try:
        redis = request.app.state.cache.redis
        await redis.incr(key)
        await redis.expire(key, 900)
    except RedisError:
        pass


@router.post("/auth/login", summary="Entrar no painel (cria cookie de sessão)")
async def login(body: Login, request: Request, response: Response):
    attempts = _attempts_key(request, body.email)
    if await _blocked(request, attempts):
        raise HTTPException(429, "muitas tentativas; aguarde 15 minutos")
    async with request.app.state.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id, senha_hash, ativo FROM app.usuario WHERE lower(email) = lower(%s)", (body.email.strip(),)
            )
        ).fetchone()
        if not row or not row["ativo"] or not users.verify_password(body.senha, row["senha_hash"]):
            await _register_failure(request, attempts)
            raise HTTPException(401, "e-mail ou senha incorretos")
        settings = request.app.state.settings
        ip = valid_ip(request.client.host if request.client else None)
        token = await users.create_session(
            conn, row["id"], settings.session_hours, ip, request.headers.get("user-agent")
        )
    try:
        await request.app.state.cache.redis.delete(attempts)
    except RedisError:
        pass
    request.state.usuario_id = row["id"]
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"ok": True}


@router.post("/auth/logout", summary="Sair (encerra a sessão)")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        async with request.app.state.pool.connection() as conn:
            await conn.execute("DELETE FROM app.sessao WHERE token_hash = %s", (token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/eu", summary="Usuário logado, plano e situação dos termos")
async def eu(request: Request, cliente: SessaoDep):
    async with request.app.state.pool.connection() as conn:
        u = await (
            await conn.execute(
                "SELECT id, email, nome, papel, termos_versao, termos_aceitos_em FROM app.usuario WHERE id = %s",
                (cliente.usuario_id,),
            )
        ).fetchone()
    p = cliente.plano
    return u | {
        "termos_vigentes": request.app.state.termos_versao,
        "termos_pendentes": u["termos_versao"] != request.app.state.termos_versao,
        "plano": {
            "id": p.id,
            "req_por_minuto": p.req_por_minuto,
            "req_por_dia": p.req_por_dia,
            "lote_max": p.lote_max,
            "export_max": p.export_max,
            "monitor_max": p.monitor_max,
        },
    }


@router.get("/termos", summary="Termos de uso vigentes (público)")
async def termos(request: Request):
    return {"versao": request.app.state.termos_versao, "texto": request.app.state.termos_texto}


@router.post("/auth/termos", summary="Aceitar os termos de uso vigentes")
async def aceitar_termos(body: Aceite, request: Request, cliente: SessaoDep):
    if body.versao != request.app.state.termos_versao:
        raise HTTPException(409, "versão dos termos desatualizada; recarregue a página")
    async with request.app.state.pool.connection() as conn:
        await conn.execute(
            "UPDATE app.usuario SET termos_versao = %s, termos_aceitos_em = now() WHERE id = %s",
            (body.versao, cliente.usuario_id),
        )
    return {"ok": True}


@router.post("/auth/senha", summary="Trocar a própria senha")
async def trocar_senha(body: TrocaSenha, request: Request, cliente: SessaoDep):
    try:
        users.validate_password(body.nova)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with request.app.state.pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute("SELECT senha_hash FROM app.usuario WHERE id = %s", (cliente.usuario_id,))
        ).fetchone()
        if not users.verify_password(body.atual, row["senha_hash"]):
            raise HTTPException(401, "senha atual incorreta")
        await conn.execute(
            "UPDATE app.usuario SET senha_hash = %s WHERE id = %s", (users.hash_password(body.nova), cliente.usuario_id)
        )
        # encerra as outras sessões do usuário
        token = request.cookies.get(SESSION_COOKIE, "")
        await conn.execute(
            "DELETE FROM app.sessao WHERE usuario_id = %s AND token_hash <> %s", (cliente.usuario_id, token_hash(token))
        )
    return {"ok": True}
