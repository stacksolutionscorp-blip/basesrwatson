import asyncio
import logging
from typing import Annotated

import psycopg
import typer
import uvicorn
from cnpj_core.schema import init_db

from cnpj_api import maintenance, users, webhooks
from cnpj_api.auth import generate_key
from cnpj_api.config import get_settings
from cnpj_api.runtime import make_pool

app = typer.Typer(help="CNPJ Intel API", no_args_is_help=True)


@app.callback()
def _setup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    workers: int = 1,
    reload: Annotated[bool, typer.Option(help="Recarregar ao editar o código (desenvolvimento)")] = False,
) -> None:
    """Sobe a API (documentação em /docs)."""
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        init_db(conn)
    uvicorn.run("cnpj_api.main:app_factory", factory=True, host=host, port=port, workers=workers, reload=reload,
                proxy_headers=True)  # fmt: skip


@app.command("criar-chave")
def criar_chave(
    nome: Annotated[str, typer.Option(help="Cliente ou sistema que vai usar a chave")],
    plano: Annotated[str, typer.Option(help="free | pro | enterprise")] = "pro",
) -> None:
    """Gera uma API key. Ela é exibida uma única vez; guarde-a."""
    key, prefixo, digest = generate_key()
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        init_db(conn)
        if not conn.execute("SELECT 1 FROM app.plano WHERE id = %s", (plano,)).fetchone():
            raise typer.BadParameter(f"plano inexistente: {plano}")
        kid = conn.execute(
            "INSERT INTO app.api_key (nome, prefixo, hash, plano_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (nome, prefixo, digest, plano),
        ).fetchone()[0]
    typer.echo(f"id={kid} plano={plano}")
    typer.echo(key)


@app.command("criar-usuario")
def criar_usuario(
    email: Annotated[str, typer.Option()],
    nome: Annotated[str, typer.Option()],
    admin: Annotated[bool, typer.Option("--admin", help="Administrador do painel")] = False,
    plano: str = "pro",
    senha: Annotated[str | None, typer.Option(help="Se omitida, será perguntada")] = None,
) -> None:
    """Cria um usuário do painel web (use --admin para o primeiro acesso)."""
    if senha is None:
        senha = typer.prompt("senha", hide_input=True, confirmation_prompt=True)
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        init_db(conn)
        try:
            uid = users.create_user_sync(conn, email, nome, senha, "admin" if admin else "usuario", plano)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        except psycopg.errors.UniqueViolation as exc:
            raise typer.BadParameter("já existe usuário com este e-mail") from exc
    typer.echo(f"usuário {uid} criado ({'admin' if admin else 'usuario'})")


@app.command("listar-chaves")
def listar_chaves() -> None:
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT id, nome, prefixo, plano_id, ativo, criado_em, ultimo_uso_em FROM app.api_key ORDER BY id"
        ).fetchall()
    for kid, nome, prefixo, plano, ativo, criado, _ in rows:
        typer.echo(f"{kid:>4} {prefixo}… {plano:<10} {'ativa' if ativo else 'revogada':<8} {criado:%Y-%m-%d} {nome}")


@app.command("revogar-chave")
def revogar_chave(id: int) -> None:
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        n = conn.execute("UPDATE app.api_key SET ativo = false WHERE id = %s", (id,)).rowcount
    typer.echo("revogada (efeito em até 60 s)" if n else "chave não encontrada")


@app.command()
def worker(intervalo: float = 10.0) -> None:
    """Entrega webhooks pendentes e roda a manutenção (retenção de logs, alertas). Serviço separado da API."""

    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        init_db(conn)  # o worker pode subir antes da API num banco novo

    async def main():
        pool = make_pool(settings)
        await pool.open(wait=True)
        try:
            await asyncio.gather(
                webhooks.run_worker(pool, intervalo, settings.webhook_allow_private),
                maintenance.run_maintenance(pool),
            )
        finally:
            await pool.close()

    asyncio.run(main())


if __name__ == "__main__":
    app()
