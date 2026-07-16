# Our own MCP retrieval server image (Zero-Token Sovereign, Phase Z2b).
# Read-only, never_call_claude, no network egress of its own — it serves the local index to any MCP client.
FROM python:3.12-slim

WORKDIR /app

# Only the retrieval + MCP deps; the package itself runs from source on PYTHONPATH.
RUN pip install --no-cache-dir "mcp>=1.27,<2" "redis>=5" "numpy>=1.26"

COPY src ./src
COPY tools ./tools

ENV PYTHONPATH=/app/src \
    CITADEL_WORKSPACE=/workspace \
    PYTHONUNBUFFERED=1

# The workspace is mounted read-only; the vector index lives in a named volume at /workspace/.claude/state.
# stdio transport — the Docker MCP Gateway / client runs this with `docker run -i --rm`.
ENTRYPOINT ["python", "-m", "citadel.mcp.server"]
