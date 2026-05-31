# syntax=docker/dockerfile:1.7
# peplink-device-mcp — multi-stage uv build. Build context is the repo root:
#   docker build -f apps/device/Dockerfile -t peplink-device-mcp .

# ---- builder: resolve + install into /app/.venv ----------------------------
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Copy only the workspace manifests first so dependency install is cached
# independently of source changes.
COPY pyproject.toml uv.lock ./
COPY apps/device/pyproject.toml apps/device/
COPY packages/peplink-core/pyproject.toml packages/peplink-core/
COPY packages/peplink-ic2/pyproject.toml packages/peplink-ic2/
COPY packages/peplink-mcp-shared/pyproject.toml packages/peplink-mcp-shared/

# External deps only (workspace packages installed after source is copied).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package peplink-device-mcp

# Now the source (incl. the manifest YAMLs the app reads at runtime).
COPY apps/ apps/
COPY packages/ packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package peplink-device-mcp

# ---- runtime: slim, non-root, HTTP transport -------------------------------
FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PEPLINK_MCP_CONFIG=/config/config.yaml \
    PEPLINK_MCP_SECRETS=/config/secrets.yaml
RUN useradd --system --uid 10001 --create-home --home-dir /app peplink
WORKDIR /app
# venv + source (same base python as builder, so the venv is portable).
COPY --from=builder --chown=peplink:peplink /app /app
USER peplink

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/health'); sys.exit(0)" || exit 1

# HTTP transport requires at least one mcp_keys entry (fails closed otherwise).
ENTRYPOINT ["peplink-device-mcp"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
