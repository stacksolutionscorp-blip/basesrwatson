"""Administração: usuários, chaves de API, planos, cargas do ETL, webhooks com falha e auditoria de acessos."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import errors
from pydantic import BaseModel, Field

from cnpj_api import users
from cnpj_api.auth import Cliente, generate_key
from cnpj_api.deps import cliente

router = APIRouter(prefix="/v1/admin", tags=["admin"])


async def admin(c: Annotated[Cliente, Depends(cliente)]) -> Cliente:
    if c.papel != "admin":
        raise HTTPException(403, "acesso restrito a administradores")
    return c


AdminDep = Annotated[Cliente, Depends(admin)]


class NovoUsuario(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    nome: str = Field(min_length=2, max_length=120)
    senha: str = Field(min_length=users.MIN_SENHA, max_length=200)
    papel: Literal["admin", "usuario"] = "usuario"
    plano: str = "pro"


class AlteraUsuario(BaseModel):
    nome: str | None = Field(None, min_length=2, max_length=120)
    papel: Literal["admin", "usuario"] | None = None
    ativo: bool | None = None
    plano: str | None = None
    senha: str | None = Field(None, min_length=users.MIN_SENHA, max_length=200)


class NovaChave(BaseModel):
    nome: str = Field(min_length=2, max_length=120, description="Sistema ou cliente que vai usar a chave")
    plano: str = "pro"
    usuario_id: int | None = Field(None, description="Dono da chave (monitoramentos aparecem para ele)")


class AlteraChave(BaseModel):
    ativo: bool | None = None
    plano: str | None = None
    nome: str | None = Field(None, min_length=2, max_length=120)


class Plano(BaseModel):
    nome: str
    req_por_minuto: int = Field(ge=1)
    req_por_dia: int = Field(ge=1)
    lote_max: int = Field(ge=1, le=500)
    export_max: int = Field(ge=1)
    monitor_max: int = Field(ge=0)


async def _all(request: Request, sql: str, params=None) -> list[dict]:
    async with request.app.state.pool.connection() as conn:
        return await (await conn.execute(sql, params)).fetchall()


def _forget_keys(request: Request) -> None:
    request.app.state.key_memo.clear()  # mudanças de chave/plano valem na hora neste processo


# ---------------------------------------------------------------- usuários


@router.get("/usuarios", summary="Usuários do painel")
async def listar_usuarios(request: Request, _: AdminDep):
    return await _all(
        request,
        """SELECT u.id, u.email, u.nome, u.papel, u.ativo, u.termos_versao, u.termos_aceitos_em, u.criado_em,
                  u.ultimo_login_em, k.plano_id AS plano
           FROM app.usuario u LEFT JOIN app.api_key k ON k.usuario_id = u.id AND k.pessoal
           ORDER BY u.id""",
    )


@router.post("/usuarios", status_code=201, summary="Criar usuário")
async def criar_usuario(body: NovoUsuario, request: Request, _: AdminDep):
    try:
        async with request.app.state.pool.connection() as conn:
            uid = await users.create_user(conn, body.email, body.nome, body.senha, body.papel, body.plano)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except errors.UniqueViolation as exc:
        raise HTTPException(409, "já existe usuário com este e-mail") from exc
    except errors.ForeignKeyViolation as exc:
        raise HTTPException(422, f"plano inexistente: {body.plano}") from exc
    return {"id": uid}


@router.patch("/usuarios/{usuario_id}", summary="Alterar usuário (nome, papel, ativo, plano, senha)")
async def alterar_usuario(usuario_id: int, body: AlteraUsuario, request: Request, eu: AdminDep):
    if usuario_id == eu.usuario_id and (body.ativo is False or body.papel == "usuario"):
        raise HTTPException(422, "você não pode desativar nem rebaixar a própria conta")
    sets, params = [], []
    for col in ("nome", "papel", "ativo"):
        if (v := getattr(body, col)) is not None:
            sets.append(f"{col} = %s")
            params.append(v)
    if body.senha is not None:
        try:
            users.validate_password(body.senha)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        sets.append("senha_hash = %s")
        params.append(users.hash_password(body.senha))
    async with request.app.state.pool.connection() as conn, conn.transaction():
        if sets:
            cur = await conn.execute(f"UPDATE app.usuario SET {', '.join(sets)} WHERE id = %s", (*params, usuario_id))
            if cur.rowcount == 0:
                raise HTTPException(404, "usuário não encontrado")
        if body.plano is not None:
            try:
                await conn.execute(
                    "UPDATE app.api_key SET plano_id = %s WHERE usuario_id = %s AND pessoal", (body.plano, usuario_id)
                )
            except errors.ForeignKeyViolation as exc:
                raise HTTPException(422, f"plano inexistente: {body.plano}") from exc
        if body.ativo is False or body.senha is not None:
            await conn.execute("DELETE FROM app.sessao WHERE usuario_id = %s", (usuario_id,))
    _forget_keys(request)
    return {"ok": True}


# ---------------------------------------------------------------- chaves de API


@router.get("/chaves", summary="Chaves de API de integração")
async def listar_chaves(request: Request, _: AdminDep):
    return await _all(
        request,
        """SELECT k.id, k.nome, k.prefixo, k.plano_id AS plano, k.ativo, k.criado_em, k.usuario_id,
                  u.email AS usuario_email,
                  (SELECT max(criado_em) FROM app.access_log l WHERE l.api_key_id = k.id) AS ultimo_uso_em
           FROM app.api_key k LEFT JOIN app.usuario u ON u.id = k.usuario_id
           WHERE NOT k.pessoal
           ORDER BY k.id""",
    )


@router.post("/chaves", status_code=201, summary="Criar chave de API (exibida uma única vez)")
async def criar_chave(body: NovaChave, request: Request, _: AdminDep):
    key, prefixo, digest = generate_key()
    try:
        rows = await _all(
            request,
            "INSERT INTO app.api_key (nome, prefixo, hash, plano_id, usuario_id) VALUES (%s, %s, %s, %s, %s) "
            "RETURNING id",
            (body.nome, prefixo, digest, body.plano, body.usuario_id),
        )
    except errors.ForeignKeyViolation as exc:
        raise HTTPException(422, "plano ou usuário inexistente") from exc
    return {"id": rows[0]["id"], "chave": key, "prefixo": prefixo}


@router.patch("/chaves/{chave_id}", summary="Revogar/reativar chave ou trocar plano")
async def alterar_chave(chave_id: int, body: AlteraChave, request: Request, _: AdminDep):
    sets, params = [], []
    for col, field in (("ativo", "ativo"), ("plano_id", "plano"), ("nome", "nome")):
        if (v := getattr(body, field)) is not None:
            sets.append(f"{col} = %s")
            params.append(v)
    if not sets:
        return {"ok": True}
    try:
        async with request.app.state.pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE app.api_key SET {', '.join(sets)} WHERE id = %s AND NOT pessoal", (*params, chave_id)
            )
    except errors.ForeignKeyViolation as exc:
        raise HTTPException(422, f"plano inexistente: {body.plano}") from exc
    if cur.rowcount == 0:
        raise HTTPException(404, "chave não encontrada")
    _forget_keys(request)
    return {"ok": True}


# ---------------------------------------------------------------- planos


@router.get("/planos", summary="Planos e limites")
async def listar_planos(request: Request, _: AdminDep):
    return await _all(request, "SELECT * FROM app.plano ORDER BY req_por_minuto")


@router.put("/planos/{plano_id}", summary="Criar ou alterar plano")
async def salvar_plano(plano_id: str, body: Plano, request: Request, _: AdminDep):
    await _all(
        request,
        """INSERT INTO app.plano (id, nome, req_por_minuto, req_por_dia, lote_max, export_max, monitor_max)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, req_por_minuto = EXCLUDED.req_por_minuto,
               req_por_dia = EXCLUDED.req_por_dia, lote_max = EXCLUDED.lote_max,
               export_max = EXCLUDED.export_max, monitor_max = EXCLUDED.monitor_max
           RETURNING id""",
        (plano_id, body.nome, body.req_por_minuto, body.req_por_dia, body.lote_max, body.export_max, body.monitor_max),
    )
    _forget_keys(request)
    return {"ok": True}


# ---------------------------------------------------------------- operação


@router.get("/etl", summary="Últimas cargas do ETL com etapas")
async def etl(request: Request, _: AdminDep, limite: Annotated[int, Query(ge=1, le=100)] = 10):
    runs = await _all(
        request,
        """SELECT id, referencia, status, iniciado_em, finalizado_em,
                  extract(epoch FROM coalesce(finalizado_em, now()) - iniciado_em)::int AS duracao_s, erro
           FROM ops.etl_run ORDER BY id DESC LIMIT %s""",
        (limite,),
    )
    if runs:
        steps = await _all(
            request,
            """SELECT run_id, etapa, arquivo, linhas, linhas_rejeitadas, duracao_ms, status, erro
               FROM ops.etl_step WHERE run_id = ANY(%s) ORDER BY id""",
            ([r["id"] for r in runs],),
        )
        for r in runs:
            r["etapas"] = [s for s in steps if s["run_id"] == r["id"]]
    return {"base_servida": request.app.state.referencia, "execucoes": runs}


@router.get("/webhooks", summary="Entregas de webhook com problema")
async def webhooks_com_falha(request: Request, _: AdminDep):
    return await _all(
        request,
        """SELECT e.id, e.status, e.tentativas, e.ultimo_status_http, e.ultimo_erro, e.proxima_tentativa_em,
                  w.url, k.nome AS chave, a.cnpj, a.tipo, a.referencia
           FROM app.webhook_entrega e
           JOIN app.webhook w ON w.id = e.webhook_id
           JOIN app.api_key k ON k.id = w.api_key_id
           JOIN app.alteracao a ON a.id = e.alteracao_id
           WHERE e.status = 'falhou' OR (e.status = 'pendente' AND e.tentativas > 0)
           ORDER BY e.id DESC LIMIT 200""",
    )


@router.get("/uso", summary="Consumo por chave/usuário")
async def uso_geral(request: Request, _: AdminDep, dias: Annotated[int, Query(ge=1, le=90)] = 30):
    return await _all(
        request,
        """SELECT k.id AS api_key_id, k.nome, k.pessoal, k.plano_id AS plano, u.email AS usuario_email,
                  count(l.id) AS requisicoes, count(l.id) FILTER (WHERE l.status >= 400) AS erros,
                  max(l.criado_em) AS ultimo_acesso
           FROM app.api_key k
           LEFT JOIN app.usuario u ON u.id = k.usuario_id
           LEFT JOIN app.access_log l ON l.api_key_id = k.id AND l.criado_em >= current_date - %s
           GROUP BY k.id, u.email ORDER BY requisicoes DESC, k.id""",
        (dias - 1,),
    )


@router.get("/acessos", summary="Auditoria: log de acesso (LGPD)")
async def acessos(
    request: Request,
    _: AdminDep,
    usuario_id: int | None = None,
    api_key_id: int | None = None,
    caminho: Annotated[str | None, Query(description="Trecho do caminho, ex.: um CNPJ")] = None,
    de: date | None = None,
    ate: date | None = None,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    where, params = ["true"], []
    if usuario_id is not None:
        where.append("l.usuario_id = %s")
        params.append(usuario_id)
    if api_key_id is not None:
        where.append("l.api_key_id = %s")
        params.append(api_key_id)
    if caminho:
        where.append("l.caminho LIKE %s")
        params.append(f"%{caminho.replace('%', '').replace('_', '')}%")
    if de:
        where.append("l.criado_em >= %s")
        params.append(de)
    if ate:
        where.append("l.criado_em < %s::date + 1")
        params.append(ate)
    return await _all(
        request,
        f"""SELECT l.criado_em, l.metodo, l.caminho, l.consulta, l.status, l.duracao_ms, host(l.ip) AS ip,
                   l.usuario_id, u.email AS usuario_email, l.api_key_id, k.nome AS chave
            FROM app.access_log l
            LEFT JOIN app.usuario u ON u.id = l.usuario_id
            LEFT JOIN app.api_key k ON k.id = l.api_key_id
            WHERE {" AND ".join(where)}
            ORDER BY l.id DESC LIMIT %s""",
        (*params, limite),
    )


@router.get("/alertas", summary="Alertas operacionais enviados")
async def alertas(request: Request, _: AdminDep):
    return await _all(request, "SELECT tipo, chave, mensagem, enviado_em FROM app.alerta ORDER BY id DESC LIMIT 100")
