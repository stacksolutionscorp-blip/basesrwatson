"""Prospecção de leads para consórcio: segmentos, score, decisores e consulta.

O score (0–100) prioriza quem tem canal de contato e porte para comprar uma carta de consórcio.
Ele é calculado no banco (para ordenar) e explicado em Python a partir das mesmas regras;
``test_score_sql_igual_python`` garante que as duas versões não divirjam.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from cnpj_core import format_cnpj, mask_cpf, normalize_text

from cnpj_api.profile import PORTE
from cnpj_api.runtime import LIVE

# Perfis de comprador por tipo de consórcio. São sugestões de partida: a tela permite editar.
SEGMENTOS: dict[str, dict] = {
    "pesados": {
        "nome": "Pesados e caminhões",
        "consorcio": "Consórcio de caminhões, ônibus e máquinas de obra",
        "cnaes": [
            4930201,
            4930202,
            4930203,
            4930204,
            4921301,
            4921302,
            4922101,
            4922102,
            4929901,
            4929902,
            4313400,
            3811400,
            5212500,
            5211701,
        ],
    },
    "frota": {
        "nome": "Veículos e frota de serviço",
        "consorcio": "Consórcio de veículos leves e utilitários",
        "cnaes": [
            4321500,
            4322301,
            4322302,
            8011101,
            5320202,
            4923001,
            7711000,
            8599601,
            8111700,
            4329104,
            4399103,
            8121400,
            4744099,
            4520001,
        ],
    },
    "imoveis": {
        "nome": "Imóveis",
        "consorcio": "Consórcio imobiliário (sede própria, investimento)",
        "cnaes": [
            4120400,
            4110700,
            6821801,
            6821802,
            6810201,
            6810202,
            8630503,
            8630504,
            6911701,
            6920601,
            7111100,
            7112000,
            8650004,
            8650003,
        ],
    },
    "agro": {
        "nome": "Agro e máquinas",
        "consorcio": "Consórcio de tratores, implementos e caminhonetes",
        "cnaes": [
            115600,
            111302,
            134200,
            113000,
            131800,
            132600,
            151201,
            151202,
            155501,
            161003,
            121101,
            133499,
            4623199,
            4661300,
        ],
    },
}

STATUS = ("novo", "contatado", "interessado", "proposta", "fechado", "sem_interesse")

# Qualificações que indicam quem decide, em ordem de prioridade (tabela de qualificações da Receita).
DECISORES = [49, 5, 65, 50, 16, 10, 28, 54, 22]
EMPRESARIO_INDIVIDUAL = 2135  # natureza jurídica do empresário individual (inclui MEI): sem quadro societário
_CPF_SUFIXO = re.compile(r"\s*(\*{3}\d{6}\*{2}|\d{3}\.?\d{3}\.?\d{3}-?\d{2})\s*$")


@dataclass
class FiltrosLead:
    lat: float | None = None
    lng: float | None = None
    raio_km: float | None = None
    municipio_ibge: list[int] = field(default_factory=list)
    segmento: str | None = None
    cnae: list[int] = field(default_factory=list)
    somente_cnae_principal: bool = False
    porte: list[int] = field(default_factory=list)
    capital_min: float | None = None
    idade_min_anos: float | None = None
    com_telefone: bool = True
    so_celular: bool = False
    com_email: bool = False
    incluir_mei: bool = True
    ocultar_trabalhados: bool = True
    q: str | None = None

    def validate(self) -> None:
        geo = (self.lat, self.lng, self.raio_km)
        if any(v is not None for v in geo) and not all(v is not None for v in geo):
            raise ValueError("lat, lng e raio_km devem ser informados juntos")
        if self.raio_km is not None and not 0 < self.raio_km <= 300:
            raise ValueError("raio_km deve estar entre 0 e 300")
        if self.segmento and self.segmento not in SEGMENTOS:
            raise ValueError(f"segmento desconhecido: {self.segmento}")

    def cnaes(self) -> list[int]:
        base = SEGMENTOS[self.segmento]["cnaes"] if self.segmento else []
        return sorted(set(base) | set(self.cnae))


def _celular_sql(col: str) -> str:
    return f"(length({col}) = 11 AND substr({col}, 3, 1) = '9')"


CELULAR = f"({_celular_sql('e.telefone1')} OR {_celular_sql('e.telefone2')})"


def score_sql(cnaes_param: str | None) -> str:
    segmento = f"CASE WHEN e.cnae_principal = ANY({cnaes_param}) THEN 10 ELSE 0 END" if cnaes_param else "0"
    return f"""(
        CASE WHEN e.telefone1 IS NOT NULL OR e.telefone2 IS NOT NULL THEN 20 ELSE 0 END
      + CASE WHEN {CELULAR} THEN 10 ELSE 0 END
      + CASE WHEN e.email IS NOT NULL THEN 10 ELSE 0 END
      + CASE WHEN coalesce(s.opcao_mei, false) THEN 5
             WHEN emp.porte = 5 THEN 20 WHEN emp.porte = 3 THEN 15 WHEN emp.porte = 1 THEN 10 ELSE 5 END
      + CASE WHEN e.data_inicio <= current_date - interval '3 years' THEN 15
             WHEN e.data_inicio <= current_date - interval '1 year' THEN 8 ELSE 0 END
      + CASE WHEN emp.capital_social >= 100000 THEN 15 WHEN emp.capital_social >= 20000 THEN 10
             WHEN emp.capital_social >= 5000 THEN 5 ELSE 0 END
      + {segmento})"""


def _celular(tel: str | None) -> bool:
    return bool(tel) and len(tel) == 11 and tel[2] == "9"


def fatores(r: dict, cnaes_segmento: list[int], hoje: date) -> list[dict]:
    """Mesmas regras de ``score_sql``, com explicação."""
    out: list[tuple[str, int]] = []
    tels = [t for t in (r["telefone1"], r["telefone2"]) if t]
    if tels:
        out.append(("tem telefone", 20))
    if any(_celular(t) for t in tels):
        out.append(("telefone celular (WhatsApp)", 10))
    if r["email"]:
        out.append(("tem e-mail", 10))
    if r["mei"]:
        out.append(("MEI", 5))
    else:
        out.append(
            {5: ("porte: demais (médio/grande)", 20), 3: ("porte: EPP", 15), 1: ("porte: ME", 10)}.get(
                r["porte"], ("porte não informado", 5)
            )
        )
    if r["data_inicio"]:
        anos = (hoje - r["data_inicio"]).days / 365.25
        if anos >= 3:
            out.append(("mais de 3 anos de atividade", 15))
        elif anos >= 1:
            out.append(("mais de 1 ano de atividade", 8))
    cap = r["capital_social"] or 0
    if cap >= 100000:
        out.append(("capital social ≥ R$ 100 mil", 15))
    elif cap >= 20000:
        out.append(("capital social ≥ R$ 20 mil", 10))
    elif cap >= 5000:
        out.append(("capital social ≥ R$ 5 mil", 5))
    if cnaes_segmento and r["cnae_principal"] in cnaes_segmento:
        out.append(("atividade principal do segmento", 10))
    return [{"fator": f, "pontos": p} for f, p in out]


def build_query(f: FiltrosLead, limit: int, offset: int) -> tuple[str, dict]:
    where = ["e.situacao = 2"]
    params: dict = {"limit": limit, "offset": offset}
    cnaes = f.cnaes()
    distance = "NULL::float8"
    if cnaes:
        params["cnaes"] = cnaes
        if f.somente_cnae_principal:
            where.append("e.cnae_principal = ANY(%(cnaes)s)")
        else:
            where.append("(e.cnae_principal = ANY(%(cnaes)s) OR e.cnaes_secundarios && %(cnaes)s::int[])")
    if f.raio_km is not None:
        params |= {"lat": f.lat, "lng": f.lng, "raio_m": f.raio_km * 1000}
        point = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"
        where.append(
            f"""((e.geo_precisao > 1 AND ST_DWithin(e.geom, {point}, %(raio_m)s))
                 OR (e.geo_precisao = 1 AND e.municipio IN (
                     SELECT codigo_siafi FROM geo.municipio_ibge m
                     WHERE ST_DWithin(ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography,
                                      {point}, %(raio_m)s))))"""
        )
        distance = f"round((ST_Distance(e.geom, {point}) / 1000)::numeric, 1)::float8"
    if f.municipio_ibge:
        params["mun"] = f.municipio_ibge
        where.append("e.municipio IN (SELECT codigo_siafi FROM geo.municipio_ibge WHERE codigo_ibge = ANY(%(mun)s))")
    if f.porte:
        params["porte"] = f.porte
        where.append("emp.porte = ANY(%(porte)s)")
    if f.capital_min is not None:
        params["capital_min"] = f.capital_min
        where.append("emp.capital_social >= %(capital_min)s")
    if f.idade_min_anos is not None:
        params["idade_dias"] = int(f.idade_min_anos * 365.25)
        where.append("e.data_inicio <= current_date - %(idade_dias)s")
    if f.com_telefone:
        where.append("(e.telefone1 IS NOT NULL OR e.telefone2 IS NOT NULL)")
    if f.so_celular:
        where.append(CELULAR)
    if f.com_email:
        where.append("e.email IS NOT NULL")
    if not f.incluir_mei:
        where.append("NOT coalesce(s.opcao_mei, false)")
    if f.ocultar_trabalhados:
        where.append("(l.cnpj IS NULL OR l.status = 'novo')")
    if f.q:
        params["q"] = f"%{normalize_text(f.q)}%"
        where.append("(emp.razao_social_norm LIKE %(q)s OR e.nome_fantasia_norm LIKE %(q)s)")
    # pedidos de não contato bloqueiam por CNPJ, telefone ou e-mail
    where.append(
        """NOT EXISTS (SELECT 1 FROM app.nao_contatar n
                       WHERE n.cnpj = e.cnpj OR n.telefone IN (e.telefone1, e.telefone2)
                          OR lower(n.email) = lower(e.email))"""
    )
    score = score_sql("%(cnaes)s" if cnaes else None)
    sql = f"""
