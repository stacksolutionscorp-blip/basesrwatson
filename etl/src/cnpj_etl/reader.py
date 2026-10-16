"""Leitura em streaming dos ZIPs da Receita em lotes de DataFrames (tudo string).

- Descompacta sem gravar o CSV em disco.
- Converte cp1252/latin-1 → UTF-8 (cp1252 é superconjunto prático do latin-1
  e decodifica corretamente aspas/travessões vindos de sistemas Windows).
- Remove bytes NUL e normaliza CRLF.
- Corta lotes apenas em fronteira de registro (``"\\n"``), já que todos os
  campos da Receita são entre aspas e podem conter quebras de linha.
- Divide os campos por ``";"`` em vez de usar um parser CSV genérico: aspas
  internas não escapadas (comuns nos arquivos) quebrariam o parser e ele
  completaria linhas curtas com null sem avisar.
"""

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import polars as pl

READ_CHUNK = 8 * 1024 * 1024
_BOUNDARY = b'"\n"'
_RECORD_SPLIT = re.compile(r'(?<=")\n(?=")')


@dataclass
class Batch:
    df: pl.DataFrame
    malformed: int  # registros descartados (nº de campos errado)


def decode(raw: bytes) -> str:
    return raw.replace(b"\x00", b"").replace(b"\r\n", b"\n").decode("cp1252", errors="replace")


def iter_raw_chunks(path: Path, batch_bytes: int) -> Iterator[bytes]:
    """Blocos de bytes do (único) CSV dentro do ZIP, cortados em fim de registro."""
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise ValueError(f"{path.name}: esperado 1 arquivo no ZIP, há {len(members)}")
        with zf.open(members[0]) as fh:
            buf = bytearray()
            while True:
                chunk = fh.read(min(READ_CHUNK, batch_bytes))
                if not chunk:
                    if buf:
                        yield bytes(buf)
                    return
                buf += chunk
                if len(buf) >= batch_bytes:
                    cut = buf.rfind(_BOUNDARY)
                    if cut != -1:  # sem fronteira: registro maior que o lote, continua lendo
                        yield bytes(buf[: cut + 2])  # inclui '"\n'
                        del buf[: cut + 2]


def parse(text: str, columns: list[str]) -> Batch:
    """Divide em registros (``"\\n"``) e campos (``";"``), vetorizado no polars.

    Registros sem aspas nas pontas ou com nº de campos diferente do layout são
    descartados e contados em ``malformed`` — nunca preenchidos com null.
    """
    records = pl.Series("r", _RECORD_SPLIT.split(text.strip("\n")), dtype=pl.String)
    shaped = records.str.starts_with('"') & records.str.ends_with('"')
    fields = records.str.slice(1, records.str.len_chars() - 2).str.split('";"')
    df = pl.DataFrame({"f": fields, "ok": shaped}).filter(pl.col("ok") & (pl.col("f").list.len() == len(columns)))
    out = df.select(pl.col("f").list.get(i).alias(c) for i, c in enumerate(columns))
    return Batch(out, records.len() - out.height)


def iter_batches(path: Path, columns: list[str], batch_bytes: int) -> Iterator[Batch]:
    for raw in iter_raw_chunks(path, batch_bytes):
        text = decode(raw)
        if text.strip():
            yield parse(text, columns)
