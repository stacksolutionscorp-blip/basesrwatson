# Build a partir da raiz do repositório (usa libs/cnpj_core).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY libs/cnpj_core libs/cnpj_core
COPY api/pyproject.toml api/pyproject.toml
COPY api/src api/src
RUN pip install ./libs/cnpj_core ./api

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["cnpj-api", "serve", "--workers", "2"]