WITH alvo AS (
    SELECT e.cnpj, {score} AS score, {distance} AS distancia_km
    FROM {LIVE}.estabelecimento e
    JOIN {LIVE}.empresa emp ON emp.cnpj_basico = e.cnpj_basico
    LEFT JOIN {LIVE}.simples s ON s.cnpj_basico = e.cnpj_basico
    LEFT JOIN app.lead l ON l.cnpj = e.cnpj
    WHERE {" AND ".join(where)}
    ORDER BY score DESC, distancia_km NULLS LAST, e.cnpj
    LIMIT %(limit)s OFFSET %(offset)s
)
{DETALHE.format(fonte="alvo a JOIN " + LIVE + ".estabelecimento e ON e.cnpj = a.cnpj")}
ORDER BY a.score DESC, a.distancia_km NULLS LAST, a.cnpj
"""
    return sql, params


# Colunas de exibição de um lead (usado pela busca e pela carteira).
DETALHE = (
    """SELECT e.cnpj, e.cnpj_basico, emp.razao_social, e.nome_fantasia, e.cnae_principal,
       c.descricao AS cnae_descricao, e.telefone1, e.telefone2, e.email, e.tipo_logradouro, e.logradouro,
       e.numero, e.bairro, e.cep, coalesce(mi.nome, mu.descricao) AS municipio, e.uf, e.data_inicio,
       emp.porte, emp.capital_social, emp.natureza_juridica, coalesce(s.opcao_mei, false) AS mei,
       ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lng,
       {score_col} AS score, {dist_col} AS distancia_km,
       l.status, l.nota, l.proximo_contato, l.atualizado_em AS status_em, u.nome AS responsavel
