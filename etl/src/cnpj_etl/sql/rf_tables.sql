-- Tabelas de uma carga mensal. {schema} é substituído (rf_new).
-- Sem PK/índices/FKs aqui: são criados depois do COPY (ver rf_indexes.sql).

CREATE TABLE {schema}.cnae              (codigo int, descricao text);
CREATE TABLE {schema}.motivo_situacao   (codigo int, descricao text);
CREATE TABLE {schema}.municipio         (codigo int, descricao text);  -- código SIAFI
CREATE TABLE {schema}.natureza_juridica (codigo int, descricao text);
CREATE TABLE {schema}.pais              (codigo int, descricao text);
CREATE TABLE {schema}.qualificacao      (codigo int, descricao text);

CREATE TABLE {schema}.empresa (
    cnpj_basico       char(8) NOT NULL,
    razao_social      text,
    razao_social_norm text,
    natureza_juridica int,
    qualificacao_resp int,
    capital_social    numeric(18,2),
    porte             smallint,  -- 0 não informado, 1 ME, 3 EPP, 5 demais
    ente_federativo   text
);

CREATE TABLE {schema}.estabelecimento (
    cnpj                   char(14) NOT NULL,
    cnpj_basico            char(8)  NOT NULL,
    matriz                 boolean,
    nome_fantasia          text,
    nome_fantasia_norm     text,
    situacao               smallint, -- 1 nula, 2 ativa, 3 suspensa, 4 inapta, 8 baixada
    data_situacao          date,
    motivo_situacao        int,
    data_inicio            date,
    cnae_principal         int,
    cnaes_secundarios      int[],
    tipo_logradouro        text,
    logradouro             text,
    numero                 text,
    complemento            text,
    bairro                 text,
    cep                    char(8),
    uf                     char(2),
    municipio              int,
    pais                   int,
    cidade_exterior        text,
    telefone1              text,
    telefone2              text,
    fax                    text,
    email                  text,
    situacao_especial      text,
    data_situacao_especial date,
    endereco_hash          bytea,
    geom                   geography(Point, 4326),
    geo_precisao           smallint  -- 1 município, 2 CEP, 3 rua, 4 número
);

CREATE TABLE {schema}.socio (
    id                bigint GENERATED ALWAYS AS IDENTITY,
    cnpj_basico       char(8) NOT NULL,
    tipo              smallint, -- 1 PJ, 2 PF, 3 estrangeiro
    nome              text,
    nome_norm         text,
    cpf_cnpj          text,     -- PF: mascarado como publicado (***123456**)
    qualificacao      int,
    data_entrada      date,
    pais              int,
    repr_cpf          text,
    repr_nome         text,
    repr_qualificacao int,
    faixa_etaria      smallint,
    chave_pessoa      text      -- nome_norm|cpf_cnpj
);

CREATE TABLE {schema}.simples (
    cnpj_basico           char(8) NOT NULL,
    opcao_simples         boolean,
    data_opcao_simples    date,
    data_exclusao_simples date,
    opcao_mei             boolean,
    data_opcao_mei        date,
    data_exclusao_mei     date
);
