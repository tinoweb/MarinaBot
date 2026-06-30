#!/bin/sh
set -e

host="${MYSQL_HOST:-db}"
port="${MYSQL_PORT:-3306}"
user="${MYSQL_USER:-root}"
password="${MYSQL_PASSWORD}"

echo "Aguardando MySQL em ${host}:${port}..."

# Aguarda o MySQL ficar disponivel
while ! python -c "
import mysql.connector
try:
    c = mysql.connector.connect(host='${host}', port=${port}, user='${user}', password='${password}')
    c.close()
except Exception:
    exit(1)
" 2>/dev/null; do
    sleep 2
    echo "MySQL ainda nao esta pronto... aguardando"
done

echo "MySQL pronto! Iniciando aplicacao..."

exec python run.py
