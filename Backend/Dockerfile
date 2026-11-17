# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS dependencies

RUN python -m pip install --no-cache-dir poetry==2.3.2 \
    && python -m venv /opt/venv

WORKDIR /build
COPY pyproject.toml poetry.lock ./
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN poetry install --only main --extras generator --no-root --no-interaction

FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates fonts-dejavu-core fonts-liberation \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dependencies /opt/venv /opt/venv
WORKDIR /opt/ucts
COPY src/ ./src/
COPY --from=generator --chmod=a+rX --exclude=**/__pycache__ --exclude=**/*.pyc . /opt/certificate-service/app/
COPY docker-entrypoint.sh /usr/local/bin/ucts-entrypoint

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/opt/ucts/src:/opt/certificate-service \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp

USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/usr/local/bin/ucts-entrypoint"]
CMD ["uvicorn", "ucts.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
