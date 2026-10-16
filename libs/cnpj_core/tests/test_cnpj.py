import pytest
from cnpj_core import clean, compute_dv, format_cnpj, is_valid, normalize_text


@pytest.mark.parametrize(
    "cnpj",
    [
        "11.222.333/0001-81",
        "11222333000181",
        "00.000.000/0001-91",  # Banco do Brasil
        "33.000.167/0001-01",  # Petrobras
        "12.ABC.345/01DE-35",  # exemplo oficial do CNPJ alfanumérico (Serpro/RFB)
        "12abc34501de35",  # minúsculas são aceitas
    ],
)
def test_validos(cnpj):
    assert is_valid(cnpj)


@pytest.mark.parametrize(
    "cnpj",
    [
        "11.222.333/0001-82",  # DV errado
        "12.ABC.345/01DE-36",
        "00000000000000",  # todos iguais
        "11111111111111",
        "1122233300018",  # 13 caracteres
        "112223330001811",
        "12.ABC.345/01DE-3A",  # DV não pode ser letra
        "",
        None,
    ],
)
def test_invalidos(cnpj):
    assert not is_valid(cnpj)


def test_compute_dv_compativel_com_numerico():
    assert compute_dv("112223330001") == "81"
    assert compute_dv("12ABC34501DE") == "35"


def test_compute_dv_rejeita_base_invalida():
    with pytest.raises(ValueError):
        compute_dv("12345")


def test_clean_e_format():
    assert clean(" 12.abc.345/01de-35 ") == "12ABC34501DE35"
    assert format_cnpj("11222333000181") == "11.222.333/0001-81"
    with pytest.raises(ValueError):
        format_cnpj("123")


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Padaria  São   João ", "PADARIA SAO JOAO"),
        ("AÇÚCAR & CIA ltda", "ACUCAR & CIA LTDA"),
        ("   ", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_text(entrada, esperado):
    assert normalize_text(entrada) == esperado
