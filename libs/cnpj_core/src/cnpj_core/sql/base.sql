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

-- ---------------------------------------------------------------- app (API)
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.plano (
    id             text PRIMARY KEY,
    nome           text NOT NULL,
    req_por_minuto int  NOT NULL,
    req_por_dia    int  NOT NULL,
    lote_max       int  NOT NULL,  -- CNPJs por chamada em POST /v1/lote
    export_max     int  NOT NULL,  -- linhas por exportação
    monitor_max    int  NOT NULL   -- CNPJs monitorados por chave
);
INSERT INTO app.plano VALUES
    ('free',       'Free',          30,     1000,  50,   1000,     10),
    ('pro',        'Pro',          300,    50000, 500,  50000,   1000),
    ('enterprise', 'Enterprise',  3000,  1000000, 500, 500000, 100000)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS app.api_key (
    id            bigserial PRIMARY KEY,
    nome          text        NOT NULL,          -- cliente / sistema integrado
    prefixo       text        NOT NULL,          -- início da chave, para identificação
    hash          bytea       NOT NULL UNIQUE,   -- sha256 da chave (a chave em si não é guardada)
    plano_id      text        NOT NULL REFERENCES app.plano (id),
    ativo         boolean     NOT NULL DEFAULT true,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    ultimo_uso_em timestamptz
);

-- Log de acesso por chave (LGPD): quem consultou o quê e quando.
CREATE TABLE IF NOT EXISTS app.access_log (
    id         bigserial PRIMARY KEY,
    api_key_id bigint,
    metodo     text        NOT NULL,
    rota       text        NOT NULL,   -- template, ex.: /v1/cnpj/{cnpj}
    caminho    text        NOT NULL,   -- caminho real, ex.: /v1/cnpj/11222333000181
    consulta   text,                   -- query string
    status     smallint    NOT NULL,
    duracao_ms int         NOT NULL,
    ip         inet,
    user_agent text,
    criado_em  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS access_log_key_idx ON app.access_log (api_key_id, criado_em);

CREATE TABLE IF NOT EXISTS app.monitor (
    api_key_id bigint      NOT NULL REFERENCES app.api_key (id) ON DELETE CASCADE,
    cnpj       char(14)    NOT NULL,
    criado_em  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (api_key_id, cnpj)
);
CREATE INDEX IF NOT EXISTS monitor_cnpj_idx ON app.monitor (cnpj);

CREATE TABLE IF NOT EXISTS app.webhook (
    id         bigserial PRIMARY KEY,
    api_key_id bigint      NOT NULL REFERENCES app.api_key (id) ON DELETE CASCADE,
    url        text        NOT NULL,
    segredo    text        NOT NULL,   -- assina o corpo (HMAC-SHA256)
    ativo      boolean     NOT NULL DEFAULT true,
    criado_em  timestamptz NOT NULL DEFAULT now()
);

-- Mudanças detectadas entre duas cargas mensais (rf_prev → rf) para CNPJs monitorados.
CREATE TABLE IF NOT EXISTS app.alteracao (
    id           bigserial PRIMARY KEY,
    cnpj         char(14)    NOT NULL,
    referencia   char(7)     NOT NULL,
    tipo         text        NOT NULL CHECK (tipo IN ('situacao', 'endereco', 'socios')),
    antes        jsonb,
    depois       jsonb,
    detectado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cnpj, referencia, tipo)
);
CREATE INDEX IF NOT EXISTS alteracao_cnpj_idx ON app.alteracao (cnpj, detectado_em DESC);

CREATE TABLE IF NOT EXISTS app.webhook_entrega (
    id                   bigserial PRIMARY KEY,
    webhook_id           bigint      NOT NULL REFERENCES app.webhook (id) ON DELETE CASCADE,
    alteracao_id         bigint      NOT NULL REFERENCES app.alteracao (id) ON DELETE CASCADE,
    status               text        NOT NULL DEFAULT 'pendente'
                         CHECK (status IN ('pendente', 'entregue', 'falhou')),
    tentativas           int         NOT NULL DEFAULT 0,
    proxima_tentativa_em timestamptz NOT NULL DEFAULT now(),
    ultimo_status_http   int,
    ultimo_erro          text,
    entregue_em          timestamptz,
    UNIQUE (webhook_id, alteracao_id)
);
CREATE INDEX IF NOT EXISTS webhook_entrega_fila_idx
    ON app.webhook_entrega (proxima_tentativa_em) WHERE status = 'pendente';