FROM {fonte}
JOIN """
    + LIVE
    + """.empresa emp ON emp.cnpj_basico = e.cnpj_basico
LEFT JOIN """
    + LIVE
    + """.simples s ON s.cnpj_basico = e.cnpj_basico
LEFT JOIN """
    + LIVE
    + """.cnae c ON c.codigo = e.cnae_principal
LEFT JOIN geo.municipio_ibge mi ON mi.codigo_siafi = e.municipio
LEFT JOIN """
    + LIVE
    + """.municipio mu ON mu.codigo = e.municipio
LEFT JOIN app.lead l ON l.cnpj = e.cnpj
LEFT JOIN app.usuario u ON u.id = l.responsavel_id"""
)
DETALHE = DETALHE.replace("{score_col}", "a.score").replace("{dist_col}", "a.distancia_km")

_DECISORES_SQL = f"""
SELECT s.cnpj_basico, s.nome, s.tipo, s.qualificacao, q.descricao AS qualificacao_descricao, s.faixa_etaria
FROM {LIVE}.socio s LEFT JOIN {LIVE}.qualificacao q ON q.codigo = s.qualificacao
WHERE s.cnpj_basico = ANY(%s)
ORDER BY s.cnpj_basico, array_position(%s::int[], s.qualificacao) NULLS LAST, s.tipo DESC, s.nome
"""


async def decisores(conn, rows: list[dict]) -> dict[str, list[dict]]:
    """Até 3 pessoas por empresa, priorizando quem administra; titular no caso de empresário individual."""
    basicos = sorted({r["cnpj_basico"] for r in rows})
    out: dict[str, list[dict]] = {b: [] for b in basicos}
    if basicos:
        for s in await (await conn.execute(_DECISORES_SQL, (basicos, DECISORES))).fetchall():
            lista = out[s["cnpj_basico"]]
            if len(lista) < 3:
                lista.append(
                    {
                        "nome": s["nome"],
                        "qualificacao": s["qualificacao_descricao"],
                        "tipo": {1: "PJ", 2: "PF", 3: "estrangeiro"}.get(s["tipo"]),
                    }
                )
    for r in rows:
        if not out[r["cnpj_basico"]] and r["natureza_juridica"] == EMPRESARIO_INDIVIDUAL and r["razao_social"]:
            titular = _CPF_SUFIXO.sub("", mask_cpf(r["razao_social"]) or "").strip()
            out[r["cnpj_basico"]] = [{"nome": titular, "qualificacao": "Titular (empresário individual)", "tipo": "PF"}]
    return out


def _tel(t: str) -> dict:
    cel = _celular(t)
    return {"numero": t, "celular": cel, "whatsapp": f"https://wa.me/55{t}" if cel else None}


def present(r: dict, dec: list[dict], cnaes_segmento: list[int], hoje: date) -> dict:
    return {
        "cnpj": r["cnpj"],
        "cnpj_formatado": format_cnpj(r["cnpj"]),
        "razao_social": mask_cpf(r["razao_social"]),
        "nome_fantasia": mask_cpf(r["nome_fantasia"]),
        "cnae_principal": {"codigo": r["cnae_principal"], "descricao": r["cnae_descricao"]},
        "telefones": [_tel(t) for t in (r["telefone1"], r["telefone2"]) if t],
        "email": r["email"],
        "endereco": " ".join(p for p in (r["tipo_logradouro"], r["logradouro"], r["numero"]) if p) or None,
        "bairro": r["bairro"],
        "cep": r["cep"],
        "municipio": r["municipio"],
        "uf": r["uf"],
        "distancia_km": r["distancia_km"],
        "lat": r["lat"],
        "lng": r["lng"],
        "porte": "MEI" if r["mei"] else PORTE.get(r["porte"]),
        "capital_social": r["capital_social"],
        "idade_anos": round((hoje - r["data_inicio"]).days / 365.25, 1) if r["data_inicio"] else None,
        "decisores": dec,
        "score": r["score"],
        "fatores": fatores(r, cnaes_segmento, hoje),
        "status": r["status"] or "novo",
        "nota": r["nota"],
        "proximo_contato": r["proximo_contato"],
        "status_em": r["status_em"],
        "responsavel": r["responsavel"],
    }
