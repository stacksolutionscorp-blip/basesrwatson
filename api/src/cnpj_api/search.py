"""Busca de estabelecimentos com filtros combinados (usada por /busca e /export)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from cnpj_core import clean, format_cnpj, is_valid, mask_cpf, normalize_text

from cnpj_api.profile import PORTE, SITUACAO
from cnpj_api.runtime import LIVE

MAX_RAIO_KM = 200


@dataclass
class Filtros:
    q: str | None = None
    cnae: list[int] = field(default_factory=list)
    somente_cnae_principal: bool = False
    uf: list[str] = field(default_factory=list)
    municipio: list[int] = field(default_factory=list)  # SIAFI (Receita)
    municipio_ibge: list[int] = field(default_factory=list)
    lat: float | None = None
    lng: float | None = None
    raio_km: float | None = None
    situacao: list[int] = field(default_factory=list)
    porte: list[int] = field(default_factory=list)
    capital_min: Decimal | None = None
    capital_max: Decimal | None = None
    abertura_de: date | None = None
    abertura_ate: date | None = None
    simples: bool | None = None
    mei: bool | None = None
    matriz: bool | None = None
    cnpj_basico: str | None = None  # usado por /cnpj/{cnpj}/filiais

    def validate(self) -> None:
        geo = (self.lat, self.lng, self.raio_km)
        if any(v is not None for v in geo) and not all(v is not None for v in geo):
            raise ValueError("lat, lng e raio_km devem ser informados juntos")
        if self.raio_km is not None and not 0 < self.raio_km <= MAX_RAIO_KM:
            raise ValueError(f"raio_km deve estar entre 0 e {MAX_RAIO_KM}")
        if self.lat is not None and not (-90 <= self.lat <= 90 and -180 <= self.lng <= 180):
            raise ValueError("coordenadas inválidas")
        if self.q is not None and len(normalize_text(self.q) or "") < 3 and len(clean(self.q)) not in (8, 14):
            raise ValueError("q deve ter ao menos 3 caracteres")


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def build_query(f: Filtros, limit: int, offset: int = 0) -> tuple[str, dict]:
    where: list[str] = []
    params: dict = {"limit": limit, "offset": offset}
    joins_simples = f.simples is not None or f.mei is not None

    if f.q:
        doc = clean(f.q)
        if len(doc) == 14 and is_valid(doc):
            where.append("e.cnpj = %(doc)s")
            params["doc"] = doc
        elif len(doc) == 8 and doc.isdigit():
            where.append("e.cnpj_basico = %(doc)s")
            params["doc"] = doc
        else:
            params["q"] = _like(normalize_text(f.q))
            where.append(
                f"""(e.cnpj_basico IN (SELECT cnpj_basico FROM {LIVE}.empresa WHERE razao_social_norm LIKE %(q)s)
                     OR e.nome_fantasia_norm LIKE %(q)s)"""
            )
    if f.cnae:
        params["cnae"] = f.cnae
        if f.somente_cnae_principal:
            where.append("e.cnae_principal = ANY(%(cnae)s)")
        else:
            where.append("(e.cnae_principal = ANY(%(cnae)s) OR e.cnaes_secundarios && %(cnae)s::int[])")
    if f.uf:
        params["uf"] = [u.upper() for u in f.uf]
        where.append("e.uf = ANY(%(uf)s)")
    if f.municipio:
        params["municipio"] = f.municipio
        where.append("e.municipio = ANY(%(municipio)s)")
    if f.municipio_ibge:
        params["municipio_ibge"] = f.municipio_ibge
        where.append(
            "e.municipio IN (SELECT codigo_siafi FROM geo.municipio_ibge WHERE codigo_ibge = ANY(%(municipio_ibge)s))"
        )
    if f.situacao:
        params["situacao"] = f.situacao
        where.append("e.situacao = ANY(%(situacao)s)")
    if f.porte:
        params["porte"] = f.porte
        where.append("emp.porte = ANY(%(porte)s)")
    if f.capital_min is not None:
        params["capital_min"] = f.capital_min
        where.append("emp.capital_social >= %(capital_min)s")
    if f.capital_max is not None:
        params["capital_max"] = f.capital_max
        where.append("emp.capital_social <= %(capital_max)s")
    if f.abertura_de:
        params["abertura_de"] = f.abertura_de
        where.append("e.data_inicio >= %(abertura_de)s")
    if f.abertura_ate:
        params["abertura_ate"] = f.abertura_ate
        where.append("e.data_inicio <= %(abertura_ate)s")
    if f.simples is not None:
        params["simples"] = f.simples
        where.append("coalesce(s.opcao_simples, false) = %(simples)s")
    if f.mei is not None:
        params["mei"] = f.mei
        where.append("coalesce(s.opcao_mei, false) = %(mei)s")
    if f.cnpj_basico:
        params["cnpj_basico"] = f.cnpj_basico
        where.append("e.cnpj_basico = %(cnpj_basico)s")
    if f.matriz is not None:
        params["matriz"] = f.matriz
        where.append("e.matriz = %(matriz)s")

    joins_empresa = f.porte or f.capital_min is not None or f.capital_max is not None
    joins = "\n".join(
        j
        for j, on in (
            (f"JOIN {LIVE}.empresa emp ON emp.cnpj_basico = e.cnpj_basico", joins_empresa),
            (f"LEFT JOIN {LIVE}.simples s ON s.cnpj_basico = e.cnpj_basico", joins_simples),
        )
        if on
    )
    cond = " AND ".join(where) or "true"

    if f.raio_km is None:
        alvo = f"""
    SELECT e.cnpj, NULL::float8 AS distancia_km
    FROM {LIVE}.estabelecimento e {joins}
    WHERE {cond}
    ORDER BY e.cnpj
    LIMIT %(limit)s OFFSET %(offset)s"""
        outer_order = "a.cnpj"
    else:
        # Duas origens de coordenada: pontos geocodificados (índice espacial parcial) e estabelecimentos
        # que só têm o centroide do município — estes são achados pelos municípios no raio e lidos por
        # (municipio, cnpj), sem varrer milhões de pontos idênticos.
        params |= {"lat": f.lat, "lng": f.lng, "raio_m": f.raio_km * 1000}
        point = "ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography"
        km = "round((ST_Distance({g}, " + point + ") / 1000)::numeric, 3)::float8"
        centroid = "ST_SetSRID(ST_MakePoint(m.lng, m.lat), 4326)::geography"
        alvo = f"""
    (SELECT e.cnpj, {km.format(g="e.geom")} AS distancia_km
     FROM {LIVE}.estabelecimento e {joins}
     WHERE e.geo_precisao > 1 AND ST_DWithin(e.geom, {point}, %(raio_m)s) AND {cond})
    UNION ALL
    (SELECT x.cnpj, mun.distancia_km
     FROM (SELECT m.codigo_siafi, {km.format(g=centroid)} AS distancia_km
           FROM geo.municipio_ibge m
           WHERE ST_DWithin({centroid}, {point}, %(raio_m)s)) mun
     CROSS JOIN LATERAL (
         SELECT e.cnpj FROM {LIVE}.estabelecimento e {joins}
         WHERE e.geo_precisao = 1 AND e.municipio = mun.codigo_siafi AND {cond}
         ORDER BY e.cnpj
         LIMIT %(limit)s + %(offset)s) x)
    ORDER BY distancia_km, cnpj
    LIMIT %(limit)s OFFSET %(offset)s"""
        outer_order = "a.distancia_km, a.cnpj"

    # Duas etapas: filtra/ordena/pagina só sobre estabelecimento (e empresa/simples se algum filtro
    # exigir) e depois junta os dados de exibição apenas nas linhas da página.
    sql = f"""