-- ---------------------------------------------------------------- usuários do painel web
CREATE TABLE IF NOT EXISTS app.usuario (
    id                bigserial PRIMARY KEY,
    email             text        NOT NULL,
    nome              text        NOT NULL,
    senha_hash        text        NOT NULL,             -- scrypt (ver cnpj_api.users)
    papel             text        NOT NULL DEFAULT 'usuario' CHECK (papel IN ('admin', 'usuario')),
    ativo             boolean     NOT NULL DEFAULT true,
    termos_versao     text,                             -- versão dos termos de uso aceita
    termos_aceitos_em timestamptz,
    criado_em         timestamptz NOT NULL DEFAULT now(),
    ultimo_login_em   timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS usuario_email_uidx ON app.usuario (lower(email));

-- Cada usuário tem uma chave "pessoal" interna: monitoramento, webhooks e limites do painel
-- usam a mesma estrutura das integrações. Chaves de integração também podem pertencer a um usuário.
ALTER TABLE app.api_key ADD COLUMN IF NOT EXISTS usuario_id bigint REFERENCES app.usuario (id) ON DELETE CASCADE;
ALTER TABLE app.api_key ADD COLUMN IF NOT EXISTS pessoal boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS api_key_pessoal_uidx ON app.api_key (usuario_id) WHERE pessoal;

CREATE TABLE IF NOT EXISTS app.sessao (
    token_hash bytea       PRIMARY KEY,                 -- sha256 do token do cookie
    usuario_id bigint      NOT NULL REFERENCES app.usuario (id) ON DELETE CASCADE,
    criado_em  timestamptz NOT NULL DEFAULT now(),
    expira_em  timestamptz NOT NULL,
    ip         inet,
    user_agent text
);
CREATE INDEX IF NOT EXISTS sessao_expira_idx ON app.sessao (expira_em);

ALTER TABLE app.access_log ADD COLUMN IF NOT EXISTS usuario_id bigint;
CREATE INDEX IF NOT EXISTS access_log_criado_idx ON app.access_log (criado_em);
CREATE INDEX IF NOT EXISTS access_log_usuario_idx ON app.access_log (usuario_id, criado_em);

-- Alertas operacionais já enviados (evita repetir a mesma notificação).
CREATE TABLE IF NOT EXISTS app.alerta (
    id         bigserial PRIMARY KEY,
    tipo       text        NOT NULL,
    chave      text        NOT NULL,
    mensagem   text        NOT NULL,
    enviado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tipo, chave)
);

-- Maiúsculas sem acento (mesma regra de cnpj_core.normalize_text) para buscas em tabelas pequenas.
CREATE OR REPLACE FUNCTION public.unaccent_upper(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT upper(translate(t,
        'áàâãäåÁÀÂÃÄÅéèêëÉÈÊËíìîïÍÌÎÏóòôõöÓÒÔÕÖúùûüÚÙÛÜçÇñÑýÿÝ',
        'aaaaaaAAAAAAeeeeEEEEiiiiIIIIoooooOOOOOuuuuUUUUcCnNyyY'))
$$;

-- ---------------------------------------------------------------- leads (prospecção)
-- Carteira compartilhada pela equipe: um status por CNPJ evita dois vendedores no mesmo lead.
CREATE TABLE IF NOT EXISTS app.lead (
    cnpj            char(14)    PRIMARY KEY,
    status          text        NOT NULL DEFAULT 'novo' CHECK (status IN
                    ('novo', 'contatado', 'interessado', 'proposta', 'fechado', 'sem_interesse')),
    responsavel_id  bigint      REFERENCES app.usuario (id) ON DELETE SET NULL,
    nota            text,       -- última anotação
    proximo_contato date,
    criado_em       timestamptz NOT NULL DEFAULT now(),
    atualizado_em   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lead_status_idx ON app.lead (status, atualizado_em DESC);

CREATE TABLE IF NOT EXISTS app.lead_evento (
    id         bigserial PRIMARY KEY,
    cnpj       char(14)    NOT NULL,
    usuario_id bigint      REFERENCES app.usuario (id) ON DELETE SET NULL,
    status     text,
    nota       text,
    criado_em  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lead_evento_cnpj_idx ON app.lead_evento (cnpj, criado_em DESC);

-- Pedidos de não contato (LGPD / boa prática): bloqueiam o CNPJ, o telefone ou o e-mail nas buscas.
CREATE TABLE IF NOT EXISTS app.nao_contatar (
    id         bigserial PRIMARY KEY,
    cnpj       char(14),
    telefone   text,
    email      text,
    motivo     text,
    usuario_id bigint      REFERENCES app.usuario (id) ON DELETE SET NULL,
    criado_em  timestamptz NOT NULL DEFAULT now(),
    CHECK (cnpj IS NOT NULL OR telefone IS NOT NULL OR email IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS nao_contatar_cnpj_idx ON app.nao_contatar (cnpj);
CREATE INDEX IF NOT EXISTS nao_contatar_tel_idx ON app.nao_contatar (telefone);
CREATE INDEX IF NOT EXISTS nao_contatar_email_idx ON app.nao_contatar (lower(email));

-- Cache da fonte externa por CNPJ (cnpj_api.external).
CREATE TABLE IF NOT EXISTS app.cnpj_externo (
    cnpj      char(14)    PRIMARY KEY,
    fonte     text        NOT NULL,
    dados     jsonb       NOT NULL,
    obtido_em timestamptz NOT NULL
);

-- Referência das alterações: "AAAA-MM" (carga mensal) ou "ext:AAAA-MM-DD" (fonte externa).
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'app' AND table_name = 'alteracao' AND column_name = 'referencia') = 'character' THEN
        ALTER TABLE app.alteracao ALTER COLUMN referencia TYPE text;
    END IF;
END $$;
