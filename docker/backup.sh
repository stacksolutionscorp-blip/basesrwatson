#!/bin/sh
# Backup diário dos dados que NÃO vêm da Receita (usuários, chaves, monitoramento, webhooks,
# histórico de alterações, log de acesso, cache de geocodificação, log do ETL).
# A base da Receita (schema rf) é recarregável pelo ETL e não entra no backup.
set -eu
DIR=/backups
RETENCAO_DIAS="${BACKUP_RETENCAO_DIAS:-14}"
HORA="${BACKUP_HORA:-03}"
mkdir -p "$DIR"

backup() {
    arquivo="$DIR/cnpj-$(date +%Y%m%d-%H%M).dump"
    echo "$(date -Iseconds) backup → $arquivo"
    if pg_dump -Fc -n app -n geo -n ops -f "$arquivo.tmp"; then
        mv "$arquivo.tmp" "$arquivo"
        find "$DIR" -name 'cnpj-*.dump' -mtime +"$RETENCAO_DIAS" -delete
        echo "$(date -Iseconds) ok ($(du -h "$arquivo" | cut -f1))"
    else
        rm -f "$arquivo.tmp"
        echo "$(date -Iseconds) FALHOU" >&2
    fi
}

[ "${1:-}" = "agora" ] && { backup; exit 0; }
while true; do
    # espera até a próxima HORA:00
    agora=$(date +%s)
    alvo=$(date -d "$(date +%F) $HORA:00" +%s 2>/dev/null || date -D '%Y-%m-%d %H:%M' -d "$(date +%F) $HORA:00" +%s)
    [ "$alvo" -le "$agora" ] && alvo=$((alvo + 86400))
    sleep $((alvo - agora))
    backup
done
