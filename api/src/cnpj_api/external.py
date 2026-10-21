"""Fonte externa de dados por CNPJ (sem carregar a base da Receita).

Provedores com o formato do projeto minhareceita (o mesmo usado pela BrasilAPI):
- ``brasilapi``     → https://brasilapi.com.br/api/cnpj/v1/{cnpj}
- ``minhareceita``  → https://minhareceita.org/{cnpj}
- qualquer URL com ``{cnpj}`` (ex.: uma instância própria do minhareceita)

Os provedores são tentados em ordem: 404 = CNPJ inexistente (para); limite de requisições, erro 5xx
ou timeout = tenta o próximo. O resultado, já no formato do perfil da API (CPF mascarado, score de
risco), fica guardado em ``app.cnpj_externo`` e é reaproveitado por ``EXTERNO_TTL_HORAS``.
"""

import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta

import httpx
from cnpj_core import format_cnpj, mask_cpf
from psycopg_pool import AsyncConnectionPool

from cnpj_api import risk
from cnpj_api.profile import PORTE, SITUACAO

log = logging.getLogger("cnpj_api")

PROVIDERS = {
    "brasilapi": "https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
    "minhareceita": "https://minhareceita.org/{cnpj}",
}
TIPO_SOCIO = {1: "PJ", 2: "PF", 3: "estrangeiro"}
_SEM_REPRESENTANTE = {"", "***000000**", "00000000000"}


class ExternalUnavailable(RuntimeError):
    """Nenhum provedor respondeu (limite, erro ou rede)."""


def provider_templates(spec: str) -> list[tuple[str, str]]:
    """'brasilapi,minhareceita,https://x/{cnpj}' → [(nome, url_template), ...]."""
    out = []
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        if item in PROVIDERS:
            out.append((item, PROVIDERS[item]))
        elif "{cnpj}" in item:
            out.append((item.split("/")[2] if "//" in item else item, item))
        else:
            raise ValueError(f"provedor desconhecido: {item}")
    return out


# ---------------------------------------------------------------- conversão para o perfil da API


