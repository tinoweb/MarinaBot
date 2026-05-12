#!/bin/bash
set -e

# Script de deploy via Git para VPS
# Coloque este arquivo na raiz do projeto e execute apos o git pull

echo "========================================"
echo "   Marina Bot - Deploy Script"
echo "========================================"

# Verifica se .env existe
if [ ! -f ".env" ]; then
    echo "[ERRO] Arquivo .env nao encontrado!"
    echo "Copie .env.docker para .env e configure suas variaveis."
    exit 1
fi

# Verifica variaveis obrigatorias
if ! grep -q "OPENAI_API_KEY=sk-" .env 2>/dev/null; then
    echo "[AVISO] OPENAI_API_KEY parece nao estar configurada no .env"
fi

echo "[1/4] Atualizando codigo..."
git pull origin main

echo "[2/4] Construindo containers..."
sudo docker compose -f docker-compose.prod.yml build

echo "[3/4] Subindo containers..."
sudo docker compose -f docker-compose.prod.yml up -d

echo "[4/4] Verificando status..."
sleep 3
sudo docker ps

echo ""
echo "========================================"
echo "   Deploy concluido!"
echo "========================================"
echo "Logs: sudo docker logs -f marina_bot_app"
echo ""