WITH alvo AS ({alvo}
)
SELECT e.cnpj, e.matriz, emp.razao_social, e.nome_fantasia, e.situacao, e.data_inicio, e.cnae_principal,
       emp.porte, emp.capital_social, coalesce(mi.nome, mu.descricao) AS municipio, e.uf, e.cep,
       ST_Y(e.geom::geometry) AS lat, ST_X(e.geom::geometry) AS lng, a.distancia_km
FROM alvo a
JOIN {LIVE}.estabelecimento e ON e.cnpj = a.cnpj
LEFT JOIN {LIVE}.empresa emp ON emp.cnpj_basico = e.cnpj_basico
LEFT JOIN geo.municipio_ibge mi ON mi.codigo_siafi = e.municipio
LEFT JOIN {LIVE}.municipio mu ON mu.codigo = e.municipio
ORDER BY {outer_order}
"""
    return sql, params


def present(row: dict) -> dict:
    return {
        "cnpj": row["cnpj"],
        "cnpj_formatado": format_cnpj(row["cnpj"]),
        "matriz": row["matriz"],
        "razao_social": mask_cpf(row["razao_social"]),
        "nome_fantasia": mask_cpf(row["nome_fantasia"]),
        "situacao": SITUACAO.get(row["situacao"]),
        "data_inicio": row["data_inicio"],
        "cnae_principal": row["cnae_principal"],
        "porte": PORTE.get(row["porte"]),
        "capital_social": row["capital_social"],
        "municipio": row["municipio"],
        "uf": row["uf"],
        "cep": row["cep"],
        "lat": row["lat"],
        "lng": row["lng"],
        "distancia_km": row["distancia_km"],
    }
