FROM python:3.11-slim

# Evita prompts interativos
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instala dependencias minimas do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia codigo da aplicacao
COPY . .

# Torna o entrypoint executavel (converte CRLF->LF para compatibilidade Linux)
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Porta do Flask
EXPOSE 5000

# Entrypoint aguarda MySQL e inicia a aplicacao (sed garante LF mesmo com volume mount Windows)
CMD ["sh", "-c", "sed -i 's/\\r$//' /app/entrypoint.sh && exec /app/entrypoint.sh"]
