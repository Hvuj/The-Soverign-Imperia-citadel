# The Zero-Token MCP Bridge — Docker + egress isolation (Phase Z2b)

This makes **reading/searching your code cost 0 model tokens for any AI** (Claude Code, the CLI, another
MCP client) and enforces a hard security rule: **reads in, data-out blocked**. It is the *Pomerium extended
to the network* — your code and local indexes may be read, but nothing crosses the wall outward except to an
explicit allowlist.

## The pieces

| Server | Role | Network policy |
|---|---|---|
| **citadel-retrieval** (ours, FastMCP) | zero-token `search`/`read`/`context` over the local vector+BM25 index | native stdio (trusted, localhost-only) — or our image, no egress |
| **filesystem / git / memory / sequential-thinking** (official reference) | scoped file read, repo read, KG memory, reasoning | **`--network none`** — they touch your code, so it physically cannot leave |
| **fetch / context7** (reference) | pull web docs | the **only** internet-facing servers — `citadel_egress` network, **allowlist only**, read-only GET |
| **exec-sandbox** (Z4/Z5) | run + verify code | **`--network none`**, ephemeral, scoped worktree — a reverse shell has nowhere to go |

## Build our server image

```bash
docker build -f docker/mcp/Dockerfile -t citadel-mcp:local .
```

Publish to your registry (optional): `docker tag citadel-mcp:local ghcr.io/<you>/citadel-mcp:1 && docker push …`.

## Wire it

`mcp-servers.json` in this folder is the canonical topology — merge the entries you want into your project
`.mcp.json` or register them through the **Docker MCP Gateway** (Docker Desktop → MCP Toolkit). Our own
server is simplest run **natively** (it needs host Ollama + Redis): `python -m citadel.mcp.server`.

## The two hard rules

1. **Egress isolation.** Every server that touches your code runs `--network none`. Only Fetch/Context7 get
   the internet, and only to the allowlist (`docs.python.org`, `github.com`, `pypi.org`,
   `raw.githubusercontent.com` by default — edit in `mcp-servers.json`). Enforce the allowlist with the
   `egress-proxy` service (compose `--profile egress-proxy`) or a host firewall rule.
2. **Supply-chain / digest pinning (D6).** Replace every `@sha256:PIN_ME` with the real digest before use:
   `docker inspect --format='{{index .RepoDigests 0}}' mcp/filesystem:latest`. Never run a third-party MCP
   image by a floating tag.

## Backing services

`docker compose -f docker/mcp/docker-compose.yml up -d redis` starts a containerized Redis Stack if you
don't already run one natively. Our retrieval layer auto-detects RediSearch and falls back to a pure-Python
on-disk vector file when Redis is absent — so nothing here is a hard requirement.
