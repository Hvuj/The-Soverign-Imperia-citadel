# workspace-intelligence-ui

Type: success
Date: 2026-06-08
Tags: [workspace-intelligence, citadel-ui, rest-api, static-files, stdlib-http, config-overlay]

## What was built

Workspace intelligence REST API (11 sub-endpoints under /api/workspace/) and hierarchical HTML UI (workspace/repo/dir/module/file pages) surfacing 24 pre-built workspace indexes inside the Citadel UI server.

## Key facts

- Static files under docs/brain/ are served at /brain/<file> automatically — no route registration.
- sys.path.insert(0, ROOT/"tools") enables local tool imports without packaging changes.
- citadel-ask-config.json::allowed_context_files FULLY replaces _DEFAULT_CONFIG list (overlay, not merge). Must keep both in sync.
- Index field shapes: repo-index key field = `name`; module-index value = list not dict; dir-index has minimal fields only.
- Health check for daemon = advisory/yellow (not critical).

## Validation

56 tests pass, py_compile clean, bash -n clean, all /api/workspace/* endpoints status=ok.

## Pattern card

See `docs/ai-context/feature-implementation-patterns.md` — "workspace-intelligence UI + REST API layer (2026-06-08)"

## Links

- [[citadel-ui-hardfix-2026-06-08]]
- [[citadel-api-health-full-embed-2026-06-08]]
- [[workspace-intelligence-system-2026-06-08]]
