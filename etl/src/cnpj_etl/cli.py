import asyncio
import logging
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import httpx
import typer

from cnpj_etl import discover, finalize, pipeline
from cnpj_etl.config import get_settings
from cnpj_etl.db import connect, init_db, live_referencia
from cnpj_etl.demo import make_release
from cnpj_etl.geocode import municipios, nominatim
from cnpj_etl.runlog import last_success

app = typer.Typer(help="ETL dos Dados Abertos CNPJ da Receita Federal", no_args_is_help=True)
geo_app = typer.Typer(help="Geocodificação", no_args_is_help=True)
app.add_typer(geo_app, name="geo")

log = logging.getLogger("cnpj_etl")


@app.callback()
def _setup(verbose: Annotated[bool, typer.Option("-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


@app.command("db-init")
def db_init() -> None:
    """Cria extensões e schemas persistentes (ops, geo)."""
    with connect(get_settings().database_url, autocommit=True) as conn:
        init_db(conn)
    typer.echo("ok")


@app.command()
def run(
    source_dir: Annotated[Path | None, typer.Option(help="Usar ZIPs locais em vez de baixar da Receita")] = None,
    referencia: Annotated[str | None, typer.Option(help="AAAA-MM (com --source-dir)")] = None,
    force: Annotated[bool, typer.Option(help="Reimportar mesmo se a referência já foi carregada")] = False,
) -> None:
    """Executa uma carga completa: download → COPY → índices → verificação → swap."""
    result = pipeline.run(get_settings(), source_dir=source_dir, referencia=referencia, force=force)
    typer.echo(f"{result.referencia}: {result.status}")
    for table, n in result.counts.items():
        typer.echo(f"  {table:<20} {n:>12,}")


@app.command()
def check() -> None:
    """Mostra a publicação mais recente da Receita e a última importada."""
    s = get_settings()
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        release = discover.latest_release(client, s.rf_base_url)
    with connect(s.database_url, autocommit=True) as conn:
        init_db(conn)
        typer.echo(f"disponível na Receita: {release.referencia} ({len(release.files)} arquivos)")
        typer.echo(f"última importada:      {last_success(conn) or '-'}")
        typer.echo(f"base servida (rf):     {live_referencia(conn) or '-'}")


@app.command()
def schedule() -> None:
    """Laço para o container: verifica periodicamente e importa quando há mês novo."""
    s = get_settings()
    while True:
        try:
            pipeline.run(s)
        except Exception:
            log.exception("carga falhou")
        time.sleep(s.check_interval_hours * 3600)


@app.command()
def status(limit: int = 5) -> None:
    """Últimas execuções e suas etapas."""
    with connect(get_settings().database_url, autocommit=True) as conn:
        init_db(conn)
        runs = conn.execute(
            """SELECT id, referencia, status, iniciado_em, finalizado_em - iniciado_em, erro
               FROM ops.etl_run ORDER BY id DESC LIMIT %s""",
            (limit,),
        ).fetchall()
        for rid, ref, st, ini, dur, err in runs:
            typer.echo(f"#{rid} {ref} {st:<8} {ini:%Y-%m-%d %H:%M} dur={dur} {err or ''}")
            steps = conn.execute(
                """SELECT etapa, coalesce(arquivo, ''), linhas, linhas_rejeitadas, duracao_ms, status
                   FROM ops.etl_step WHERE run_id = %s ORDER BY id""",
                (rid,),
            ).fetchall()
            for etapa, arq, n, rej, ms, sst in steps:
                typer.echo(f"   {etapa:<8} {arq:<28} {n or 0:>12,} rej={rej or 0:<6} {(ms or 0) / 1000:>8.1f}s {sst}")


DEMO_REF = "demo"
_DEMO_MUNICIPIOS = [  # usados se geo.municipio_ibge estiver vazia (ex.: sem internet)
    (7107, 3550308, "São Paulo", "SP", -23.5329, -46.6395),
    (6001, 3304557, "Rio de Janeiro", "RJ", -22.9129, -43.2003),
    (6619, 3525904, "Jundiaí", "SP", -23.1852, -46.8974),
    (6569, 3523404, "Itatiba", "SP", -23.0035, -46.8464),
    (6291, 3509502, "Campinas", "SP", -22.9053, -47.0659),
]


@app.command()
def demo(force: Annotated[bool, typer.Option(help="Sobrescrever mesmo se houver base real carregada")] = False) -> None:
    """Carrega uma amostra sintética (formato real da Receita) para testar a plataforma em segundos."""
    s = get_settings()
    with connect(s.database_url, autocommit=True) as conn:
        init_db(conn)
        live = live_referencia(conn)
        if live not in (None, DEMO_REF) and not force:
            raise typer.BadParameter(f"a base servida é a real ({live}); use --force para substituir pela demo")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO geo.municipio_ibge VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                _DEMO_MUNICIPIOS,
            )
    with tempfile.TemporaryDirectory() as tmp:
        release = make_release(Path(tmp) / DEMO_REF, regiao_jundiai=True)
        result = pipeline.run(replace(s, min_row_ratio=0.0), source_dir=release, referencia=DEMO_REF, force=True)
    typer.echo(f"demo carregada: {sum(result.counts.values())} linhas")
    typer.echo("exemplo: CNPJ 11.222.333/0001-81 (matriz), sócio 'JOSE DA SILVA', CNAE 1091102, UF SP")
    typer.echo("leads: 6 empresas fictícias em Jundiaí, Itatiba e Campinas (menu Leads)")


@app.command()
def rollback() -> None:
    """Volta a servir a carga anterior (troca rf ↔ rf_prev)."""
    with connect(get_settings().database_url, autocommit=True) as conn:
        typer.echo(f"servindo agora: {finalize.rollback_swap(conn)}")


@geo_app.command("municipios")
def geo_municipios(
    se_vazio: Annotated[bool, typer.Option(help="Só carrega se a tabela estiver vazia")] = False,
) -> None:
    """Carrega SIAFI↔IBGE + centroides e preenche geom faltante na base viva."""
    s = get_settings()
    with connect(s.database_url, autocommit=True) as conn:
        init_db(conn)
        if se_vazio and conn.execute("SELECT EXISTS (SELECT 1 FROM geo.municipio_ibge)").fetchone()[0]:
            typer.echo("geo.municipio_ibge já carregada")
            return
        n, updated = municipios.load(conn, s.municipios_url)
    typer.echo(f"{n} municípios; {updated} estabelecimentos com centroide aplicado")


@geo_app.command("geocode")
def geo_geocode(
    limit: Annotated[int, typer.Option(help="Máximo de endereços nesta execução")] = 10_000,
    todas: Annotated[bool, typer.Option(help="Incluir empresas não ativas")] = False,
    uf: Annotated[str | None, typer.Option(help="Restringir a uma UF")] = None,
) -> None:
    """Geocodifica endereços ainda não presentes no cache, via Nominatim."""
    s = get_settings()
    with connect(s.database_url, autocommit=True) as conn:
        done, found = asyncio.run(
            nominatim.run(
                conn,
                s.nominatim_url,
                s.nominatim_user_agent,
                s.nominatim_rps,
                s.nominatim_concurrency,
                limit,
                todas=todas,
                uf=uf.upper() if uf else None,
            )
        )
    typer.echo(f"{done} consultados, {found} encontrados")


if __name__ == "__main__":
    app()
