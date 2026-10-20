from typing import Annotated

from cnpj_core import clean, format_cnpj, is_valid, mask_cpf, normalize_text
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder

from cnpj_api import graph, profile, search
from cnpj_api.deps import ClienteDep, valid_cnpj
from cnpj_api.runtime import LIVE
from cnpj_api.schemas import Grafo, ListaEstabelecimentos, ListaSocios, LoteEntrada, LoteResposta, Perfil

router = APIRouter(prefix="/v1", tags=["consulta"])


async def get_profile(request: Request, cnpj: str) -> dict | None:
    st = request.app.state
    key = f"perfil:{st.referencia}:{cnpj}"
    cached = await st.cache.get(key)
    if cached is not None:
        return cached
    async with st.pool.connection() as conn:
        found = await profile.fetch_profiles(conn, [cnpj], st.referencia)
    data = found.get(cnpj)
    if data is not None:
        data = jsonable_encoder(data)
        await st.cache.set(key, data)
    return data


@router.get("/cnpj/{cnpj}", response_model=Perfil, summary="Perfil completo de um CNPJ")
async def consultar(cnpj: str, request: Request, _: ClienteDep):
    """Empresa, estabelecimento, sócios, CNAEs, Simples/MEI, coordenadas e score de risco.

    Aceita o CNPJ com ou sem pontuação, numérico ou alfanumérico.
    """
    c = valid_cnpj(cnpj)
    data = await get_profile(request, c)
    if data is None:
        raise HTTPException(404, f"CNPJ {format_cnpj(c)} não encontrado na base da Receita")
    return data


