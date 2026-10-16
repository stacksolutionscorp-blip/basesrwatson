# cnpj-intel

Plataforma de inteligência empresarial por CNPJ a partir dos
[Dados Abertos CNPJ](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/cadastros/consultas/dados-publicos-cnpj)
da Receita Federal.

| Fase | Conteúdo | Status |
|---|---|---|
| 1 | ETL mensal → PostgreSQL, geocodificação | ✅ |
| 2 | API REST (FastAPI) | — |
| 3 | Frontend (React + Leaflet) | — |

## Estrutura

```
libs/cnpj_core/    validação de CNPJ (numérico e alfanumérico) e normalização de texto
etl/               pacote cnpj_etl (CLI `cnpj-etl`) + testes
  src/cnpj_etl/sql/  DDL: base.sql (ops, geo), rf_tables.sql, rf_indexes.sql
docker/            entrypoint do container de ETL
docker-compose.yml postgres (PostGIS), redis, etl, nominatim (profile "geo")
```

## Modelo de dados

| Schema | Conteúdo | Ciclo de vida |
|---|---|---|
| `rf` | base servida: `empresa`, `estabelecimento`, `socio`, `simples` e auxiliares (`cnae`, `municipio`, `natureza_juridica`, `qualificacao`, `pais`, `motivo_situacao`) | recriado a cada mês |
| `rf_new` | carga em andamento | existe só durante a carga |
| `rf_prev` | mês anterior (base do diff de monitoramento e do rollback) | substituído a cada swap |
| `geo` | `municipio_ibge` (SIAFI↔IBGE + centroide), `geocode` (cache por endereço) | persistente |
| `ops` | `etl_run`, `etl_step` (log de cada execução) | persistente |

Decisões:

- **CNPJ é texto (`char(14)`)**, nunca número: desde jul/2026 a Receita emite CNPJs
  alfanuméricos (IN RFB 2.229/2024). `cnpj_core.is_valid` implementa o DV novo
  (compatível com o numérico).
- **Município da Receita é código SIAFI/TOM**, não IBGE; `geo.municipio_ibge` faz o de-para.
- **CPF de sócio** é gravado exatamente como a Receita publica (`***123456**`).
- `chave_pessoa = nome normalizado | CPF mascarado` liga a mesma pessoa física
  entre empresas (base do grafo societário).
- `cnaes_secundarios int[]` com índice GIN: filtro "tem o CNAE X" é
  `cnae_principal = X OR cnaes_secundarios @> ARRAY[X]`.
- Busca textual em colunas `*_norm` (maiúsculas, sem acento) com índice trigram.
  Para pesquisar, normalize o termo com `cnpj_core.normalize_text`.
- `geom geography(Point,4326)` + GiST para busca por raio (`ST_DWithin`).
  `geo_precisao`: 1 município, 2 CEP, 3 rua, 4 número.
- Sem foreign keys em `rf` (a base da Receita tem órfãos e FKs deixariam o COPY lento).

## Como o ETL funciona

1. **Descoberta**: lê o índice em `RF_BASE_URL` e escolhe o mês `AAAA-MM` mais recente
   com os 37 ZIPs publicados (um mês incompleto é ignorado).
2. **Download** resumível (HTTP Range) e idempotente em `DATA_DIR/raw/AAAA-MM/`.
3. **Leitura em streaming** do ZIP, sem descompactar em disco: cp1252/latin-1 → UTF-8,
   remoção de NUL, lotes cortados só em fim de registro. Linhas com nº de campos
   errado são descartadas e contadas, nunca completadas com null.
4. **Transformação** (polars): datas `AAAAMMDD` (`0`/`00000000` → null), capital
   `1.234,56` → numeric, CNAEs secundários → array, telefones, normalização, hash do
   endereço, coordenada (cache de geocodificação → centroide do município).
5. **COPY FREEZE** em `rf_new`, uma transação por tabela.
6. **Chaves primárias** (duplicatas da fonte são removidas e registradas), **índices**
   em paralelo, `ANALYZE`.
7. **Verificação**: aborta se alguma tabela vier vazia ou com menos de
   `ETL_MIN_ROW_RATIO` (90%) das linhas da base atual.
8. **Swap atômico**: `rf → rf_prev`, `rf_new → rf` numa transação curta, seguido de
   `NOTIFY cnpj_swapped, 'AAAA-MM'`. A API (Fase 2) escuta esse canal para reciclar o
   pool de conexões e limpar o cache.

Uma advisory lock impede duas cargas simultâneas. Em caso de falha, `rf` continua
intacto, `rf_new` é removido e a execução fica registrada como `failed`.

## Setup local

