# Build a partir da raiz do repositório (usa libs/cnpj_core).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app

COPY libs/cnpj_core libs/cnpj_core
COPY etl/pyproject.toml etl/pyproject.toml
COPY etl/src etl/src
RUN pip install ./libs/cnpj_core ./etl

COPY docker/etl-entrypoint.sh /usr/local/bin/etl-entrypoint.sh
RUN chmod +x /usr/local/bin/etl-entrypoint.sh

VOLUME ["/data"]
ENTRYPOINT ["etl-entrypoint.sh"]
CMD ["cnpj-etl", "schedule"]