def _txt(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _cod(codigo, descricao) -> dict | None:
    codigo, descricao = _int(codigo), _txt(descricao)
    return None if codigo is None and descricao is None else {"codigo": codigo, "descricao": descricao}


def _strip_code(v: str | None) -> str | None:
    """'206-2 - Sociedade Empresária Limitada' → 'Sociedade Empresária Limitada'."""
    v = _txt(v)
    return v.split(" - ", 1)[1] if v and " - " in v and v.split(" - ", 1)[0].replace("-", "").isdigit() else v


def _digits(v) -> str | None:
    d = "".join(ch for ch in str(v or "") if ch.isdigit())
    return d or None


def to_profile(raw: dict, fonte: str, obtido_em: datetime, hoje: date | None = None) -> dict:
    """Converte a resposta (formato minhareceita/BrasilAPI) no mesmo formato de ``profile.build``."""
    hoje = hoje or date.today()
    cnpj = _digits(raw.get("cnpj")) or ""
    situacao = _int(raw.get("situacao_cadastral"))
    data_inicio = _date(raw.get("data_inicio_atividade"))
    porte = _int(raw.get("codigo_porte"))
    capital = raw.get("capital_social")
    mei = raw.get("opcao_pelo_mei")

    socios = []
    for s in raw.get("qsa") or []:
        repr_cpf = _txt(s.get("cpf_representante_legal"))
        repr_nome = _txt(s.get("nome_representante_legal"))
        representante = None
        if repr_nome or (repr_cpf and repr_cpf not in _SEM_REPRESENTANTE):
            representante = {
                "nome": repr_nome,
                "cpf": mask_cpf(repr_cpf) if repr_cpf not in _SEM_REPRESENTANTE else None,
                "qualificacao": _cod(
                    s.get("codigo_qualificacao_representante_legal"), s.get("qualificacao_representante_legal")
                ),
            }
        socios.append({
            "tipo": TIPO_SOCIO.get(_int(s.get("identificador_de_socio"))),
            "nome": _txt(s.get("nome_socio")),
            "cpf_cnpj": mask_cpf(_txt(s.get("cnpj_cpf_do_socio"))),  # garante a máscara mesmo se vier aberto
            "qualificacao": _cod(s.get("codigo_qualificacao_socio"), s.get("qualificacao_socio")),
            "data_entrada": _date(s.get("data_entrada_sociedade")),
            "pais": _cod(s.get("codigo_pais"), s.get("pais")),
            "faixa_etaria": _txt(s.get("faixa_etaria")),
            "representante": representante,
        })  # fmt: skip

    simples_vals = [raw.get(k) for k in ("opcao_pelo_simples", "opcao_pelo_mei", "data_opcao_pelo_simples")]
    simples = None
    if any(v is not None for v in simples_vals):
        simples = {
            "optante": raw.get("opcao_pelo_simples"),
            "data_opcao": _date(raw.get("data_opcao_pelo_simples")),
            "data_exclusao": _date(raw.get("data_exclusao_do_simples")),
            "mei": mei,
            "data_opcao_mei": _date(raw.get("data_opcao_pelo_mei")),
            "data_exclusao_mei": _date(raw.get("data_exclusao_do_mei")),
        }

    data_situacao = _date(raw.get("data_situacao_cadastral"))
    return {
        "cnpj": cnpj,
        "cnpj_formatado": format_cnpj(cnpj) if len(cnpj) == 14 else cnpj,
        "cnpj_basico": cnpj[:8],
        "matriz": {1: True, 2: False}.get(_int(raw.get("identificador_matriz_filial"))),
        "razao_social": mask_cpf(_txt(raw.get("razao_social"))),
        "nome_fantasia": mask_cpf(_txt(raw.get("nome_fantasia"))),
        "situacao": {
            "codigo": situacao,
            "descricao": SITUACAO.get(situacao)
            or (_txt(raw.get("descricao_situacao_cadastral")) or "").upper()
            or None,
            "data": data_situacao,
            "motivo": _cod(raw.get("motivo_situacao_cadastral"), raw.get("descricao_motivo_situacao_cadastral")),
        },
        "situacao_especial": _txt(raw.get("situacao_especial")),
        "data_situacao_especial": _date(raw.get("data_situacao_especial")),
        "data_inicio": data_inicio,
        "idade_anos": round((hoje - data_inicio).days / 365.25, 1) if data_inicio else None,
        "natureza_juridica": _cod(raw.get("codigo_natureza_juridica"), _strip_code(raw.get("natureza_juridica"))),
        "porte": _cod(porte, PORTE.get(porte) or _txt(raw.get("porte"))),
        "capital_social": capital,
        "ente_federativo": _txt(raw.get("ente_federativo_responsavel")),
        "cnae_principal": _cod(raw.get("cnae_fiscal"), raw.get("cnae_fiscal_descricao")),
        "cnaes_secundarios": [
            c
            for c in (_cod(x.get("codigo"), x.get("descricao")) for x in raw.get("cnaes_secundarios") or [])
            if c and c["codigo"]
        ],
        "endereco": {
            "tipo_logradouro": _txt(raw.get("descricao_tipo_de_logradouro")),
            "logradouro": _txt(raw.get("logradouro")),
            "numero": _txt(raw.get("numero")),
            "complemento": _txt(raw.get("complemento")),
            "bairro": _txt(raw.get("bairro")),
            "cep": _digits(raw.get("cep")),
            "municipio": {
                "codigo_siafi": _int(raw.get("codigo_municipio")),
                "codigo_ibge": _int(raw.get("codigo_municipio_ibge")),
                "nome": _txt(raw.get("municipio")),
            },
            "uf": _txt(raw.get("uf")),
            "pais": _cod(raw.get("codigo_pais"), raw.get("pais")),
            "cidade_exterior": _txt(raw.get("nome_cidade_no_exterior")),
            "lat": None,
            "lng": None,
            "geo_precisao": None,
        },
        "contato": {
            "telefones": [t for t in (_digits(raw.get("ddd_telefone_1")), _digits(raw.get("ddd_telefone_2"))) if t],
            "email": (_txt(raw.get("email")) or "").lower() or None,
        },
        "simples": simples,
        "socios": socios,
        "qtd_estabelecimentos": 1,  # a fonte externa não lista as filiais
        "score_risco": risk.score(
            situacao=situacao,
            data_inicio=data_inicio,
            capital_social=capital,
            data_situacao=data_situacao,
            situacao_especial=_txt(raw.get("situacao_especial")),
            datas_entrada_socios=[s["data_entrada"] for s in socios],
            mei=mei,
            hoje=hoje,
        ),
        "referencia": None,
        "fonte": fonte,
        "atualizado_em": obtido_em,
    }


# ---------------------------------------------------------------- consulta com cache


class ExternalSource:
    def __init__(self, pool: AsyncConnectionPool, client: httpx.AsyncClient, providers: str, ttl_hours: int):
        self.pool = pool
        self.client = client
        self.providers = provider_templates(providers)
        self.ttl = timedelta(hours=ttl_hours)

    async def _fetch(self, cnpj: str) -> tuple[str, dict] | None:
        """(provedor, json) ou None se o CNPJ não existe. ExternalUnavailable se ninguém respondeu."""
        erros = []
        for nome, template in self.providers:
            try:
                r = await self.client.get(template.format(cnpj=cnpj))
            except httpx.HTTPError as exc:
                erros.append(f"{nome}: {type(exc).__name__}")
                continue
            if r.status_code == 200:
                try:
                    return nome, r.json()
                except json.JSONDecodeError:
                    erros.append(f"{nome}: resposta inválida")
                    continue
            if r.status_code == 404:
                return None
            erros.append(f"{nome}: HTTP {r.status_code}")
        log.warning("fonte externa indisponível para %s: %s", cnpj, "; ".join(erros))
        raise ExternalUnavailable("; ".join(erros))

    async def _centroid(self, perfil: dict) -> None:
        ibge = perfil["endereco"]["municipio"]["codigo_ibge"]
        if not ibge:
            return
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute("SELECT lat, lng FROM geo.municipio_ibge WHERE codigo_ibge = %s", (ibge,))
            ).fetchone()
        if row:
            perfil["endereco"] |= {"lat": row["lat"], "lng": row["lng"], "geo_precisao": "municipio"}

    async def cached(self, cnpj: str) -> tuple[dict, datetime] | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute("SELECT dados, obtido_em FROM app.cnpj_externo WHERE cnpj = %s", (cnpj,))
            ).fetchone()
        return (row["dados"], row["obtido_em"]) if row else None

    async def refresh(self, cnpj: str) -> dict | None:
        """Consulta os provedores agora e atualiza o cache. None = CNPJ inexistente."""
        found = await self._fetch(cnpj)
        if found is None:
            return None
        fonte, raw = found
        agora = datetime.now(UTC)
        perfil = to_profile(raw, fonte, agora)
        await self._centroid(perfil)
        dados = json.loads(json.dumps(perfil, default=str))
        async with self.pool.connection() as conn:
            await conn.execute(
                """INSERT INTO app.cnpj_externo (cnpj, fonte, dados, obtido_em) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (cnpj) DO UPDATE SET fonte = EXCLUDED.fonte, dados = EXCLUDED.dados,
                                                     obtido_em = EXCLUDED.obtido_em""",
                (cnpj, fonte, json.dumps(dados), agora),
            )
        return dados

    async def get(self, cnpj: str) -> dict | None:
        """Perfil do cache se ainda válido; senão consulta. Se a fonte cair, devolve o cache vencido."""
        hit = await self.cached(cnpj)
        if hit and datetime.now(UTC) - hit[1] < self.ttl:
            return hit[0]
        try:
            return await self.refresh(cnpj)
        except ExternalUnavailable:
            if hit:
                return hit[0]
            raise

    async def get_many(self, cnpjs: list[str], concurrency: int) -> dict[str, dict | Exception | None]:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def one(c: str):
            async with sem:
                try:
                    return c, await self.get(c)
                except ExternalUnavailable as exc:
                    return c, exc

        return dict(await asyncio.gather(*(one(c) for c in cnpjs)))


