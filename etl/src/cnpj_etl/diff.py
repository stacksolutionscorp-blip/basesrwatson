"""Detecção de mudanças entre a carga anterior (rf_prev) e a nova (rf) para CNPJs monitorados.

Roda logo após o swap. Grava em app.alteracao e enfileira entregas em
app.webhook_entrega; o envio é feito pelo worker de webhooks da API.
"""

import psycopg

from cnpj_etl.db import LIVE, PREV, schema_exists

_SITUACAO = f"""
INSERT INTO app.alteracao (cnpj, referencia, tipo, antes, depois)
SELECT n.cnpj, %(ref)s, 'situacao',
       jsonb_build_object('situacao', o.situacao, 'data_situacao', o.data_situacao,
                          'motivo_situacao', o.motivo_situacao),
       jsonb_build_object('situacao', n.situacao, 'data_situacao', n.data_situacao,
                          'motivo_situacao', n.motivo_situacao)
FROM (SELECT DISTINCT cnpj FROM app.monitor) m
JOIN {LIVE}.estabelecimento n ON n.cnpj = m.cnpj
JOIN {PREV}.estabelecimento o ON o.cnpj = m.cnpj
WHERE (n.situacao, n.motivo_situacao) IS DISTINCT FROM (o.situacao, o.motivo_situacao)
ON CONFLICT DO NOTHING
"""

_ENDERECO_JSON = """jsonb_build_object('tipo_logradouro', {t}.tipo_logradouro, 'logradouro', {t}.logradouro,
    'numero', {t}.numero, 'complemento', {t}.complemento, 'bairro', {t}.bairro, 'cep', {t}.cep,
    'municipio', {t}.municipio, 'uf', {t}.uf)"""

_ENDERECO = f"""
INSERT INTO app.alteracao (cnpj, referencia, tipo, antes, depois)
SELECT n.cnpj, %(ref)s, 'endereco', {_ENDERECO_JSON.format(t="o")}, {_ENDERECO_JSON.format(t="n")}
FROM (SELECT DISTINCT cnpj FROM app.monitor) m
JOIN {LIVE}.estabelecimento n ON n.cnpj = m.cnpj
JOIN {PREV}.estabelecimento o ON o.cnpj = m.cnpj
WHERE n.endereco_hash IS DISTINCT FROM o.endereco_hash
   OR n.complemento IS DISTINCT FROM o.complemento
ON CONFLICT DO NOTHING
"""

_QUADRO = """
SELECT s.cnpj_basico,
       jsonb_agg(jsonb_build_object('nome', s.nome, 'cpf_cnpj', s.cpf_cnpj, 'qualificacao', s.qualificacao)
                 ORDER BY s.nome, s.cpf_cnpj, s.qualificacao) AS quadro
FROM {schema}.socio s
WHERE s.cnpj_basico IN (SELECT DISTINCT left(cnpj, 8) FROM app.monitor)
GROUP BY s.cnpj_basico
"""

_SOCIOS = f"""
WITH novo AS ({_QUADRO.format(schema=LIVE)}), velho AS ({_QUADRO.format(schema=PREV)})
INSERT INTO app.alteracao (cnpj, referencia, tipo, antes, depois)
SELECT m.cnpj, %(ref)s, 'socios', coalesce(v.quadro, '[]'), coalesce(n.quadro, '[]')
FROM (SELECT DISTINCT cnpj FROM app.monitor) m
LEFT JOIN novo n ON n.cnpj_basico = left(m.cnpj, 8)
LEFT JOIN velho v ON v.cnpj_basico = left(m.cnpj, 8)
WHERE coalesce(n.quadro, '[]') <> coalesce(v.quadro, '[]')
ON CONFLICT DO NOTHING
"""

_ENFILEIRA = """
INSERT INTO app.webhook_entrega (webhook_id, alteracao_id)
SELECT w.id, a.id
FROM app.alteracao a
JOIN app.monitor m ON m.cnpj = a.cnpj
JOIN app.webhook w ON w.api_key_id = m.api_key_id AND w.ativo
WHERE a.referencia = %(ref)s
ON CONFLICT DO NOTHING
"""


def detect_changes(conn: psycopg.Connection, referencia: str) -> tuple[int, int]:
    """Compara rf_prev × rf para os CNPJs monitorados. Devolve (alterações, entregas enfileiradas)."""
    if not schema_exists(conn, PREV):
        return 0, 0  # primeira carga: nada a comparar
    params = {"ref": referencia}
    with conn.transaction():
        changes = sum(conn.execute(q, params).rowcount for q in (_SITUACAO, _ENDERECO, _SOCIOS))
        queued = conn.execute(_ENFILEIRA, params).rowcount
    return changes, queued
