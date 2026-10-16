#!/bin/sh
set -e

cnpj-etl db-init
# Centroides de município: precisam existir antes da 1ª carga.
cnpj-etl geo municipios --se-vazio || echo "aviso: não foi possível carregar os municípios agora"

exec "$@"
