import asyncio
import time

import httpx
import polars as pl
from cnpj_etl.geocode import municipios
from cnpj_etl.geocode.nominatim import Address, Geocoder, RateLimiter, precision_of

ADDR = Address(b"\x01" * 16, "RUA", "DAS FLORES", "123", "CENTRO", "01001000", "São Paulo", "SP")


def test_queries():
    assert ADDR.street_query() == {
        "street": "123 RUA DAS FLORES", "city": "São Paulo", "state": "SP", "country": "Brasil",
    }  # fmt: skip
    sn = Address(b"", "AV", "BRASIL", "S/N", None, "2004000", "Rio", "RJ")
    assert sn.street_query()["street"] == "AV BRASIL"
    assert sn.postcode_query() is None  # CEP com 7 dígitos
    assert ADDR.postcode_query() == {"postalcode": "01001-000", "country": "Brasil"}
    assert ADDR.text() == "RUA DAS FLORES, 123 - CENTRO, São Paulo/SP, 01001-000"


def test_precision_of():
    assert precision_of({"address": {"house_number": "123", "road": "x"}}) == 4
    assert precision_of({"category": "highway", "address": {"road": "x"}}) == 3
    assert precision_of({"addresstype": "postcode", "address": {}}) == 2
    assert precision_of({"addresstype": "city", "address": {"city": "x"}}) is None


def test_geocoder_cai_para_cep_quando_rua_nao_encontrada():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if "street" in request.url.params:
            return httpx.Response(200, json=[{"lat": "-23.5", "lon": "-46.6", "addresstype": "city"}])
        return httpx.Response(200, json=[{"lat": "-23.55", "lon": "-46.63", "addresstype": "postcode"}])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://n") as c:
            return await Geocoder(c, rps=1000, concurrency=2).geocode(ADDR)

    result = asyncio.run(go())
    assert result is not None and result.precisao == 2 and result.lat == -23.55
    assert len(calls) == 2 and calls[0]["format"] == "jsonv2"


def test_geocoder_repete_em_429():
    responses = iter([httpx.Response(429), httpx.Response(200, json=[])])

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: next(responses)), base_url="http://n"
        ) as c:
            g = Geocoder(c, rps=1000, concurrency=1)
            return await g._search({"q": "x"})

    import cnpj_etl.geocode.nominatim as nom

    orig = nom.asyncio.sleep
    nom.asyncio.sleep = lambda s: orig(0)
    try:
        assert asyncio.run(go()) is None
    finally:
        nom.asyncio.sleep = orig


def test_rate_limiter_espaca_requisicoes():
    async def go():
        limiter = RateLimiter(rps=20)
        t0 = time.monotonic()
        await asyncio.gather(*(limiter.wait() for _ in range(5)))
        return time.monotonic() - t0

    assert asyncio.run(go()) >= 0.19  # 5 chamadas a 20/s → 4 intervalos de 50 ms


def test_municipios_parse():
    csv = (
        "codigo_ibge,nome,latitude,longitude,capital,codigo_uf,siafi_id,ddd,fuso_horario\n"
        "3550308,São Paulo,-23.5329,-46.6395,1,35,7107,11,America/Sao_Paulo\n"
        "3304557,Rio de Janeiro,-22.9129,-43.2003,1,33,6001,21,America/Sao_Paulo\n"
    )
    df = municipios.parse(csv)
    assert df.to_dicts()[0] == {
        "codigo_siafi": 7107, "codigo_ibge": 3550308, "nome": "São Paulo", "uf": "SP",
        "lat": -23.5329, "lng": -46.6395,
    }  # fmt: skip
    assert df.schema["codigo_siafi"] == pl.Int32
