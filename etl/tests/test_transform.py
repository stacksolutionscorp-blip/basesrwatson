from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from cnpj_core import normalize_text
from cnpj_etl import transform
from cnpj_etl.demo import EMPRESAS_0, ESTABELECIMENTOS_0, ESTABELECIMENTOS_1, SOCIOS_0, cnpj
from cnpj_etl.demo import SIMPLES as SIMPLES_ROWS
from cnpj_etl.layouts import EMPRESAS, ESTABELECIMENTOS, SIMPLES, SOCIOS
from cnpj_etl.reader import parse


def frame(lines: list[str], columns: list[str]) -> pl.DataFrame:
    return parse("\n".join(lines) + "\n", columns).df


def one(expr: pl.Expr, values: list[str | None]) -> list:
    return pl.DataFrame({"c": values}, schema={"c": pl.String}).select(expr.alias("c"))["c"].to_list()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20150310", date(2015, 3, 10)),
        ("00000000", None),
        ("0", None),
        ("", None),
        (None, None),
        ("20151340", None),  # mês inválido
    ],
)
def test_date(raw, expected):
    assert one(transform.date("c"), [raw]) == [expected]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15000,00", Decimal("15000.00")),
        ("1.500.000,50", Decimal("1500000.50")),
        ("0,00", Decimal("0.00")),
        ("1234.5", Decimal("1234.50")),
        ("", None),
        ("abc", None),
    ],
)
def test_capital(raw, expected):
    assert one(transform.capital("c"), [raw]) == [expected]


def test_norm_equivale_a_normalize_text():
    samples = ["Padaria  São João", "AÇÚCAR & CIA ltda", "ÑANDÚ Ü ÿ", "  ", "Ação\tTeste"]
    assert one(transform.norm("c"), samples) == [normalize_text(s) for s in samples]


def test_pg_int_array():
    assert one(transform.pg_int_array("c"), ["4721102,5611203", "4721102", "", ",,", None]) == [
        "{4721102,5611203}", "{4721102}", None, None, None,
    ]  # fmt: skip


def test_sim_nao_e_phone():
    df = pl.DataFrame({"s": ["S", "n", "", "X"], "ddd": ["11", "11", "", "21"], "tel": ["3333-4444", "", "", "9999"]})
    out = df.select(b=transform.sim_nao("s"), t=transform.phone("ddd", "tel"))
    assert out["b"].to_list() == [True, False, None, None]
    assert out["t"].to_list() == ["1133334444", None, None, "219999"]


def test_empresas():
    df, rejected = transform.empresas(frame(EMPRESAS_0, EMPRESAS))
    assert rejected == 0
    r = df.row(1, named=True)
    assert r["razao_social"] == "HOLDING AÇÚCAR; PARTICIPAÇÕES S.A."
    assert r["razao_social_norm"] == "HOLDING ACUCAR; PARTICIPACOES S.A."
    assert r["capital_social"] == Decimal("1500000.50")
    assert r["porte"] == 5
    assert r["ente_federativo"] is None


def test_estabelecimentos():
    df, rejected = transform.estabelecimentos(frame(ESTABELECIMENTOS_0 + ESTABELECIMENTOS_1, ESTABELECIMENTOS))
    assert rejected == 0
    by = {r["cnpj"]: r for r in df.iter_rows(named=True)}
    holding = "".join(cnpj("44555666", "0001"))
    matriz = by["11222333000181"]
    assert matriz["matriz"] is True
    assert matriz["cnaes_secundarios"] == "{4721102,5611203}"
    assert matriz["email"] == "contato@padaria.com.br"
    assert matriz["telefone1"] == "1133334444"
    assert matriz["endereco_hash"].startswith("\\x") and len(matriz["endereco_hash"]) == 34
    assert by["".join(cnpj("11222333", "0002"))]["matriz"] is False
    assert "LINHA\nQUEBRADA" in by[holding]["logradouro"]
    assert by[holding]["data_inicio"] is None
    assert by["12ABC34501DE35"]["nome_fantasia"] == "ALFA"
    # mesmo endereço → mesmo hash; endereço diferente → hash diferente
    assert by["11222333000181"]["endereco_hash"] != by["".join(cnpj("11222333", "0002"))]["endereco_hash"]


