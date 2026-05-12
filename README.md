# Marina Bot - Assistente Virtual WhatsApp

Chatbot de autoatendimento via WhatsApp com integracao de IA (OpenAI). Utiliza a biblioteca **WPP-Whatsapp** (API nao oficial baseada no WPPConnect) para comunicacao direta com o WhatsApp Web, sem necessidade de Twilio ou Meta Business API.

---

## Requisitos

- Docker + Docker Compose (recomendado)
- Ou: Python 3.8+, MySQL local, Google Chrome/Chromium

---

## Executar com Docker (Recomendado)

### 1. Clone e entre na pasta

```bash
git clone <repo>
cd marinaautomacao
```

### 2. Configure as variaveis de ambiente

Copie o template e edite:

```bash
cp .env.docker .env
```

Edite `.env` e preencha:
- `OPENAI_API_KEY`: sua chave da OpenAI
- `SECRET_KEY`: chave secreta forte para Flask
- `MYSQL_PASSWORD`: senha do root do MySQL (pode deixar a padrao ou alterar)

### 3. Suba os containers (desenvolvimento)

```bash
docker compose up --build
```

Isso sobe:
- MySQL na porta `3306`
- Flask + Bot WhatsApp na porta `5000`

O banco de dados sera criado automaticamente. O `entrypoint.sh` aguarda o MySQL ficar pronto antes de iniciar a app.

### 4. Escaneie o QR code

No terminal do container `marina_bot_app`, escaneie o QR code com o WhatsApp do celular na primeira execucao.

```bash
docker logs -f marina_bot_app
```

### 5. Acesse

- Site: `http://localhost:5000`
- Painel admin: `http://localhost:5000/admin` (admin / senha123)

### Parar

```bash
docker compose down
```

### Limpar dados (cuidado!)

```bash
docker compose down -v
```

---

## Subir em Producao (VPS) via Git

### 1. Clonar o repositorio na VPS

Na VPS:

```bash
cd /opt
git clone https://github.com/seu-usuario/marina-bot.git marina_bot
cd marina_bot
```

### 2. Configurar `.env`

```bash
cp .env.docker .env
nano .env
```

Preencha obrigatoriamente:
- `OPENAI_API_KEY`
- `SECRET_KEY` (chave forte, minimo 32 caracteres)
- `MYSQL_PASSWORD`

### 3. Primeiro deploy

```bash
sudo docker compose -f docker-compose.prod.yml up -d --build
```

Acompanhe o QR code nos logs:

```bash
sudo docker logs -f marina_bot_app
```

Escaneie com o WhatsApp do celular na primeira vez.

### 4. Deploys futuros (atualizacao via Git)

Na VPS, dentro da pasta do projeto:

```bash
git pull origin main
sudo docker compose -f docker-compose.prod.yml up -d --build
```

Ou use o script de deploy:

```bash
chmod +x deploy.sh
./deploy.sh
```

### 5. Proxy reverso (nginx/traefik)

Em producao, nao exponha a porta 5000 diretamente. Use nginx ou traefik como proxy reverso com HTTPS.

Exemplo nginx basico:

```nginx
server {
    listen 80;
    server_name bot.seudominio.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Executar sem Docker (Modo manual)

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configurar `.env`

Edite `.env` com suas credenciais (mesmos campos do `.env.docker`).

### 3. Criar banco MySQL manualmente

```sql
CREATE DATABASE marina_bot;
```

### 4. Testar conexao WhatsApp

```bash
python test_whatsapp.py
```

### 5. Rodar a aplicacao

```bash
python run.py
```

---

## Estrutura do Projeto

| Arquivo/Pasta | Funcao |
|---|---|
| `app/models/` | Modelos de dados e IA |
| `app/controllers/` | Rotas Flask |
| `app/services/whatsapp_service.py` | Bot WhatsApp (WPP-Whatsapp) |
| `app/templates/` | Paginas HTML |
| `app/static/` | CSS, JS, imagens |
| `Dockerfile` | Imagem da aplicacao |
| `docker-compose.yml` | Orquestracao dev (Flask + MySQL) |
| `docker-compose.prod.yml` | Orquestracao producao |
| `docker-compose.override.yml` | Override dev (hot reload) |
| `entrypoint.sh` | Aguarda MySQL e inicia app |
| `.env.docker` | Template de variaveis de ambiente |

---

## Funcionalidades

- Recebimento e envio de mensagens via WhatsApp Web (WPP-Whatsapp)
- Processamento de mensagens com IA (OpenAI GPT-3.5)
- Armazenamento de conversas e dados no MySQL
- Painel administrativo para acompanhamento

---

## Proximos Passos

- Conectar painel administrativo ao banco de dados (exibir conversas reais)
- Implementar autenticacao segura (hash de senha)
- Corrigir API da OpenAI para versao 1.3.0
- Adicionar exportacao de dados coletados