# ---------------------------------------------------------------- monitoramento sem base local


def _situacao(p: dict) -> dict:
    s = p["situacao"]
    return {"situacao": s["codigo"], "data_situacao": s["data"], "motivo_situacao": (s["motivo"] or {}).get("codigo")}


def _endereco(p: dict) -> dict:
    e = p["endereco"]
    keys = ("tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep", "uf")
    return {k: e[k] for k in keys} | {"municipio": e["municipio"]["codigo_siafi"]}


def _socios(p: dict) -> list:
    return sorted(
        ({"nome": s["nome"], "cpf_cnpj": s["cpf_cnpj"], "qualificacao": (s["qualificacao"] or {}).get("codigo")}
         for s in p["socios"]),
        key=lambda s: (s["nome"] or "", s["cpf_cnpj"] or "", s["qualificacao"] or 0),
    )  # fmt: skip


def diff(antes: dict, depois: dict) -> list[tuple[str, object, object]]:
    """Mesmos tipos e formatos do diff mensal do ETL (situacao, endereco, socios)."""
    out = []
    for tipo, fn in (("situacao", _situacao), ("endereco", _endereco), ("socios", _socios)):
        a, b = fn(antes), fn(depois)
        if tipo == "situacao":
            changed = (a["situacao"], a["motivo_situacao"]) != (b["situacao"], b["motivo_situacao"])
        else:
            changed = a != b
        if changed:
            out.append((tipo, a, b))
    return out


