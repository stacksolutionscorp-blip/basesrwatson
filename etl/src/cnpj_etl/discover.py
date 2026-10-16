"""Descobre a publicação mensal mais recente no índice HTML da Receita."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx

from cnpj_etl.layouts import dataset_for, missing_datasets

_MONTH = re.compile(r'href="(?:[^"]*/)?(\d{4}-\d{2})/?"', re.IGNORECASE)
_ZIP = re.compile(r'href="([^"]+\.zip)"', re.IGNORECASE)


@dataclass(frozen=True)
class RemoteFile:
    name: str
    url: str


@dataclass(frozen=True)
class Release:
    referencia: str  # AAAA-MM
    files: list[RemoteFile]


def parse_months(html: str) -> list[str]:
    return sorted(set(_MONTH.findall(html)), reverse=True)


def parse_zips(html: str, base_url: str) -> list[RemoteFile]:
    out: dict[str, RemoteFile] = {}
    for href in _ZIP.findall(html):
        name = unquote(href.rsplit("/", 1)[-1])
        if dataset_for(name):
            out[name] = RemoteFile(name, urljoin(base_url, href))
    return sorted(out.values(), key=lambda f: f.name)


def latest_release(client: httpx.Client, base_url: str, max_months: int = 3) -> Release:
    """Mês mais recente com todos os datasets publicados.

    A Receita sobe os arquivos ao longo de alguns dias; um mês incompleto é
    ignorado e o anterior é usado.
    """
    base_url = base_url if base_url.endswith("/") else base_url + "/"
    resp = client.get(base_url)
    resp.raise_for_status()
    months = parse_months(resp.text)
    if not months:
        raise RuntimeError(f"nenhuma pasta AAAA-MM encontrada em {base_url}")
    for month in months[:max_months]:
        url = urljoin(base_url, f"{month}/")
        r = client.get(url)
        r.raise_for_status()
        files = parse_zips(r.text, url)
        if not missing_datasets([f.name for f in files]):
            return Release(month, files)
    raise RuntimeError(f"nenhum dos meses {months[:max_months]} está completo")


def local_release(source_dir: Path, referencia: str) -> tuple[Release, list[Path]]:
    """Usa ZIPs já baixados (download manual ou espelho)."""
    paths = sorted(p for p in source_dir.iterdir() if p.is_file() and dataset_for(p.name))
    missing = missing_datasets([p.name for p in paths])
    if missing:
        raise RuntimeError(f"{source_dir}: faltam arquivos para {', '.join(missing)}")
    files = [RemoteFile(p.name, p.resolve().as_uri()) for p in paths]
    return Release(referencia, files), paths
