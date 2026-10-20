# cnpj-intel

Plataforma de inteligência empresarial por CNPJ a partir dos
[Dados Abertos CNPJ](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/cadastros/consultas/dados-publicos-cnpj)
da Receita Federal.

| Fase | Conteúdo | Status |
|---|---|---|
| 1 | ETL mensal → PostgreSQL, geocodificação | ✅ |
| 2 | API REST (FastAPI): consulta, busca, grafo, lote, exportação, monitoramento + webhooks | ✅ |
| 3 | Painel web (React + Leaflet + cytoscape): busca, empresa, mapa, grafo, monitoramento, admin | ✅ |
| — | Produção: HTTPS automático, backup, retenção de logs, alertas, CI | ✅ |

## Início rápido (5 minutos, com dados de exemplo)

Pré-requisitos: Git e Docker com Docker Compose.

```bash
git clone https://github.com/stacksolutionscorp-blip/basesrwatson.git && cd basesrwatson
cp .env.example .env                                   # troque POSTGRES_PASSWORD
docker compose up -d --build postgres redis api webhooks web backup
docker compose run --rm etl cnpj-etl demo              # amostra sintética no formato real da Receita
docker compose exec api cnpj-api criar-usuario --email voce@empresa.com --nome "Seu Nome" --admin
```

- **Painel**: http://localhost — entre com o e-mail e a senha criados (o primeiro acesso pede o aceite dos termos de uso)
- **API**: http://localhost/api/docs — para integrações, gere uma chave em *Administração → Chaves de API*
- Teste: `curl -H "X-API-Key: SUA_CHAVE" http://localhost/api/v1/cnpj/11222333000181`

Para a base real (≈7 GB de download, 1–1,5 h de carga, ~300 GB livres no pico), suba o
agendador com `docker compose up -d etl` ou rode `docker compose run --rm etl cnpj-etl run`.
Painel e API passam a servir a base real automaticamente quando a carga termina (sem reiniciar).

## Estrutura

```
libs/cnpj_core/    validação de CNPJ (numérico e alfanumérico), normalização de texto
  src/cnpj_core/sql/base.sql   DDL persistente compartilhado (ops, geo, app)
etl/               pacote cnpj_etl (CLI `cnpj-etl`) + testes
  src/cnpj_etl/sql/  DDL da carga mensal: rf_tables.sql, rf_indexes.sql
api/               pacote cnpj_api (FastAPI, CLI `cnpj-api`) + testes
web/               painel React (Vite, Tailwind, Leaflet, cytoscape) + testes unitários e E2E (Playwright)
docker/            Caddyfile, script de backup, entrypoint do ETL
.github/workflows/ CI: lint, testes Python com Postgres/Redis, front, E2E no navegador, build das imagens
docker-compose.yml postgres, redis, etl, api, webhooks (worker), web (Caddy), backup, nominatim (profile "geo")
```

## Modelo de dados

| Schema | Conteúdo | Ciclo de vida |
|---|---|---|
| `rf` | base servida: `empresa`, `estabelecimento`, `socio`, `simples` e auxiliares (`cnae`, `municipio`, `natureza_juridica`, `qualificacao`, `pais`, `motivo_situacao`) | recriado a cada mês |
| `rf_new` | carga em andamento | existe só durante a carga |
| `rf_prev` | mês anterior (base do diff de monitoramento e do rollback) | substituído a cada swap |
| `geo` | `municipio_ibge` (SIAFI↔IBGE + centroide), `geocode` (cache por endereço) | persistente |
| `ops` | `etl_run`, `etl_step` (log de cada execução) | persistente |
| `app` | `plano`, `api_key`, `access_log`, `monitor`, `webhook`, `alteracao`, `webhook_entrega` | persistente |

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
- `geom geography(Point,4326)` para busca por raio. `geo_precisao`: 1 município, 2 CEP, 3 rua, 4 número.
  Antes da geocodificação fina, todos os estabelecimentos de uma cidade ficam no mesmo ponto
  (centroide), o que degrada um índice espacial comum. Por isso há dois índices: GiST parcial
  só para pontos geocodificados e `(municipio, cnpj)` para os de centroide; a busca por raio
  combina os dois (ver `cnpj_api.search`).
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
   `NOTIFY cnpj_swapped, 'AAAA-MM'`. A API escuta esse canal, passa a servir a base nova e
   limpa o cache (ela não usa prepared statements no servidor, então não há plano velho).
