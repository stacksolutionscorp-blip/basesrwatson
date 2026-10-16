import io
import zipfile

import httpx
import pytest
from cnpj_etl.discover import RemoteFile, latest_release, local_release, parse_months, parse_zips
from cnpj_etl.download import download_file
from cnpj_etl.layouts import missing_datasets
from receita_fixture import make_release

BASE = "https://rf.example/dados/cnpj/"
ALL = (
    [f"{p}{i}.zip" for p in ("Empresas", "Estabelecimentos", "Socios") for i in range(10)]
    + ["Simples.zip", "Cnaes.zip", "Motivos.zip", "Municipios.zip", "Naturezas.zip", "Paises.zip",
       "Qualificacoes.zip"]
)  # fmt: skip


def index(links: list[str]) -> str:
    return "<html><body>" + "".join(f'<a href="{h}">{h}</a>' for h in links) + "</body></html>"


def test_parse_months_e_zips():
    html = index(["../", "2026-08/", "2026-09/", "/dados/cnpj/2026-10/", "temp/", "LEIAME.pdf"])
    assert parse_months(html) == ["2026-10", "2026-09", "2026-08"]
    zips = parse_zips(index(["Empresas0.zip", "Outro.zip", "Cnaes.zip"]), BASE + "2026-10/")
    assert zips == [
        RemoteFile("Cnaes.zip", BASE + "2026-10/Cnaes.zip"),
        RemoteFile("Empresas0.zip", BASE + "2026-10/Empresas0.zip"),
    ]


def test_missing_datasets():
    assert missing_datasets(ALL) == []
    assert missing_datasets([f for f in ALL if not f.startswith("Socios")]) == ["socio"]


def test_latest_release_ignora_mes_incompleto():
    pages = {
        BASE: index(["2026-09/", "2026-10/"]),
        BASE + "2026-10/": index(ALL[:5]),  # Receita ainda publicando
        BASE + "2026-09/": index(ALL),
    }
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=pages[str(r.url)]))
    with httpx.Client(transport=transport) as client:
        rel = latest_release(client, BASE)
    assert rel.referencia == "2026-09" and len(rel.files) == 37


def test_local_release(tmp_path):
    make_release(tmp_path)
    rel, paths = local_release(tmp_path, "2026-10")
    assert rel.referencia == "2026-10" and len(paths) == 37
    (tmp_path / "Simples.zip").unlink()
    with pytest.raises(RuntimeError, match="simples"):
        local_release(tmp_path, "2026-10")


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", "a" * 5000)
    return buf.getvalue()


class RangeServer:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.gets: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        headers = {"content-length": str(len(self.payload))}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        rng = request.headers.get("range")
        self.gets.append(rng)
        if rng:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            return httpx.Response(206, content=self.payload[start:])
        return httpx.Response(200, content=self.payload)


def test_download_retoma_de_part(tmp_path):
    payload = _zip_bytes()
    server = RangeServer(payload)
    (tmp_path / "Cnaes.zip.part").write_bytes(payload[:100])
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        dest = download_file(client, RemoteFile("Cnaes.zip", BASE + "Cnaes.zip"), tmp_path)
        assert dest.read_bytes() == payload
        assert server.gets == ["bytes=100-"]
        # segunda chamada não baixa de novo
        download_file(client, RemoteFile("Cnaes.zip", BASE + "Cnaes.zip"), tmp_path)
        assert server.gets == ["bytes=100-"]