Pré-requisitos: Docker + Docker Compose. Para desenvolver fora do Docker:
Python ≥ 3.12 e [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env            # ajuste senha e tuning
docker compose up -d postgres redis
docker compose up -d etl        # db-init, carrega municípios e agenda as cargas
docker compose logs -f etl
```

O serviço `etl` roda `cnpj-etl schedule`: a cada `ETL_CHECK_INTERVAL_HOURS` verifica
se há mês novo na Receita e importa. Como não há data fixa de publicação, isso é mais
confiável que um cron mensal.

Comandos úteis:

```bash
docker compose run --rm etl cnpj-etl check     # mês disponível × importado × servido
docker compose run --rm etl cnpj-etl run       # força uma verificação/carga agora
docker compose run --rm etl cnpj-etl run --force
docker compose run --rm etl cnpj-etl status    # últimas execuções, linhas, tempos
docker compose run --rm etl cnpj-etl rollback  # volta a servir o mês anterior
docker compose run --rm etl cnpj-etl run --source-dir /data/zips/2026-09 --referencia 2026-09
```

### Geocodificação

Todos os estabelecimentos recebem o **centroide do município** já na carga. Isso basta
para buscas por raio de dezenas de km. Para precisão de rua ou número:

```bash
docker compose --profile geo up -d nominatim   # importa o extrato Brasil (~horas, ~100 GB)
docker compose run --rm etl cnpj-etl geo geocode --limit 500000            # só ativas
docker compose run --rm etl cnpj-etl geo geocode --uf SP --limit 100000    # priorizar uma UF
```

O resultado fica em `geo.geocode` (por hash do endereço normalizado), é aplicado na
hora em `rf.estabelecimento` e reaproveitado nas cargas seguintes. Endereços não
encontrados são retentados após 90 dias.

> A instância pública `nominatim.openstreetmap.org` **proíbe geocodificação em massa**.
> Use-a só para testes, com `NOMINATIM_RPS=1` e `NOMINATIM_CONCURRENCY=1`.

### Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `postgresql://cnpj:cnpj@localhost:5432/cnpj` | conexão (no compose é montada automaticamente) |
| `RF_BASE_URL` | `https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/` | índice das pastas mensais |
| `DATA_DIR` | `./data` (`/data` no container) | ZIPs baixados |
| `DOWNLOAD_CONCURRENCY` | `3` | downloads simultâneos |
| `ETL_BATCH_MB` | `128` | tamanho do lote descompactado por COPY |
| `ETL_INDEX_WORKERS` | `2` | índices criados em paralelo |
| `ETL_MAINTENANCE_WORK_MEM` | `1GB` | memória por criação de índice |
| `ETL_PARALLEL_WORKERS` | `2` | workers paralelos por índice |
| `ETL_MIN_ROW_RATIO` | `0.9` | proporção mínima de linhas para permitir o swap |
| `ETL_KEEP_ZIPS` | `1` | `0` apaga os ZIPs após carga bem-sucedida |
| `ETL_CHECK_INTERVAL_HOURS` | `24` | intervalo do `schedule` |
| `NOMINATIM_URL` | `http://nominatim:8080` | geocodificador |
| `NOMINATIM_RPS` / `NOMINATIM_CONCURRENCY` | `1` / `1` | limite de requisições |
| `NOMINATIM_USER_AGENT` | `cnpj-intel-etl/0.1` | identifique-se (exigido pelo OSM) |
| `MUNICIPIOS_URL` | CSV de kelvins/municipios-brasileiros | SIAFI↔IBGE + centroides |
| `PG_*` | ver `.env.example` | tuning do Postgres no compose |

### Dimensionamento

Volume da base real: cerca de 60 milhões de empresas, 65 milhões de estabelecimentos
e 26 milhões de sócios.

- **Disco**: 100–150 GB para o banco com índices, ×2 durante o swap (`rf` + `rf_new`),
  mais ~7 GB de ZIPs por mês. O Nominatim precisa de ~100 GB à parte.
- **Tempo**: medido em 4 vCPUs, 1 milhão de estabelecimentos leva ~20 s de carga. A base
  completa deve levar 1–1,5 h, sendo a maior parte em índices trigram.

## Testes

```bash
uv sync --all-packages --all-groups
uv run pytest                                    # unitários
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres uv run pytest   # + integração
```

Os testes de integração criam e removem o banco `cnpj_etl_test`. O servidor precisa
de PostGIS e pg_trgm. Os ZIPs de teste (`etl/tests/receita_fixture.py`) reproduzem o
formato real e suas sujeiras: latin-1, `;` dentro de campo, aspas internas, quebra
de linha em campo, NUL, CRLF, datas zeradas, duplicatas e CNPJ alfanumérico.