9. **Diff de monitoramento**: compara `rf_prev × rf` para os CNPJs monitorados (situação,
   endereço, quadro societário), grava em `app.alteracao` e enfileira os webhooks.

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

## Painel web (Fase 3)

| Tela | O que faz |
|---|---|
| Início | Busca única com autocomplete: CNPJ (com validação do dígito), razão social, nome fantasia ou sócio |
| Empresa | Dados cadastrais, score de risco explicado, endereço e contato, mapa, CNAEs, quadro societário, filiais, botão de monitorar e histórico |
| Rede societária | Grafo interativo (1 a 3 níveis): clique numa empresa ou pessoa para navegar |
| Busca avançada | Todos os filtros da API, raio a partir de um clique no mapa ou da sua localização, mapa com agrupamento por região, exportação CSV/Excel; os filtros ficam na URL (dá para compartilhar o link) |
| Sócios | Pessoa ou empresa sócia → todas as empresas ligadas |
| Consulta em lote | Cole centenas de CNPJs (de qualquer planilha) e baixe o resultado em CSV |
| Monitoramento | CNPJs acompanhados, histórico de mudanças e cadastro/teste de webhooks |
| Uso da API | Consumo por dia e por rota, limites do plano |
| Administração | Usuários (papel, plano, ativar/desativar), chaves de API, planos, cargas da Receita (com etapas e erros), webhooks com falha, consumo por conta e auditoria do log de acesso |

**Login e segurança**: sessão por cookie `HttpOnly`/`SameSite=Lax` (12 h), senha com scrypt (mínimo 10
caracteres), bloqueio de 15 min após 10 senhas erradas, proteção contra CSRF em toda requisição que
altera dados. Usuários são criados pelo administrador (não há cadastro aberto).

**LGPD**: o primeiro acesso exige o aceite dos termos de uso (`api/src/cnpj_api/termos.md`, ou o seu
arquivo em `API_TERMOS_ARQUIVO`); mudar a versão do arquivo pede novo aceite a todos. Cada consulta fica
registrada com usuário, IP e o que foi consultado (*Administração → Auditoria*). CPFs aparecem só
mascarados — inclusive o CPF que a Receita anexa à razão social de empresários individuais e MEIs
("JOSÉ DA SILVA 12345678900" vira "JOSÉ DA SILVA ***456789**"), que também é retirado do índice de
busca para que ninguém localize uma pessoa digitando o CPF completo.

**Mapas**: os tiles vêm dos servidores públicos do OpenStreetMap, adequados a uso moderado. Com muito
tráfego, use um provedor de tiles (ou servidor próprio) com `VITE_TILE_URL` e `TILE_HOSTS` no `.env`.

## Produção

