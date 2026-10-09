FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini docker-entrypoint.sh ./

# Versie (git-commit) waarmee het image is gebouwd; getoond onder Bijwerken.
ARG GIT_COMMIT=""
ENV APP_VERSION=${GIT_COMMIT}

RUN useradd --create-home --uid 1000 declaratie \
    && mkdir -p /data/uploads \
    && chown -R declaratie /data \
    && chmod +x docker-entrypoint.sh
USER declaratie

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["web"]
