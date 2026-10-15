FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.22 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV HG_TARGET=cloud PORT=8765
EXPOSE 8765
CMD ["sh", "-c", "uv run --no-sync python -m handoff_graph.mcp_server --http ${PORT}"]
