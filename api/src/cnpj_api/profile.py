"""Montagem do perfil completo de um ou vários CNPJs com poucas consultas (usado por /cnpj e /lote)."""

from datetime import date

from cnpj_core import format_cnpj
from psycopg import AsyncConnection

from cnpj_api import risk
from cnpj_api.runtime import LIVE

SITUACAO = {1: "NULA", 2: "ATIVA", 3: "SUSPENSA", 4: "INAPTA", 8: "BAIXADA"}
PORTE = {0: "NÃO INFORMADO", 1: "MICRO EMPRESA", 3: "EMPRESA DE PEQUENO PORTE", 5: "DEMAIS"}
TIPO_SOCIO = {1: "PJ", 2: "PF", 3: "estrangeiro"}
FAIXA_ETARIA = {
    1: "0 a 12 anos", 2: "13 a 20 anos", 3: "21 a 30 anos", 4: "31 a 40 anos", 5: "41 a 50 anos",
    6: "51 a 60 anos", 7: "61 a 70 anos", 8: "71 a 80 anos", 9: "mais de 80 anos",
}  # fmt: skip
PRECISAO = {1: "municipio", 2: "cep", 3: "rua", 4: "numero"}

_ESTAB = f"""
SELECT e.*, ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lng,
       c.descricao AS cnae_descricao, mo.descricao AS motivo_descricao,
       mu.descricao AS municipio_rf, mi.nome AS municipio_nome, mi.codigo_ibge, pa.descricao AS pais_nome
FROM {LIVE}.estabelecimento e
LEFT JOIN {LIVE}.cnae c ON c.codigo = e.cnae_principal
LEFT JOIN {LIVE}.motivo_situacao mo ON mo.codigo = e.motivo_situacao
LEFT JOIN {LIVE}.municipio mu ON mu.codigo = e.municipio
LEFT JOIN geo.municipio_ibge mi ON mi.codigo_siafi = e.municipio
LEFT JOIN {LIVE}.pais pa ON pa.codigo = e.pais
WHERE e.cnpj = ANY(%s)
"""
_EMPRESA = f"""
SELECT emp.*, nj.descricao AS natureza_descricao,
       (SELECT count(*) FROM {LIVE}.estabelecimento x WHERE x.cnpj_basico = emp.cnpj_basico) AS qtd_estab
FROM {LIVE}.empresa emp
LEFT JOIN {LIVE}.natureza_juridica nj ON nj.codigo = emp.natureza_juridica
WHERE emp.cnpj_basico = ANY(%s)
"""
_SOCIOS = f"""
SELECT s.*, q.descricao AS qualificacao_descricao, qr.descricao AS repr_qualificacao_descricao,
       pa.descricao AS pais_nome
FROM {LIVE}.socio s
LEFT JOIN {LIVE}.qualificacao q ON q.codigo = s.qualificacao
LEFT JOIN {LIVE}.qualificacao qr ON qr.codigo = s.repr_qualificacao
LEFT JOIN {LIVE}.pais pa ON pa.codigo = s.pais
WHERE s.cnpj_basico = ANY(%s)
ORDER BY s.cnpj_basico, s.nome
"""
_SIMPLES = f"SELECT * FROM {LIVE}.simples WHERE cnpj_basico = ANY(%s)"
_CNAES = f"SELECT codigo, descricao FROM {LIVE}.cnae WHERE codigo = ANY(%s)"


async def _all(conn: AsyncConnection, sql: str, arg) -> list[dict]:
    return await (await conn.execute(sql, (arg,))).fetchall()


def _cod(codigo, descricao) -> dict | None:
    return None if codigo is None else {"codigo": codigo, "descricao": descricao}


def _socio(s: dict) -> dict:
    representante = None
    if s["repr_nome"] or s["repr_cpf"]:
        representante = {
            "nome": s["repr_nome"],
            "cpf": s["repr_cpf"],
            "qualificacao": _cod(s["repr_qualificacao"], s["repr_qualificacao_descricao"]),
        }
    return {
        "tipo": TIPO_SOCIO.get(s["tipo"]),
        "nome": s["nome"],
        "cpf_cnpj": s["cpf_cnpj"],
        "qualificacao": _cod(s["qualificacao"], s["qualificacao_descricao"]),
        "data_entrada": s["data_entrada"],
        "pais": _cod(s["pais"], s["pais_nome"]),
        "faixa_etaria": FAIXA_ETARIA.get(s["faixa_etaria"]),
        "representante": representante,
    }


