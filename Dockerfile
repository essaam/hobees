FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
RUN uv sync --no-dev
COPY src ./src
RUN groupadd --system --gid 10001 hobees \
    && useradd --system --uid 10001 --gid hobees --home-dir /home/hobees --create-home hobees \
    && mkdir -p /data/artifacts /data/skills
    && chown -R hobees:hobees /data /home/hobees
USER hobees
ENTRYPOINT ["hobees"]
CMD ["web --host 0.0.0.0 --port 8420"]
