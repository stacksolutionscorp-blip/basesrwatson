"""Rede societária: empresa ↔ sócios ↔ outras empresas, em N saltos (formato cytoscape/vis-network)."""

from cnpj_core import mask_cpf
from psycopg import AsyncConnection

from cnpj_api.profile import SITUACAO
from cnpj_api.runtime import LIVE

_SOCIOS_DE = f"""
SELECT s.cnpj_basico, s.tipo, s.nome, s.cpf_cnpj, s.chave_pessoa, s.data_entrada, q.descricao AS qualificacao
FROM {LIVE}.socio s LEFT JOIN {LIVE}.qualificacao q ON q.codigo = s.qualificacao
WHERE s.cnpj_basico = ANY(%s)
"""
# Empresas em que uma PJ do conjunto é sócia (usa o índice em left(cpf_cnpj, 8)).
_PARTICIPACOES_PJ = f"""
SELECT s.cnpj_basico, left(s.cpf_cnpj, 8) AS socio_basico, s.data_entrada, q.descricao AS qualificacao
FROM {LIVE}.socio s LEFT JOIN {LIVE}.qualificacao q ON q.codigo = s.qualificacao
WHERE s.tipo = 1 AND left(s.cpf_cnpj, 8) = ANY(%s)
"""
_PARTICIPACOES_PESSOA = f"""
SELECT s.cnpj_basico, s.chave_pessoa, s.data_entrada, q.descricao AS qualificacao
FROM {LIVE}.socio s LEFT JOIN {LIVE}.qualificacao q ON q.codigo = s.qualificacao
WHERE s.chave_pessoa = ANY(%s)
"""
_EMPRESAS = f"""
SELECT emp.cnpj_basico, emp.razao_social, e.situacao, e.uf, e.cnpj
FROM {LIVE}.empresa emp
LEFT JOIN {LIVE}.estabelecimento e ON e.cnpj_basico = emp.cnpj_basico AND e.matriz
WHERE emp.cnpj_basico = ANY(%s)
"""


class _Builder:
    def __init__(self, max_nodes: int):
        self.max_nodes = max_nodes
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple, dict] = {}
        self.truncado = False

    def node(self, node_id: str, tipo: str, nivel: int, label: str | None = None, **dados) -> bool:
        """Adiciona o nó se couber; devolve True se ele é novo."""
        if node_id in self.nodes:
            return False
        if len(self.nodes) >= self.max_nodes:
            self.truncado = True
            return False
        self.nodes[node_id] = {"id": node_id, "tipo": tipo, "label": label, "nivel": nivel, "dados": dados}
        return True

    def edge(self, source: str, target: str, qualificacao: str | None, data_entrada) -> None:
        if source in self.nodes and target in self.nodes:
            key = (source, target, qualificacao)
            self.edges.setdefault(key, {"source": source, "target": target, "qualificacao": qualificacao,
                                        "data_entrada": data_entrada})  # fmt: skip


def _emp(basico: str) -> str:
    return f"empresa:{basico}"


def _pessoa(chave: str) -> str:
    return f"pessoa:{chave}"


async def build_graph(conn: AsyncConnection, cnpj_basico: str, niveis: int, max_nodes: int) -> dict:
    g = _Builder(max_nodes)
    g.node(_emp(cnpj_basico), "empresa", 0)
    empresas, pessoas = {cnpj_basico}, set()

    for nivel in range(1, niveis + 1):
        prox_empresas: set[str] = set()
        prox_pessoas: set[str] = set()
        if empresas:
            # sócios das empresas da fronteira
            for s in await (await conn.execute(_SOCIOS_DE, (list(empresas),))).fetchall():
                alvo = _emp(s["cnpj_basico"])
                if s["tipo"] == 1 and s["cpf_cnpj"] and len(s["cpf_cnpj"]) == 14:
                    basico = s["cpf_cnpj"][:8]
                    if g.node(_emp(basico), "empresa", nivel):
                        prox_empresas.add(basico)
                    g.edge(_emp(basico), alvo, s["qualificacao"], s["data_entrada"])
                elif s["chave_pessoa"]:
                    pid = _pessoa(s["chave_pessoa"])
                    tipo = "estrangeiro" if s["tipo"] == 3 else "PF"
                    if g.node(pid, "pessoa", nivel, s["nome"], cpf_cnpj=s["cpf_cnpj"], tipo_socio=tipo):
                        prox_pessoas.add(s["chave_pessoa"])
                    g.edge(pid, alvo, s["qualificacao"], s["data_entrada"])
            # empresas em que as empresas da fronteira são sócias
            for s in await (await conn.execute(_PARTICIPACOES_PJ, (list(empresas),))).fetchall():
                if g.node(_emp(s["cnpj_basico"]), "empresa", nivel):
                    prox_empresas.add(s["cnpj_basico"])
                g.edge(_emp(s["socio_basico"]), _emp(s["cnpj_basico"]), s["qualificacao"], s["data_entrada"])
        if pessoas:
            for s in await (await conn.execute(_PARTICIPACOES_PESSOA, (list(pessoas),))).fetchall():
                if g.node(_emp(s["cnpj_basico"]), "empresa", nivel):
                    prox_empresas.add(s["cnpj_basico"])
                g.edge(_pessoa(s["chave_pessoa"]), _emp(s["cnpj_basico"]), s["qualificacao"], s["data_entrada"])
        empresas, pessoas = prox_empresas, prox_pessoas
        if g.truncado or not (empresas or pessoas):
            break

    basicos = [n["id"].split(":", 1)[1] for n in g.nodes.values() if n["tipo"] == "empresa"]
    for r in await (await conn.execute(_EMPRESAS, (basicos,))).fetchall():
        n = g.nodes[_emp(r["cnpj_basico"])]
        n["label"] = mask_cpf(r["razao_social"])
        n["dados"] = {"cnpj_basico": r["cnpj_basico"], "cnpj_matriz": r["cnpj"],
                      "situacao": SITUACAO.get(r["situacao"]), "uf": r["uf"]}  # fmt: skip
    return {"nodes": list(g.nodes.values()), "edges": list(g.edges.values()), "truncado": g.truncado}
