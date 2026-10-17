"""Orquestra uma carga mensal completa."""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from cnpj_etl import diff, discover, download, finalize, load
from cnpj_etl.config import Settings
from cnpj_etl.db import NEW, connect, init_db
from cnpj_etl.layouts import DATASETS, dataset_for
from cnpj_etl.runlog import RunLog, already_imported

log = logging.getLogger("cnpj_etl")


@dataclass
class RunResult:
    referencia: str
    status: str  # success | skipped
    counts: dict[str, int]


def _group(paths: list[Path]) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for p in paths:
        ds = dataset_for(p.name)
        if ds:
            out.setdefault(ds.name, []).append(p)
    return out


def run(
    settings: Settings,
    *,
    source_dir: Path | None = None,
    referencia: str | None = None,
    force: bool = False,
) -> RunResult:
    url = settings.database_url
    with connect(url, autocommit=True) as logconn, connect(url, autocommit=True) as conn:
        init_db(logconn)

        if source_dir is not None:
            release, paths = discover.local_release(source_dir, referencia or source_dir.name)
        else:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                release = discover.latest_release(client, settings.rf_base_url)
            paths = None

        if not force and already_imported(logconn, release.referencia):
            log.info("referência %s já importada; nada a fazer", release.referencia)
            return RunResult(release.referencia, "skipped", {})

        runlog = RunLog(logconn, release.referencia)
        runlog.start()
        try:
            if paths is None:
                dest = settings.data_dir / "raw" / release.referencia
                with runlog.step("download") as st:
                    paths = download.download_release(release, dest, settings.download_concurrency)
                    st.linhas = len(paths)

            groups = _group(paths)
            load.create_schema(conn)
            counts: dict[str, int] = {}
            batch_bytes = settings.batch_mb * 1024 * 1024
            for ds in DATASETS:  # auxiliares primeiro, depois as tabelas grandes
                counts[ds.name] = load.load_dataset(conn, runlog, ds, groups[ds.name], batch_bytes)

            with runlog.step("keys") as st:
                for table in finalize.PRIMARY_KEYS:
                    st.linhas_rejeitadas += finalize.add_primary_key(conn, table)
            with runlog.step("index") as st:
                st.linhas = finalize.create_indexes(url, settings.index_workers)
                finalize.analyze(conn)
            with runlog.step("check"):
                counts |= finalize.check_counts(conn, settings.min_row_ratio)  # pós-dedup
            with runlog.step("swap"):
                finalize.swap(conn, release.referencia)
            try:
                with runlog.step("diff") as st:
                    st.linhas, queued = diff.detect_changes(conn, release.referencia)
                    log.info("%s alterações em CNPJs monitorados, %s webhooks enfileirados", st.linhas, queued)
            except Exception:  # a base nova já está no ar; a falha fica registrada na etapa
                log.exception("falha ao detectar alterações")

            if source_dir is None and not settings.keep_zips:
                shutil.rmtree(settings.data_dir / "raw" / release.referencia, ignore_errors=True)
        except BaseException as exc:
            runlog.finish("failed", f"{type(exc).__name__}: {exc}")
            try:
                conn.execute(f"DROP SCHEMA IF EXISTS {NEW} CASCADE")
            except Exception:
                log.exception("não foi possível remover %s", NEW)
            raise
        runlog.finish("success")
        return RunResult(release.referencia, "success", counts)