def build(e: dict, emp: dict | None, socios: list[dict], simples: dict | None, cnaes: dict[int, str],
          referencia: str | None, hoje: date) -> dict:  # fmt: skip
    emp = emp or {}
    mei = simples["opcao_mei"] if simples else None
    idade = round((hoje - e["data_inicio"]).days / 365.25, 1) if e["data_inicio"] else None
    socios_out = [_socio(s) for s in socios]
    return {
        "cnpj": e["cnpj"],
        "cnpj_formatado": format_cnpj(e["cnpj"]),
        "cnpj_basico": e["cnpj_basico"],
        "matriz": e["matriz"],
        "razao_social": emp.get("razao_social"),
        "nome_fantasia": e["nome_fantasia"],
        "situacao": {
            "codigo": e["situacao"],
            "descricao": SITUACAO.get(e["situacao"]),
            "data": e["data_situacao"],
            "motivo": _cod(e["motivo_situacao"], e["motivo_descricao"]),
        },
        "situacao_especial": e["situacao_especial"],
        "data_situacao_especial": e["data_situacao_especial"],
        "data_inicio": e["data_inicio"],
        "idade_anos": idade,
        "natureza_juridica": _cod(emp.get("natureza_juridica"), emp.get("natureza_descricao")),
        "porte": _cod(emp.get("porte"), PORTE.get(emp.get("porte"))),
        "capital_social": emp.get("capital_social"),
        "ente_federativo": emp.get("ente_federativo"),
        "cnae_principal": _cod(e["cnae_principal"], e["cnae_descricao"]),
        "cnaes_secundarios": [_cod(c, cnaes.get(c)) for c in (e["cnaes_secundarios"] or [])],
        "endereco": {
            "tipo_logradouro": e["tipo_logradouro"],
            "logradouro": e["logradouro"],
            "numero": e["numero"],
            "complemento": e["complemento"],
            "bairro": e["bairro"],
            "cep": e["cep"],
            "municipio": {
                "codigo_siafi": e["municipio"],
                "codigo_ibge": e["codigo_ibge"],
                "nome": e["municipio_nome"] or e["municipio_rf"],
            },
            "uf": e["uf"],
            "pais": _cod(e["pais"], e["pais_nome"]),
            "cidade_exterior": e["cidade_exterior"],
            "lat": e["lat"],
            "lng": e["lng"],
            "geo_precisao": PRECISAO.get(e["geo_precisao"]),
        },
        "contato": {
            "telefones": [t for t in (e["telefone1"], e["telefone2"]) if t],
            "email": e["email"],
        },
        "simples": None
        if simples is None
        else {
            "optante": simples["opcao_simples"],
            "data_opcao": simples["data_opcao_simples"],
            "data_exclusao": simples["data_exclusao_simples"],
            "mei": simples["opcao_mei"],
            "data_opcao_mei": simples["data_opcao_mei"],
            "data_exclusao_mei": simples["data_exclusao_mei"],
        },
        "socios": socios_out,
        "qtd_estabelecimentos": emp.get("qtd_estab") or 1,
        "score_risco": risk.score(
            situacao=e["situacao"],
            data_inicio=e["data_inicio"],
            capital_social=emp.get("capital_social"),
            data_situacao=e["data_situacao"],
            situacao_especial=e["situacao_especial"],
            datas_entrada_socios=[s["data_entrada"] for s in socios],
            mei=mei,
            hoje=hoje,
        ),
        "referencia": referencia,
    }


async def fetch_profiles(conn: AsyncConnection, cnpjs: list[str], referencia: str | None) -> dict[str, dict]:
    """Perfis completos de vários CNPJs (14 caracteres, já validados) com 5 consultas."""
    estabs = await _all(conn, _ESTAB, cnpjs)
    if not estabs:
        return {}
    basicos = sorted({e["cnpj_basico"] for e in estabs})
    empresas = {r["cnpj_basico"]: r for r in await _all(conn, _EMPRESA, basicos)}
    simples = {r["cnpj_basico"]: r for r in await _all(conn, _SIMPLES, basicos)}
    socios: dict[str, list[dict]] = {}
    for s in await _all(conn, _SOCIOS, basicos):
        socios.setdefault(s["cnpj_basico"], []).append(s)
    codes = sorted({c for e in estabs for c in (e["cnaes_secundarios"] or [])})
    cnaes = {r["codigo"]: r["descricao"] for r in await _all(conn, _CNAES, codes)} if codes else {}
    hoje = date.today()
    return {
        e["cnpj"]: build(
            e,
            empresas.get(e["cnpj_basico"]),
            socios.get(e["cnpj_basico"], []),
            simples.get(e["cnpj_basico"]),
            cnaes,
            referencia,
            hoje,
        )
        for e in estabs
    }