def test_estabelecimento_sem_cnpj_completo_e_rejeitado():
    bad = ESTABELECIMENTOS_0[0].replace('"11222333"', '""', 1)
    df, rejected = transform.estabelecimentos(frame([bad], ESTABELECIMENTOS))
    assert rejected == 1 and df.height == 0


def test_endereco_exterior_sem_hash():
    row = ESTABELECIMENTOS_0[0].replace('"SP"', '"EX"')
    df, _ = transform.estabelecimentos(frame([row], ESTABELECIMENTOS))
    assert df["endereco_hash"].to_list() == [None]


def test_attach_geo_prefere_cache_e_cai_para_centroide():
    df, _ = transform.estabelecimentos(frame(ESTABELECIMENTOS_0 + ESTABELECIMENTOS_1, ESTABELECIMENTOS))
    hit = df.filter(pl.col("cnpj") == "11222333000181")["endereco_hash"][0]
    geocoded = pl.DataFrame({"endereco_hash": [hit], "lat": [-23.5], "lng": [-46.6], "precisao": [4]})
    centroids = pl.DataFrame({"municipio": [7107, 6001], "lat": [-23.55, -22.9], "lng": [-46.63, -43.2]},
                             schema={"municipio": pl.Int32, "lat": pl.Float64, "lng": pl.Float64})  # fmt: skip
    filial = "".join(cnpj("11222333", "0002"))
    out = {r["cnpj"]: r for r in transform.attach_geo(df, geocoded, centroids).iter_rows(named=True)}
    assert out["11222333000181"]["geom"] == "SRID=4326;POINT(-46.6 -23.5)"
    assert out["11222333000181"]["geo_precisao"] == 4
    assert out[filial]["geom"] == "SRID=4326;POINT(-43.2 -22.9)"
    assert out[filial]["geo_precisao"] == 1
    assert out["12ABC34501DE35"]["geom"] is None and out["12ABC34501DE35"]["geo_precisao"] is None


def test_socios():
    df, rejected = transform.socios(frame(SOCIOS_0, SOCIOS))
    assert rejected == 0
    rows = df.to_dicts()
    assert rows[0]["cpf_cnpj"] == "***123456**"  # mantém a máscara publicada
    assert rows[0]["repr_cpf"] is None  # ***000000** = sem representante
    assert rows[0]["chave_pessoa"] == "JOSE DA SILVA|***123456**"
    assert rows[0]["chave_pessoa"] == rows[2]["chave_pessoa"]  # mesma pessoa em 2 empresas
    assert rows[3]["repr_cpf"] == "***987654**"
    assert rows[3]["cpf_cnpj"] is None and rows[3]["data_entrada"] is None


def test_simples():
    df, _ = transform.simples(frame(SIMPLES_ROWS, SIMPLES))
    assert df.row(1, named=True) == {
        "cnpj_basico": "77888999",
        "opcao_simples": True,
        "data_opcao_simples": date(2020, 1, 1),
        "data_exclusao_simples": None,
        "opcao_mei": True,
        "data_opcao_mei": date(2020, 1, 1),
        "data_exclusao_mei": None,
    }


def test_aux_rejeita_codigo_invalido():
    df, rejected = transform.aux(frame(['"0001";"X"', '"abc";"Y"'], ["codigo", "descricao"]))
    assert df.to_dicts() == [{"codigo": 1, "descricao": "X"}] and rejected == 1


def test_razao_social_norm_sem_cpf():
    df, _ = transform.empresas(frame(EMPRESAS_0, EMPRESAS))
    jose = df.filter(pl.col("cnpj_basico") == "77888999").row(0, named=True)
    assert jose["razao_social"] == "JOSÉ DA SILVA 12345678900"  # dado original preservado no banco
    assert jose["razao_social_norm"] == "JOSE DA SILVA"  # índice de busca sem o CPF