1. **Domínio e HTTPS**: aponte o DNS para o servidor, libere as portas 80 e 443 e defina no `.env`
   `SITE_ADDRESS=cnpj.suaempresa.com.br` e `API_COOKIE_SECURE=1`. O Caddy emite e renova o certificado
   sozinho (Let's Encrypt). Integrações passam a usar `https://cnpj.suaempresa.com.br/api/v1/...`.
2. **Portas**: Postgres, Redis, API direta e Nominatim só escutam em `127.0.0.1`; o acesso externo é
   sempre pelo Caddy, que também aplica cabeçalhos de segurança (CSP, HSTS, X-Frame-Options).
3. **Backup**: o serviço `backup` grava todo dia (às `BACKUP_HORA`) um `pg_dump` dos schemas `app`,
   `geo` e `ops` em `BACKUP_DIR`, mantendo `BACKUP_RETENCAO_DIAS` dias. A base da Receita (`rf`) não
   entra: é recarregada pelo ETL. Copie `BACKUP_DIR` para fora do servidor (S3, outro disco etc.).
   ```bash
   docker compose exec backup sh /backup.sh agora                 # backup imediato
   # restauração (banco novo ou após perda de dados):
   docker compose run --rm etl cnpj-etl db-init
   docker compose exec backup pg_restore --clean --if-exists -d cnpj /backups/cnpj-AAAAMMDD-HHMM.dump
   ```
4. **Alertas**: defina `ALERTA_WEBHOOK_URL` (Slack, Discord, Teams/Power Automate ou qualquer endpoint
   JSON) para ser avisado quando uma carga da Receita falhar, quando nenhuma carga for concluída há mais
   de `ALERTA_ETL_ATRASO_DIAS` dias ou quando webhooks de clientes esgotarem as tentativas. Os alertas
   também aparecem no log do serviço `webhooks` e em `GET /api/v1/admin/alertas`.
5. **Retenção**: o log de acesso é mantido por `API_LOG_RETENCAO_DIAS` (padrão 365; o Marco Civil exige
   no mínimo 6 meses). Sessões expiradas e entregas antigas de webhook também são limpas.
6. **Atualização**: `git pull && docker compose up -d --build`. O schema é atualizado sozinho na subida.

## API (Fase 2)

Documentação OpenAPI completa em `/docs` (Swagger) e `/redoc`; contrato em `/openapi.json`
(dá para gerar cliente em qualquer linguagem com `openapi-generator`).

| Método | Rota | Descrição |
|---|---|---|
| GET | `/v1/cnpj/{cnpj}` | Perfil completo: empresa, estabelecimento, sócios, CNAEs, Simples/MEI, coordenada, score de risco |
| GET | `/v1/cnpj/{cnpj}/filiais` | Todos os estabelecimentos do CNPJ básico (aceita 14 ou 8 caracteres) |
| GET | `/v1/socios?nome=&cpf=` | Sócio → empresas vinculadas (agrupado por pessoa) |
| GET | `/v1/busca` | Filtros combinados: `q`, `cnae`, `uf`, `municipio`/`municipio_ibge`, `lat`+`lng`+`raio_km`, `situacao`, `porte`, `capital_min/max`, `abertura_de/ate`, `simples`, `mei`, `matriz`; paginação |
| GET | `/v1/export?formato=csv\|xlsx` | Mesmos filtros da busca, em arquivo |
| GET | `/v1/sugestoes?q=` | Autocomplete único (CNPJ, razão social, nome fantasia, sócio) |
| GET | `/v1/grafo/{cnpj}?niveis=2` | Rede societária em formato cytoscape/vis-network |
| POST | `/v1/lote` | Até 500 CNPJs por chamada (`{"cnpjs": [...]}`) |
| POST/GET | `/v1/monitor` | Monitorar CNPJs / listar |
| DELETE | `/v1/monitor/{cnpj}` | Parar de monitorar |
| GET | `/v1/monitor/{cnpj}/historico` | Alterações detectadas entre cargas mensais |
| POST/GET | `/v1/webhooks` | Cadastrar (devolve o segredo uma única vez) / listar |
| DELETE | `/v1/webhooks/{id}` | Remover |
| POST | `/v1/webhooks/{id}/teste` | Dispara um evento de teste para validar a integração |
| GET | `/v1/uso` | Consumo da chave por dia e por rota, limites do plano |
| GET | `/v1/cnaes?q=` · `/v1/municipios?q=` | Listas para filtros e autocomplete |
| GET | `/health` | Saúde (sem autenticação): banco, Redis, mês da base servida |
| — | `/v1/auth/*`, `/v1/termos`, `/v1/admin/*` | Login, termos e administração do painel (documentados em `/docs`) |

**Autenticação**: header `X-API-Key: <chave>` (ou `Authorization: Bearer <chave>`). Chaves são
geradas por linha de comando e só o hash SHA-256 fica no banco:

```bash
docker compose exec api cnpj-api criar-chave --nome "sistema-x" --plano pro
docker compose exec api cnpj-api listar-chaves
docker compose exec api cnpj-api revogar-chave 3      # efeito em até 60 s
```

**Planos** (tabela `app.plano`, editável):

| Plano | req/min | req/dia | CNPJs por lote | linhas por export | CNPJs monitorados |
|---|---|---|---|---|---|
| free | 30 | 1.000 | 50 | 1.000 | 10 |
| pro | 300 | 50.000 | 500 | 50.000 | 1.000 |
| enterprise | 3.000 | 1.000.000 | 500 | 500.000 | 100.000 |

Toda resposta autenticada traz `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Limit-Day` e `X-RateLimit-Remaining-Day`; acima do limite: `429` com `Retry-After`.

**Erros**: `401` chave ausente/inválida · `404` não encontrado · `422` CNPJ com dígito
verificador inválido ou parâmetro inválido (validado antes de ir ao banco) · `429` limite ·
`503` base ainda não carregada ou banco fora · `504` consulta excedeu o tempo.

**CNPJ no caminho da URL**: com ou sem pontuação, numérico ou alfanumérico — exceto a barra
(`/`), que não cabe num segmento de URL. Use `11222333000181` ou `11.222.333.0001-81`.
No corpo do `/v1/lote` e no `q` da busca qualquer formatação é aceita.

**LGPD**: CPFs de sócios e representantes aparecem só no formato mascarado em que a Receita
publica (`***123456**`). Cada requisição fica em `app.access_log` (chave, rota, caminho
consultado, status, IP, user-agent, duração).

### Integrando outro sistema

```bash
curl -H "X-API-Key: $CHAVE" http://localhost/api/v1/cnpj/11222333000181
curl -H "X-API-Key: $CHAVE" "http://localhost/api/v1/busca?cnae=4321500&lat=-23.55&lng=-46.63&raio_km=15&situacao=2"
curl -H "X-API-Key: $CHAVE" -H "Content-Type: application/json" \
     -d '{"cnpjs": ["11.222.333/0001-81", "33.000.167/0001-01"]}' http://localhost/api/v1/lote
```

Python:

```python
import httpx

api = httpx.Client(base_url="http://localhost/api", headers={"X-API-Key": CHAVE}, timeout=30)
empresa = api.get("/v1/cnpj/11222333000181").json()
print(empresa["razao_social"], empresa["situacao"]["descricao"], empresa["score_risco"]["nivel"])
```

Node/TypeScript:

```ts
const r = await fetch("http://localhost/api/v1/cnpj/11222333000181", { headers: { "X-API-Key": CHAVE } });
if (r.status === 404) { /* CNPJ não existe na base */ }
const empresa = await r.json();
```

**Webhooks**: a cada carga mensal, mudanças de situação, endereço ou quadro societário dos CNPJs
monitorados geram um `POST` JSON no seu endpoint:

```json
{"evento": "cnpj.alterado", "id": 42, "cnpj": "11222333000181", "tipo": "situacao",
 "referencia": "2026-10", "antes": {"situacao": 2, ...}, "depois": {"situacao": 8, ...},
 "detectado_em": "2026-10-16T03:12:00Z"}
```

Valide a assinatura `X-CNPJ-Signature: sha256=<hex>` (HMAC-SHA256 do corpo com o segredo
recebido no cadastro) e responda 2xx. Falhas são retentadas em 1 min, 5 min, 30 min, 2 h,
6 h e 24 h. Por segurança, URLs que resolvem para rede interna/loopback são recusadas
(libere com `API_WEBHOOK_ALLOW_PRIVATE=1` só em desenvolvimento).

```python
import hashlib, hmac

def assinatura_valida(corpo: bytes, header: str, segredo: str) -> bool:
    esperado = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header)
```

**Score de risco** (0–100, maior = mais risco, com os fatores explicados na resposta): situação
não ativa (+50/+70), situação especial (+15), empresa com menos de 1 ano (+20) ou 3 anos (+10),
capital social abaixo de R$ 1.000 exceto MEI (+10), mudança de situação ou entrada de sócio
nos últimos 6 meses (+10 cada). Níveis: baixo < 30 ≤ médio < 60 ≤ alto.

### Desempenho medido

Base sintética de 1 milhão de estabelecimentos (todos no centroide de 2 municípios, o pior caso
para busca por raio), 4 vCPUs:

| Operação | Tempo |
|---|---|
| `GET /v1/cnpj/{cnpj}` com cache / sem cache | ~4 ms / ~15 ms |
| Busca por raio de 10 km (500 mil estabelecimentos dentro do raio) | 5–20 ms |
| Busca por UF + CNAE, por faixa de capital | ~2 ms |
| Busca por texto na razão social | ~350 ms |
| Raio + CNAE raro (quase nenhum resultado) | ~530 ms |
| Exportação CSV de 50 mil linhas | ~0,9 s |

Ponto de atenção para a base real (≈65 milhões): filtros muito seletivos dentro de um raio
que cobre uma capital podem passar de 1 s enquanto os estabelecimentos estiverem só com o
centroide do município; a geocodificação fina (Nominatim) elimina esse caso.

### Variáveis da API

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` / `REDIS_URL` | localhost | conexões (no compose são montadas automaticamente) |
| `API_PORT` | `8000` | porta publicada no compose |
| `API_POOL_MIN` / `API_POOL_MAX` | `2` / `20` | conexões com o Postgres por processo |
| `API_CACHE_TTL` | `86400` | segundos de cache do perfil (o swap mensal limpa o cache) |
| `API_STATEMENT_TIMEOUT_MS` | `15000` | tempo máximo de uma consulta (depois: 504) |
| `API_CORS_ORIGINS` | `*` | origens liberadas para chamadas do navegador |
| `API_TRUST_PROXY` | `0` | `1` atrás de proxy reverso (IP real no log de acesso) |
| `API_WEBHOOK_ALLOW_PRIVATE` | `0` | `1` libera webhooks para rede interna (só desenvolvimento) |
| `API_GRAPH_MAX_NODES` | `300` | limite de nós do grafo |

Em produção, coloque a API atrás de um proxy com HTTPS (nginx, Caddy, Traefik) e defina
`API_CORS_ORIGINS` com os domínios do seu front.

## Testes

```bash
uv sync --all-packages --all-groups
uv run pytest                                    # unitários
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres uv run pytest   # + integração
# Redis de teste: TEST_REDIS_URL (padrão redis://localhost:6379/15)
```

Os testes de integração criam e removem os bancos `cnpj_etl_test` e `cnpj_api_test`.

Frontend:

```bash
cd web && npm ci
npm run dev            # http://localhost:5173 (encaminha /api para a API em :8000)
npm run typecheck && npm test
# ponta a ponta no navegador (com API + front rodando e um usuário admin criado):
E2E_BASE_URL=http://localhost E2E_EMAIL=admin@demo.com E2E_SENHA=... npx playwright test
```

O CI (`.github/workflows/ci.yml`) roda tudo isso a cada push: lint, testes Python com Postgres/PostGIS
e Redis, tipos/testes/build do front, testes de navegador contra a stack com a base demo e o build das
três imagens Docker. O servidor precisa
de PostGIS e pg_trgm. Os ZIPs de teste (`etl/tests/receita_fixture.py`) reproduzem o
formato real e suas sujeiras: latin-1, `;` dentro de campo, aspas internas, quebra
de linha em campo, NUL, CRLF, datas zeradas, duplicatas e CNPJ alfanumérico.
