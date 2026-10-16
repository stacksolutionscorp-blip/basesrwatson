"""Log de execução em ops.etl_run / ops.etl_step.

Usa uma conexão própria em autocommit, para que o log persista mesmo quando a
transação de carga é desfeita.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg

log = logging.getLogger("cnpj_etl")

# Chave do advisory lock que impede duas cargas simultâneas.
_LOCK_KEY = 0x434E504A  # "CNPJ"


class AlreadyRunning(RuntimeError):
    pass


@dataclass
class StepStats:
    linhas: int = 0
    linhas_rejeitadas: int = 0


class RunLog:
    def __init__(self, conn: psycopg.Connection, referencia: str):
        assert conn.autocommit, "RunLog precisa de conexão em autocommit"
        self.conn = conn
        self.referencia = referencia
        self.run_id: int | None = None

    def start(self) -> int:
        if not self.conn.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,)).fetchone()[0]:
            raise AlreadyRunning("já existe uma carga em andamento")
        self.run_id = self.conn.execute(
            "INSERT INTO ops.etl_run (referencia) VALUES (%s) RETURNING id", (self.referencia,)
        ).fetchone()[0]
        log.info("execução %s iniciada (referência %s)", self.run_id, self.referencia)
        return self.run_id

    def finish(self, status: str, erro: str | None = None) -> None:
        self.conn.execute(
            "UPDATE ops.etl_run SET status = %s, erro = %s, finalizado_em = now() WHERE id = %s",
            (status, erro, self.run_id),
        )
        self.conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
        log.info("execução %s finalizada: %s", self.run_id, status)

    @contextmanager
    def step(self, etapa: str, arquivo: str | None = None) -> Iterator[StepStats]:
        step_id = self.conn.execute(
            "INSERT INTO ops.etl_step (run_id, etapa, arquivo) VALUES (%s, %s, %s) RETURNING id",
            (self.run_id, etapa, arquivo),
        ).fetchone()[0]
        stats = StepStats()
        t0 = time.monotonic()
        log.info("→ %s %s", etapa, arquivo or "")
        try:
            yield stats
        except BaseException as exc:
            self._close_step(step_id, stats, t0, "failed", f"{type(exc).__name__}: {exc}")
            raise
        self._close_step(step_id, stats, t0, "success", None)
        log.info(
            "✓ %s %s: %s linhas, %s rejeitadas, %.1fs",
            etapa, arquivo or "", stats.linhas, stats.linhas_rejeitadas, time.monotonic() - t0,
        )  # fmt: skip

    def _close_step(self, step_id, stats, t0, status, erro):
        self.conn.execute(
            """UPDATE ops.etl_step
               SET linhas = %s, linhas_rejeitadas = %s, duracao_ms = %s, status = %s, erro = %s
               WHERE id = %s""",
            (
                stats.linhas,
                stats.linhas_rejeitadas,
                int((time.monotonic() - t0) * 1000),
                status,
                erro,
                step_id,
            ),
        )


def last_success(conn: psycopg.Connection) -> str | None:
    row = conn.execute(
        "SELECT referencia FROM ops.etl_run WHERE status = 'success' ORDER BY referencia DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None
