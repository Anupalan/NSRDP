# NSRDP platform core. One image runs the API, the outbox worker and migrations.
# Base image is public and open source so it can be mirrored into a GI Cloud registry.
FROM python:3.12-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.lock ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps .

FROM python:3.12-slim-bookworm
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NSRDP_CONFIG_DIR=/app/config \
    NSRDP_CONTRACTS_DIR=/app/contracts
RUN groupadd --gid 10001 nsrdp && useradd --uid 10001 --gid nsrdp --no-create-home nsrdp
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
COPY contracts ./contracts
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "nsrdp.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
