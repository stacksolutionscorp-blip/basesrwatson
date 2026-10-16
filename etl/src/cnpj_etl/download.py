"""Download resumível e idempotente dos ZIPs."""

import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from cnpj_etl.discover import Release, RemoteFile

log = logging.getLogger("cnpj_etl")

ATTEMPTS = 5


def download_file(client: httpx.Client, remote: RemoteFile, dest_dir: Path) -> Path:
    dest = dest_dir / remote.name
    part = dest.with_name(dest.name + ".part")
    head = client.head(remote.url, follow_redirects=True)
    head.raise_for_status()
    size = int(head.headers.get("content-length", 0)) or None

    if dest.exists() and (size is None or dest.stat().st_size == size) and zipfile.is_zipfile(dest):
        log.info("já baixado: %s", remote.name)
        return dest

    for attempt in range(1, ATTEMPTS + 1):
        try:
            pos = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={pos}-"} if pos else {}
            with client.stream("GET", remote.url, headers=headers, follow_redirects=True) as r:
                if r.status_code == 416:  # .part já completo
                    break
                r.raise_for_status()
                mode = "ab" if r.status_code == 206 else "wb"
                with part.open(mode) as fh:
                    for chunk in r.iter_bytes(1024 * 1024):
                        fh.write(chunk)
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if attempt == ATTEMPTS:
                raise
            wait = 2**attempt
            log.warning("%s: %s — nova tentativa em %ss", remote.name, exc, wait)
            time.sleep(wait)

    if size is not None and part.stat().st_size != size:
        raise RuntimeError(f"{remote.name}: tamanho {part.stat().st_size} ≠ esperado {size}")
    if not zipfile.is_zipfile(part):
        raise RuntimeError(f"{remote.name}: arquivo baixado não é um ZIP válido")
    part.rename(dest)
    log.info("baixado: %s (%.1f MB)", remote.name, dest.stat().st_size / 1e6)
    return dest


def download_release(
    release: Release, dest_dir: Path, concurrency: int, client: httpx.Client | None = None
) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60, read=300))
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(pool.map(lambda f: download_file(client, f, dest_dir), release.files))
    finally:
        if own:
            client.close()