async def refresh_monitored(source: ExternalSource, max_age: timedelta, pause_s: float = 1.0) -> int:
    """Reconsulta CNPJs monitorados que não estão na base local; registra mudanças e enfileira webhooks."""
    async with source.pool.connection() as conn:
        tem_base = (
            await (await conn.execute("SELECT to_regclass('rf.estabelecimento') IS NOT NULL AS ok")).fetchone()
        )["ok"]
        local = "AND NOT EXISTS (SELECT 1 FROM rf.estabelecimento r WHERE r.cnpj = m.cnpj)" if tem_base else ""
        alvos = await (
            await conn.execute(
                f"""SELECT DISTINCT m.cnpj FROM app.monitor m
                    LEFT JOIN app.cnpj_externo e ON e.cnpj = m.cnpj
                    WHERE (e.cnpj IS NULL OR e.obtido_em < now() - %s) {local}""",
                (max_age,),
            )
        ).fetchall()
    mudancas = 0
    hoje = date.today().isoformat()
    for row in alvos:
        cnpj = row["cnpj"]
        antes = await source.cached(cnpj)
        try:
            depois = await source.refresh(cnpj)
        except ExternalUnavailable:
            continue  # tenta no próximo ciclo
        if depois is not None and antes is not None:
            for tipo, a, b in diff(antes[0], depois):
                async with source.pool.connection() as conn, conn.transaction():
                    cur = await conn.execute(
                        """INSERT INTO app.alteracao (cnpj, referencia, tipo, antes, depois)
                           VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id""",
                        (cnpj, f"ext:{hoje}", tipo, json.dumps(a, default=str), json.dumps(b, default=str)),
                    )
                    nova = await cur.fetchone()
                    if nova:
                        mudancas += 1
                        await conn.execute(
                            """INSERT INTO app.webhook_entrega (webhook_id, alteracao_id)
                               SELECT w.id, %s FROM app.monitor m
                               JOIN app.webhook w ON w.api_key_id = m.api_key_id AND w.ativo
                               WHERE m.cnpj = %s ON CONFLICT DO NOTHING""",
                            (nova["id"], cnpj),
                        )
        await asyncio.sleep(pause_s)  # gentileza com a fonte pública
    if alvos:
        log.info("monitoramento externo: %s CNPJs reconsultados, %s mudanças", len(alvos), mudancas)
    return mudancas
