"""Geocodificação em lote via Nominatim, com cache em geo.geocode.

Use uma instância própria (serviço ``nominatim`` do docker-compose). A instância
pública do OSM proíbe geocodificação em massa; para ela mantenha
NOMINATIM_RPS=1 e NOMINATIM_CONCURRENCY=1 e use só para volumes pequenos.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
import psycopg

from cnpj_etl.db import LIVE

log = logging.getLogger("cnpj_etl")

_SEM_NUMERO = {"SN", "S/N", "S N", "SEM NUMERO", "0", "00", "000"}
RETRY_NOT_FOUND_DAYS = 90


@dataclass(frozen=True)
class Address:
    endereco_hash: bytes
    tipo_logradouro: str | None
    logradouro: str | None
    numero: str | None
    bairro: str | None
    cep: str | None
    cidade: str | None
    uf: str | None

    def text(self) -> str:
        rua = " ".join(p for p in (self.tipo_logradouro, self.logradouro) if p)
        cep = f"{self.cep[:5]}-{self.cep[5:]}" if self.cep and len(self.cep) == 8 else (self.cep or "")
        return f"{rua}, {self.numero or 'S/N'} - {self.bairro or ''}, {self.cidade or ''}/{self.uf or ''}, {cep}"

    def street_query(self) -> dict[str, str] | None:
        if not self.logradouro or not self.cidade:
            return None
        rua = " ".join(p for p in (self.tipo_logradouro, self.logradouro) if p)
        numero = (self.numero or "").strip().upper()
        street = f"{numero} {rua}" if numero and numero not in _SEM_NUMERO else rua
        return {"street": street, "city": self.cidade, "state": self.uf or "", "country": "Brasil"}

    def postcode_query(self) -> dict[str, str] | None:
        if not self.cep or len(self.cep) != 8:
            return None
        return {"postalcode": f"{self.cep[:5]}-{self.cep[5:]}", "country": "Brasil"}


@dataclass(frozen=True)
class Result:
    lat: float
    lng: float
    precisao: int  # 2 CEP, 3 rua, 4 número


def precision_of(item: dict) -> int | None:
    """Precisão a partir da resposta jsonv2; None se o resultado é só cidade/bairro."""
    address = item.get("address") or {}
    if address.get("house_number"):
        return 4
    if item.get("category") == "highway" or item.get("addresstype") == "road":
        return 3
    if item.get("addresstype") == "postcode" or item.get("type") == "postcode":
        return 2
    return None


class RateLimiter:
    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


class Geocoder:
    def __init__(self, client: httpx.AsyncClient, rps: float, concurrency: int):
        self.client = client
        self.limiter = RateLimiter(rps)
        self.sem = asyncio.Semaphore(max(1, concurrency))

    async def _search(self, params: dict[str, str]) -> dict | None:
        q = {**params, "format": "jsonv2", "addressdetails": "1", "limit": "1"}
        for attempt in range(4):
            async with self.sem:
                await self.limiter.wait()
                try:
                    r = await self.client.get("/search", params=q)
                except httpx.TransportError:
                    r = None
            if r is not None and r.status_code == 200:
                data = r.json()
                return data[0] if data else None
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
            await asyncio.sleep(2 ** (attempt + 1))
        raise RuntimeError("Nominatim indisponível após várias tentativas")

    async def geocode(self, addr: Address) -> Result | None:
        for params in (addr.street_query(), addr.postcode_query()):
            if params is None:
                continue
            item = await self._search(params)
            if item and (prec := precision_of(item)) is not None:
                return Result(float(item["lat"]), float(item["lon"]), prec)
        return None


PENDING_SQL = f"""
SELECT DISTINCT ON (e.endereco_hash)
       e.endereco_hash, e.tipo_logradouro, e.logradouro, e.numero, e.bairro, e.cep,
       coalesce(m.nome, rm.descricao), e.uf
FROM {LIVE}.estabelecimento e
LEFT JOIN geo.municipio_ibge m ON m.codigo_siafi = e.municipio
LEFT JOIN {LIVE}.municipio rm ON rm.codigo = e.municipio
LEFT JOIN geo.geocode g ON g.endereco_hash = e.endereco_hash
WHERE e.endereco_hash IS NOT NULL
  AND (%(todas)s OR e.situacao = 2)
  AND (%(uf)s::text IS NULL OR e.uf = %(uf)s)
  AND (g.endereco_hash IS NULL
       OR (g.lat IS NULL AND g.consultado_em < now() - make_interval(days => {RETRY_NOT_FOUND_DAYS})))
ORDER BY e.endereco_hash
LIMIT %(limit)s
"""


def pending(conn: psycopg.Connection, limit: int, todas: bool, uf: str | None) -> list[Address]:
    rows = conn.execute(PENDING_SQL, {"limit": limit, "todas": todas, "uf": uf}).fetchall()
    return [Address(bytes(r[0]), *r[1:]) for r in rows]


def save(conn: psycopg.Connection, items: list[tuple[Address, Result | None]], fonte: str) -> int:
    """Grava no cache (inclusive "não encontrado") e atualiza a base viva. Devolve encontrados."""
    found = [a.endereco_hash for a, r in items if r]
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO geo.geocode (endereco_hash, endereco_texto, lat, lng, precisao, fonte)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (endereco_hash) DO UPDATE
                   SET lat = EXCLUDED.lat, lng = EXCLUDED.lng, precisao = EXCLUDED.precisao,
                       fonte = EXCLUDED.fonte, consultado_em = now()""",
                [(a.endereco_hash, a.text(), r and r.lat, r and r.lng, r and r.precisao, fonte) for a, r in items],
            )
        if found:
            conn.execute(
                f"""UPDATE {LIVE}.estabelecimento e
                    SET geom = ST_SetSRID(ST_MakePoint(g.lng, g.lat), 4326)::geography,
                        geo_precisao = g.precisao
                    FROM geo.geocode g
                    WHERE g.endereco_hash = ANY(%s) AND e.endereco_hash = g.endereco_hash""",
                (found,),
            )
    return len(found)


async def run(
    conn: psycopg.Connection,
    base_url: str,
    user_agent: str,
    rps: float,
    concurrency: int,
    limit: int,
    page: int = 1000,
    todas: bool = False,
    uf: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, int]:
    """Geocodifica até ``limit`` endereços pendentes. Devolve (consultados, encontrados)."""
    own = client is None
    client = client or httpx.AsyncClient(base_url=base_url, headers={"User-Agent": user_agent}, timeout=30)
    geocoder = Geocoder(client, rps, concurrency)
    done = found = 0
    try:
        while done < limit:
            batch = pending(conn, min(page, limit - done), todas, uf)
            if not batch:
                break
            results = await asyncio.gather(*(geocoder.geocode(a) for a in batch))
            found += save(conn, list(zip(batch, results, strict=True)), fonte=base_url)
            done += len(batch)
            log.info("geocodificados %s (%s encontrados)", done, found)
    finally:
        if own:
            await client.aclose()
    return done, found
