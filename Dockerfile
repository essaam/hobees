FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 1. Install uv system-wide as root
RUN pip install --no-cache-dir uv

# 2. Create the non-root user and data directories first
RUN groupadd --system --gid 10001 hobees \
    && useradd --system --uid 10001 --gid hobees --home-dir /home/hobees --create-home hobees \
    && mkdir -p /data/artifacts /data/skills \
    && chown -R hobees:hobees /data /home/hobees

# 3. Switch to user space BEFORE running uv commands
USER hobees
WORKDIR /home/hobees

# 4. Add the user's local bin directory to PATH
ENV PATH="/home/hobees/.local/bin:${PATH}"

# 5. Install from PyPi
RUN uv tool install hobees

ENTRYPOINT ["hobees"]
CMD ["web", "--host", "0.0.0.0", "--port", "6543"]