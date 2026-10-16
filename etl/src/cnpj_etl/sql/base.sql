-- Objetos persistentes (não são recriados a cada carga mensal). Idempotente.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS geo;

CREATE TABLE IF NOT EXISTS ops.etl_run (
    id            bigserial PRIMARY KEY,
    referencia    char(7)     NOT NULL,              -- '2026-09'
    status        text        NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    iniciado_em   timestamptz NOT NULL DEFAULT now(),
    finalizado_em timestamptz,
    erro          text
);
CREATE INDEX IF NOT EXISTS etl_run_ref_idx ON ops.etl_run (referencia, status);

CREATE TABLE IF NOT EXISTS ops.etl_step (
    id                bigserial PRIMARY KEY,
    run_id            bigint      NOT NULL REFERENCES ops.etl_run (id) ON DELETE CASCADE,
    etapa             text        NOT NULL,  -- download | load | index | check | swap | geo
    arquivo           text,
    linhas            bigint,
    linhas_rejeitadas bigint,
    iniciado_em       timestamptz NOT NULL DEFAULT now(),
    duracao_ms        bigint,
    status            text        NOT NULL DEFAULT 'running',
    erro              text
);
CREATE INDEX IF NOT EXISTS etl_step_run_idx ON ops.etl_step (run_id);

-- Município da Receita (código SIAFI/TOM) ↔ IBGE, com centroide.
CREATE TABLE IF NOT EXISTS geo.municipio_ibge (
    codigo_siafi int PRIMARY KEY,
    codigo_ibge  int  NOT NULL UNIQUE,
    nome         text NOT NULL,
    uf           char(2) NOT NULL,
    lat          float8 NOT NULL,
    lng          float8 NOT NULL
);

-- Cache de geocodificação por endereço normalizado; sobrevive aos swaps.
-- lat/lng NULL = consultado sem resultado (não repetir antes do prazo).
CREATE TABLE IF NOT EXISTS geo.geocode (
    endereco_hash  bytea PRIMARY KEY,
    endereco_texto text        NOT NULL,
    lat            float8,
    lng            float8,
    precisao       smallint,   -- 2 CEP, 3 rua, 4 número
    fonte          text        NOT NULL,
    consultado_em  timestamptz NOT NULL DEFAULT now()
);
