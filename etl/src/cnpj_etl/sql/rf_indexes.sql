-- Índices criados após a carga, um comando por bloco (separador: linha com o
-- marcador de bloco abaixo). Os blocos rodam em paralelo (ETL_INDEX_WORKERS).
-- As chaves primárias são criadas antes, em finalize.add_primary_key, porque
-- podem exigir deduplicação.

-- @
CREATE INDEX ON {schema}.empresa USING gin (razao_social_norm gin_trgm_ops);
-- @
CREATE INDEX ON {schema}.estabelecimento (cnpj_basico);
-- @
CREATE INDEX ON {schema}.estabelecimento USING gin (nome_fantasia_norm gin_trgm_ops);
-- @
CREATE INDEX ON {schema}.estabelecimento (cnae_principal);
-- @
CREATE INDEX ON {schema}.estabelecimento USING gin (cnaes_secundarios);
-- @
CREATE INDEX ON {schema}.estabelecimento (uf, municipio, situacao);
-- @
CREATE INDEX ON {schema}.estabelecimento (situacao);
-- @
CREATE INDEX ON {schema}.estabelecimento (data_inicio);
-- @
-- Busca por raio em duas partes (ver cnpj_api.search): pontos geocodificados pelo índice espacial e
-- estabelecimentos que só têm o centroide do município por (municipio, cnpj) — milhões de pontos
-- idênticos degradariam o GiST.
CREATE INDEX ON {schema}.estabelecimento USING gist (geom) WHERE geo_precisao > 1;
-- @
CREATE INDEX ON {schema}.estabelecimento (municipio, cnpj) WHERE geo_precisao = 1;
-- @
CREATE INDEX ON {schema}.estabelecimento (endereco_hash);
-- @
CREATE INDEX ON {schema}.socio (cnpj_basico);
-- @
CREATE INDEX ON {schema}.socio USING gin (nome_norm gin_trgm_ops);
-- @
CREATE INDEX ON {schema}.socio (chave_pessoa);
-- @
CREATE INDEX ON {schema}.socio ((left(cpf_cnpj, 8))) WHERE tipo = 1;  -- empresas onde uma PJ é sócia (grafo)
