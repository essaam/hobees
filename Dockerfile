ARG UV_VERSION=0.8.15
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN groupadd --system --gid 10001 hobees \
    && useradd --system --uid 10001 --gid hobees --home-dir /home/hobees --create-home hobees \
    && mkdir -p /data/artifacts /data/skills \
    && chown -R hobees:hobees /data /home/hobees

ENV HOME=/tmp
USER hobees:hobees

ENTRYPOINT ["hobees"]
CMD ["--help"]
