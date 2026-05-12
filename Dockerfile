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

# Torna o entrypoint executavel
RUN chmod +x /app/entrypoint.sh

# Porta do Flask
EXPOSE 5000

# Entrypoint aguarda MySQL e inicia a aplicacao
CMD ["/app/entrypoint.sh"]
