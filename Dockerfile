FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY digitalframe ./digitalframe

RUN uv sync --locked --no-dev \
    && /app/.venv/bin/python -c "import pillow_heif"

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin digitalframe \
    && chown -R digitalframe:digitalframe /app

ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000

USER digitalframe
EXPOSE 8000
CMD ["digitalframe", "serve"]
