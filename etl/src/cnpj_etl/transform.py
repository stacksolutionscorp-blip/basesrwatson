"""Transformações polars dos arquivos da Receita para o formato das tabelas ``rf``.

Todas as funções são puras (DataFrame de strings → DataFrame tipado) para serem
testáveis sem banco. A ordem das colunas devolvidas é a ordem do COPY.
"""

import hashlib
import unicodedata

import polars as pl

# ---------------------------------------------------------------- expressões base

# Letras maiúsculas acentuadas → letra base (equivale a cnpj_core.normalize_text).
_ACCENTS = {
    ch: base
    for code in range(0x00C0, 0x0250)
    if (ch := chr(code)).isupper()
    and (base := "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))) != ch
}
_ACCENT_FROM = list(_ACCENTS)
_ACCENT_TO = list(_ACCENTS.values())


def txt(col: str | pl.Expr) -> pl.Expr:
    """Texto aparado; vazio → null."""
    e = pl.col(col) if isinstance(col, str) else col
    e = e.str.strip_chars()
    return pl.when(e == "").then(None).otherwise(e)


def norm(col: str | pl.Expr) -> pl.Expr:
    """MAIÚSCULAS, sem acento, espaços colapsados; vazio → null."""
    e = pl.col(col) if isinstance(col, str) else col
    e = e.str.to_uppercase().str.replace_many(_ACCENT_FROM, _ACCENT_TO).str.replace_all(r"\s+", " ").str.strip_chars()
    return pl.when(e == "").then(None).otherwise(e)


def date(col: str) -> pl.Expr:
    """AAAAMMDD → date. "0", "00000000", vazio e datas impossíveis → null."""
    return pl.col(col).str.strip_chars().str.strptime(pl.Date, "%Y%m%d", strict=False)


def integer(col: str, dtype: pl.DataType = pl.Int32) -> pl.Expr:
    return pl.col(col).str.strip_chars().cast(dtype, strict=False)


def capital(col: str) -> pl.Expr:
    """ "1.234,56" ou "1234,56" → Decimal(18,2)."""
    e = pl.col(col).str.strip_chars()
    e = pl.when(e.str.contains(",")).then(e.str.replace_all(r"\.", "").str.replace(",", ".")).otherwise(e)
    return e.cast(pl.Decimal(18, 2), strict=False)


def sim_nao(col: str) -> pl.Expr:
    e = pl.col(col).str.strip_chars().str.to_uppercase()
    return pl.when(e == "S").then(True).when(e == "N").then(False).otherwise(None)


def phone(ddd: str, number: str) -> pl.Expr:
    digits = pl.concat_str([pl.col(ddd).fill_null(""), pl.col(number).fill_null("")]).str.replace_all(r"\D", "")
    return pl.when(pl.col(number).str.replace_all(r"\D", "").fill_null("") == "").then(None).otherwise(digits)


def pg_int_array(col: str) -> pl.Expr:
    """ "6201501,6202300" → literal de array do Postgres "{6201501,6202300}"."""
    e = pl.col(col).str.replace_all(r"[^0-9,]", "").str.replace_all(r",+", ",").str.strip_chars(",")
    return pl.when(e.fill_null("") == "").then(None).otherwise(pl.lit("{") + e + pl.lit("}"))


def pad(col: str, width: int) -> pl.Expr:
    """Completa com zeros à esquerda; vazio → null (para a linha ser rejeitada)."""
    return txt(pl.col(col).str.to_uppercase()).str.zfill(width)


def md5_hex(values: pl.Series) -> pl.Series:
    """md5 em formato bytea hex do Postgres (\\x...). null → null."""
    return pl.Series(
        values.name,
        [None if v is None else "\\x" + hashlib.md5(v.encode()).hexdigest() for v in values.to_list()],
        dtype=pl.String,
    )


# ---------------------------------------------------------------- por arquivo
# Cada função devolve (df_pronto, linhas_rejeitadas).


def _split_valid(df: pl.DataFrame, valid: pl.Expr) -> tuple[pl.DataFrame, int]:
    df = df.with_columns(_ok=valid.fill_null(False))
    good = df.filter(pl.col("_ok")).drop("_ok")
    return good, df.height - good.height


def aux(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    out = df.select(codigo=integer("codigo"), descricao=txt("descricao"))
    return _split_valid(out, pl.col("codigo").is_not_null())


def empresas(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    out = df.select(
        cnpj_basico=pad("cnpj_basico", 8),
        razao_social=txt("razao_social"),
        razao_social_norm=norm("razao_social"),
        natureza_juridica=integer("natureza_juridica"),
        qualificacao_resp=integer("qualificacao_responsavel"),
        capital_social=capital("capital_social"),
        porte=integer("porte", pl.Int16),
        ente_federativo=txt("ente_federativo"),
    )
    return _split_valid(out, pl.col("cnpj_basico").str.len_chars() == 8)


ENDERECO_PARTS = ["tipo_logradouro", "logradouro", "numero", "bairro"]


def endereco_key() -> pl.Expr:
    """Endereço normalizado usado como chave do cache de geocodificação e no diff."""
    parts = [norm(c).fill_null("") for c in ENDERECO_PARTS] + [
        pl.col("cep").fill_null(""),
        pl.col("municipio").cast(pl.String).fill_null(""),
        pl.col("uf").fill_null(""),
    ]
    key = pl.concat_str(parts, separator="|")
    usable = pl.col("logradouro").is_not_null() & (pl.col("uf").fill_null("EX") != "EX")
    return pl.when(usable).then(key).otherwise(None)


def estabelecimentos(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    out = df.select(
        cnpj=pl.concat_str([pad("cnpj_basico", 8), pad("cnpj_ordem", 4), pad("cnpj_dv", 2)]),
        cnpj_basico=pad("cnpj_basico", 8),
        matriz=pl.col("identificador_matriz_filial").str.strip_chars() == "1",
        nome_fantasia=txt("nome_fantasia"),
        nome_fantasia_norm=norm("nome_fantasia"),
        situacao=integer("situacao_cadastral", pl.Int16),
        data_situacao=date("data_situacao_cadastral"),
        motivo_situacao=integer("motivo_situacao_cadastral"),
        data_inicio=date("data_inicio_atividade"),
        cnae_principal=integer("cnae_fiscal_principal"),
        cnaes_secundarios=pg_int_array("cnae_fiscal_secundaria"),
        tipo_logradouro=txt("tipo_logradouro"),
        logradouro=txt("logradouro"),
        numero=txt("numero"),
        complemento=txt("complemento"),
        bairro=txt("bairro"),
        cep=txt(pl.col("cep").str.replace_all(r"\D", "")),
        uf=txt(pl.col("uf").str.to_uppercase()),
        municipio=integer("municipio"),
        pais=integer("pais"),
        cidade_exterior=txt("nome_cidade_exterior"),
        telefone1=phone("ddd_1", "telefone_1"),
        telefone2=phone("ddd_2", "telefone_2"),
        fax=phone("ddd_fax", "fax"),
        email=txt(pl.col("correio_eletronico").str.to_lowercase()),
        situacao_especial=txt("situacao_especial"),
        data_situacao_especial=date("data_situacao_especial"),
    )
    out = out.with_columns(endereco_key=endereco_key())
    out, rejected = _split_valid(out, pl.col("cnpj").str.len_chars() == 14)
    out = out.with_columns(endereco_hash=pl.col("endereco_key").map_batches(md5_hex, return_dtype=pl.String))
    return out, rejected


def attach_geo(df: pl.DataFrame, geocoded: pl.DataFrame, centroids: pl.DataFrame) -> pl.DataFrame:
    """Preenche geom/geo_precisao: cache de geocodificação → centroide do município.

    ``geocoded``: endereco_hash (\\x hex), lat, lng, precisao
    ``centroids``: municipio (SIAFI), lat, lng
    """
    g = geocoded.select("endereco_hash", g_lat="lat", g_lng="lng", g_prec=pl.col("precisao").cast(pl.Int16))
    c = centroids.select("municipio", c_lat="lat", c_lng="lng")
    df = df.join(g, on="endereco_hash", how="left").join(c, on="municipio", how="left")
    use_g = pl.col("g_lat").is_not_null()
    lat = pl.when(use_g).then(pl.col("g_lat")).otherwise(pl.col("c_lat"))
    lng = pl.when(use_g).then(pl.col("g_lng")).otherwise(pl.col("c_lng"))
    point = pl.format("SRID=4326;POINT({} {})", lng, lat)
    df = df.with_columns(
        geom=pl.when(lat.is_not_null()).then(point).otherwise(None),
        geo_precisao=pl.when(use_g)
        .then(pl.col("g_prec"))
        .when(pl.col("c_lat").is_not_null())
        .then(pl.lit(1, pl.Int16))
        .otherwise(None),
    )
    return df.drop("g_lat", "g_lng", "g_prec", "c_lat", "c_lng")


ESTABELECIMENTO_COLUMNS = [
    "cnpj", "cnpj_basico", "matriz", "nome_fantasia", "nome_fantasia_norm", "situacao",
    "data_situacao", "motivo_situacao", "data_inicio", "cnae_principal", "cnaes_secundarios",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep", "uf",
    "municipio", "pais", "cidade_exterior", "telefone1", "telefone2", "fax", "email",
    "situacao_especial", "data_situacao_especial", "endereco_hash", "geom", "geo_precisao",
]  # fmt: skip

# CPF mascarado sem valor real publicado para "sem representante".
_SEM_REPRESENTANTE = {"***000000**", "00000000000", ""}


def socios(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    repr_cpf = txt("representante_legal")
    out = df.select(
        cnpj_basico=pad("cnpj_basico", 8),
        tipo=integer("identificador_socio", pl.Int16),
        nome=txt("nome_socio"),
        nome_norm=norm("nome_socio"),
        cpf_cnpj=txt("cnpj_cpf_socio"),
        qualificacao=integer("qualificacao_socio"),
        data_entrada=date("data_entrada_sociedade"),
        pais=integer("pais"),
        repr_cpf=pl.when(repr_cpf.is_in(list(_SEM_REPRESENTANTE))).then(None).otherwise(repr_cpf),
        repr_nome=txt("nome_representante"),
        repr_qualificacao=integer("qualificacao_representante"),
        faixa_etaria=integer("faixa_etaria", pl.Int16),
    )
    out = out.with_columns(
        chave_pessoa=pl.when(pl.col("nome_norm").is_not_null()).then(
            pl.concat_str([pl.col("nome_norm"), pl.col("cpf_cnpj").fill_null("")], separator="|")
        )
    )
    return _split_valid(out, pl.col("cnpj_basico").str.len_chars() == 8)


def simples(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    out = df.select(
        cnpj_basico=pad("cnpj_basico", 8),
        opcao_simples=sim_nao("opcao_simples"),
        data_opcao_simples=date("data_opcao_simples"),
        data_exclusao_simples=date("data_exclusao_simples"),
        opcao_mei=sim_nao("opcao_mei"),
        data_opcao_mei=date("data_opcao_mei"),
        data_exclusao_mei=date("data_exclusao_mei"),
    )
    return _split_valid(out, pl.col("cnpj_basico").str.len_chars() == 8)


TRANSFORMS = {
    "empresa": empresas,
    "estabelecimento": estabelecimentos,
    "socio": socios,
    "simples": simples,
}


def transform_for(table: str):
    return TRANSFORMS.get(table, aux)