@router.get(
    "/cnpj/{cnpj}/filiais", response_model=ListaEstabelecimentos, summary="Estabelecimentos do mesmo CNPJ básico"
)
async def filiais(
    cnpj: str,
    request: Request,
    _: ClienteDep,
    pagina: Annotated[int, Query(ge=1)] = 1,
    por_pagina: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Aceita o CNPJ completo (14) ou só a raiz (8 caracteres)."""
    c = clean(cnpj)
    if len(c) == 14:
        c = valid_cnpj(c)
    elif len(c) != 8:
        raise HTTPException(422, "informe o CNPJ completo ou os 8 caracteres da raiz")
    sql, params = search.build_query(search.Filtros(cnpj_basico=c[:8]), por_pagina + 1, (pagina - 1) * por_pagina)
    async with request.app.state.pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    if not rows and pagina == 1:
        raise HTTPException(404, "CNPJ básico não encontrado")
    return {
        "resultados": [search.present(r) for r in rows[:por_pagina]],
        "paginacao": {"pagina": pagina, "por_pagina": por_pagina, "tem_mais": len(rows) > por_pagina},
    }


@router.get("/grafo/{cnpj}", response_model=Grafo, summary="Rede societária")
async def grafo(
    cnpj: str,
    request: Request,
    _: ClienteDep,
    niveis: Annotated[int, Query(ge=1, le=3, description="Saltos a partir da empresa")] = 2,
):
    """Empresa ↔ sócios ↔ outras empresas. Formato pronto para cytoscape.js / vis-network.

    Pessoas físicas são ligadas pelo par nome + CPF mascarado publicado pela Receita.
    """
    c = clean(cnpj)
    basico = valid_cnpj(c)[:8] if len(c) == 14 else c
    if len(basico) != 8:
        raise HTTPException(422, "informe o CNPJ completo ou os 8 caracteres da raiz")
    st = request.app.state
    async with st.pool.connection() as conn:
        exists = await (
            await conn.execute(f"SELECT 1 FROM {LIVE}.empresa WHERE cnpj_basico = %s", (basico,))
        ).fetchone()
        if not exists:
            raise HTTPException(404, "empresa não encontrada")
        return await graph.build_graph(conn, basico, niveis, st.settings.graph_max_nodes)


@router.post("/lote", response_model=LoteResposta, summary="Consulta em lote")
async def lote(body: LoteEntrada, request: Request, cliente: ClienteDep):
    """Até 500 CNPJs por chamada (limite do plano). A ordem da resposta segue a da entrada."""
    if len(body.cnpjs) > cliente.plano.lote_max:
        raise HTTPException(422, f"seu plano permite até {cliente.plano.lote_max} CNPJs por lote")
    limpos = [clean(c) for c in body.cnpjs]
    validos = sorted({c for c in limpos if is_valid(c)})
    st = request.app.state
    async with st.pool.connection() as conn:
        perfis = await profile.fetch_profiles(conn, validos, st.referencia) if validos else {}
    out = []
    for original, c in zip(body.cnpjs, limpos, strict=True):
        if not is_valid(c):
            out.append({"cnpj": original, "ok": False, "erro": "CNPJ inválido"})
        elif c not in perfis:
            out.append({"cnpj": c, "ok": False, "erro": "não encontrado"})
        else:
            out.append({"cnpj": c, "ok": True, "dados": perfis[c]})
    return {"resultados": out}


_SOCIOS = f"""
SELECT s.chave_pessoa, s.nome, s.cpf_cnpj, s.tipo, s.cnpj_basico, emp.razao_social,
       s.qualificacao, q.descricao AS qualificacao_descricao, s.data_entrada
FROM {LIVE}.socio s
LEFT JOIN {LIVE}.empresa emp ON emp.cnpj_basico = s.cnpj_basico
LEFT JOIN {LIVE}.qualificacao q ON q.codigo = s.qualificacao
WHERE s.nome_norm LIKE %(nome)s {{cpf}}
ORDER BY s.nome_norm, s.cpf_cnpj, s.cnpj_basico
LIMIT 2000
"""


@router.get("/socios", response_model=ListaSocios, summary="Busca de sócio → empresas vinculadas")
async def socios(
    request: Request,
    _: ClienteDep,
    nome: Annotated[str, Query(min_length=3, description="Nome (ou parte) do sócio")],
    cpf: Annotated[str | None, Query(description="Dígitos visíveis do CPF mascarado, ex.: 123456")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Agrupa por pessoa (nome + CPF mascarado) e lista as empresas em que ela aparece."""
    termo = normalize_text(nome)
    if not termo or len(termo) < 3:
        raise HTTPException(422, "nome deve ter ao menos 3 caracteres")
    params = {"nome": search._like(termo)}
    cpf_sql = ""
    if cpf:
        digits = "".join(ch for ch in cpf if ch.isdigit())
        if len(digits) < 3:
            raise HTTPException(422, "cpf deve ter ao menos 3 dígitos")
        params["cpf"] = search._like(digits)
        cpf_sql = "AND s.cpf_cnpj LIKE %(cpf)s"
    async with request.app.state.pool.connection() as conn:
        rows = await (await conn.execute(_SOCIOS.format(cpf=cpf_sql), params)).fetchall()
    pessoas: dict[str, dict] = {}
    for r in rows:
        chave = r["chave_pessoa"] or f"{r['nome']}|{r['cpf_cnpj']}"
        if chave not in pessoas:
            if len(pessoas) >= limite:
                continue
            pessoas[chave] = {"nome": r["nome"], "cpf_cnpj": r["cpf_cnpj"],
                              "tipo": profile.TIPO_SOCIO.get(r["tipo"]), "empresas": []}  # fmt: skip
        pessoas[chave]["empresas"].append({
            "cnpj_basico": r["cnpj_basico"],
            "razao_social": mask_cpf(r["razao_social"]),
            "qualificacao": profile._cod(r["qualificacao"], r["qualificacao_descricao"]),
            "data_entrada": r["data_entrada"],
        })  # fmt: skip
    return {"resultados": list(pessoas.values())}


_SUG_EMPRESA = f"""
SELECT e.cnpj, emp.razao_social, e.nome_fantasia, e.uf, e.situacao
FROM {LIVE}.empresa emp
JOIN {LIVE}.estabelecimento e ON e.cnpj_basico = emp.cnpj_basico AND e.matriz
WHERE emp.razao_social_norm LIKE %(q)s
ORDER BY (e.situacao = 2) DESC, length(emp.razao_social_norm)
LIMIT %(n)s
"""
_SUG_FANTASIA = f"""
SELECT e.cnpj, emp.razao_social, e.nome_fantasia, e.uf, e.situacao
FROM {LIVE}.estabelecimento e
LEFT JOIN {LIVE}.empresa emp ON emp.cnpj_basico = e.cnpj_basico
WHERE e.nome_fantasia_norm LIKE %(q)s
ORDER BY (e.situacao = 2) DESC, length(e.nome_fantasia_norm)
LIMIT %(n)s
"""
_SUG_SOCIO = f"""
SELECT DISTINCT ON (s.chave_pessoa) s.nome, s.cpf_cnpj, s.tipo
FROM {LIVE}.socio s WHERE s.nome_norm LIKE %(q)s
ORDER BY s.chave_pessoa
LIMIT %(n)s
"""


@router.get("/sugestoes", summary="Autocomplete: CNPJ, razão social, nome fantasia ou sócio")
async def sugestoes(
    request: Request,
    _: ClienteDep,
    q: Annotated[str, Query(min_length=3)],
    limite: Annotated[int, Query(ge=1, le=20)] = 5,
):
    """Busca única: devolve empresas e sócios que combinam com o texto digitado."""
    st = request.app.state
    doc = clean(q)
    if len(doc) == 14 and is_valid(doc):
        data = await get_profile(request, doc)
        empresas = [] if data is None else [{"cnpj": doc, "razao_social": data["razao_social"],
                                             "nome_fantasia": data["nome_fantasia"], "uf": data["endereco"]["uf"],
                                             "situacao": data["situacao"]["descricao"], "origem": "cnpj"}]  # fmt: skip
        return {"empresas": empresas, "socios": []}
    termo = normalize_text(q)
    if not termo or len(termo) < 3:
        raise HTTPException(422, "q deve ter ao menos 3 caracteres")
    params = {"q": search._like(termo).removeprefix("%"), "n": limite}  # prefixo: mais relevante e mais rápido
    async with st.pool.connection() as conn:
        razao = await (await conn.execute(_SUG_EMPRESA, params)).fetchall()
        fantasia = await (await conn.execute(_SUG_FANTASIA, params)).fetchall()
        pessoas = await (await conn.execute(_SUG_SOCIO, params)).fetchall()
    empresas, vistos = [], set()
    for origem, rows in (("razao_social", razao), ("nome_fantasia", fantasia)):
        for r in rows:
            if r["cnpj"] in vistos:
                continue
            vistos.add(r["cnpj"])
            empresas.append({"cnpj": r["cnpj"], "razao_social": mask_cpf(r["razao_social"]),
                             "nome_fantasia": mask_cpf(r["nome_fantasia"]),
                             "uf": r["uf"], "situacao": profile.SITUACAO.get(r["situacao"]),
                             "origem": origem})  # fmt: skip
    socios_out = [
        {"nome": r["nome"], "cpf_cnpj": r["cpf_cnpj"], "tipo": profile.TIPO_SOCIO.get(r["tipo"])} for r in pessoas
    ]
    return {"empresas": empresas[: limite * 2], "socios": socios_out}


@router.get("/cnaes", summary="Lista/autocomplete de CNAEs (para filtros)")
async def cnaes(
    request: Request,
    _: ClienteDep,
    q: Annotated[str | None, Query(description="Código ou parte da descrição")] = None,
    limite: Annotated[int, Query(ge=1, le=2000)] = 30,
):
    params: dict = {"n": limite}
    where = "true"
    if q:
        codigo = "".join(ch for ch in q if ch not in ".-/ ")
        if codigo.isdigit():  # "4721-1/02" ou "47211"
            where = "codigo::text LIKE %(cod)s"
            params["cod"] = f"{codigo}%"
        else:
            where = "unaccent_upper(descricao) LIKE %(desc)s"
            params["desc"] = search._like(normalize_text(q))
    async with request.app.state.pool.connection() as conn:
        return await (
            await conn.execute(
                f"SELECT codigo, descricao FROM {LIVE}.cnae WHERE {where} ORDER BY codigo LIMIT %(n)s", params
            )
        ).fetchall()


@router.get("/municipios", summary="Lista/autocomplete de municípios (para filtros)")
async def municipios(
    request: Request,
    _: ClienteDep,
    q: Annotated[str | None, Query(description="Parte do nome")] = None,
    uf: str | None = None,
    limite: Annotated[int, Query(ge=1, le=6000)] = 30,
):
    where, params = ["true"], {"n": limite}
    if q:
        where.append("unaccent_upper(nome) LIKE %(q)s")
        params["q"] = search._like(normalize_text(q)).removeprefix("%")
    if uf:
        where.append("uf = %(uf)s")
        params["uf"] = uf.upper()
    async with request.app.state.pool.connection() as conn:
        return await (
            await conn.execute(
                f"""SELECT codigo_siafi, codigo_ibge, nome, uf, lat, lng FROM geo.municipio_ibge
                    WHERE {" AND ".join(where)} ORDER BY nome, uf LIMIT %(n)s""",
                params,
            )
        ).fetchall()
