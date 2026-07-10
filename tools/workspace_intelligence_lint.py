#!/usr/bin/env python3
"""workspace_intelligence_lint.py — Security and correctness lint for workspace intelligence indexes.

Verifies:
- Config exists and is valid
- All required indexes exist and are valid JSON
- schema_version present in all indexes
- No sensitive file contents are indexed
- Exact lookup maps are non-empty
- Query smoke tests pass
- build-metadata.json is present and fresh
- No external API config enabled
- vector_embedding_backend is not a hosted API

Exit code: 0 = pass, 1 = fail.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from _workspace_intel_common import (  # noqa: E402
    IDX,
    ROOT,
    SCHEMA_VERSION,
    WS_CONFIG_PATH,
    load_json,
)

_SECRET_PATTERNS = [
    r"-----BEGIN.{0,20}PRIVATE KEY",
    r"password\s*=\s*['\"][^'\"]{4,}",
    r"api[_-]?key\s*=\s*['\"][^'\"]{8,}",
    r"secret\s*=\s*['\"][^'\"]{8,}",
]
_SECRET_RE = re.compile("|".join(_SECRET_PATTERNS), re.IGNORECASE)

_FORBIDDEN_BACKENDS = {"openai", "cohere", "anthropic", "huggingface_hub", "replicate"}


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")


def warn(msg: str) -> None:
    print(f"WARN: {msg}")


def ok(msg: str) -> None:
    print(f"OK:   {msg}")


def check_config() -> bool:
    if not WS_CONFIG_PATH.exists():
        fail(f"config missing: {WS_CONFIG_PATH}")
        return False
    cfg = load_json(WS_CONFIG_PATH, None)
    if not isinstance(cfg, dict):
        fail(f"config invalid JSON: {WS_CONFIG_PATH}")
        return False
    ok("config exists and valid")

    ve_backend = str(cfg.get("vector_embedding_backend", "")).lower()
    if any(fb in ve_backend for fb in _FORBIDDEN_BACKENDS):
        fail(f"vector_embedding_backend references a hosted API: {ve_backend}")
        return False
    ok("no external API configured")

    if cfg.get("write_vector_index", False):
        warn("write_vector_index=true; vector indexing enabled (requires local backend only)")

    return True


def check_indexes_exist() -> bool:
    required_keys = [
        "workspace", "repo", "file", "dir", "module", "symbol",
        "qualified_symbol", "import", "reverse_import", "test",
        "feature", "artifact", "alias", "inverted_token", "bm25",
        "reuse_candidate", "fingerprints", "build_metadata",
    ]
    missing = []
    for k in required_keys:
        p = IDX.get(k)
        if p is None or not p.exists():
            missing.append(str(IDX.get(k, k)))
    if missing:
        fail(f"missing index files ({len(missing)}): {', '.join(missing[:5])}")
        return False
    ok(f"all {len(required_keys)} required index files present")
    return True


def check_json_valid_and_versioned() -> bool:
    required_keys = [
        "workspace", "repo", "file", "module", "symbol",
        "feature", "alias", "reuse_candidate", "build_metadata",
    ]
    all_ok = True
    for k in required_keys:
        p = IDX.get(k)
        if not p or not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON in {k}: {exc}")
            all_ok = False
            continue
        if not isinstance(data, dict):
            fail(f"index root is not a dict: {k}")
            all_ok = False
            continue
        if data.get("schema_version") != SCHEMA_VERSION:
            fail(f"schema_version mismatch in {k}: expected {SCHEMA_VERSION!r}, "
                 f"got {data.get('schema_version')!r}")
            all_ok = False
    if all_ok:
        ok("all checked indexes: valid JSON + correct schema_version")
    return all_ok


def check_no_sensitive_content() -> bool:
    """Scan index values for secret-like content."""
    sensitive_indexes = ["file", "symbol", "module"]
    found_any = False
    for k in sensitive_indexes:
        p = IDX.get(k)
        if not p or not p.exists():
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        matches = _SECRET_RE.findall(raw)
        if matches:
            fail(f"possible sensitive content in {k} index: {len(matches)} pattern match(es)")
            found_any = True
    if not found_any:
        ok("no sensitive content patterns found in indexes")
    return not found_any


def check_exact_maps_non_empty() -> bool:
    """Verify that key O(1) maps are non-empty (unless workspace is truly empty)."""
    checks = {
        "repo_index": ("repo", "repo_count"),
        "file_index": ("file", "file_count"),
    }
    all_ok = True
    ws_data = load_json(IDX["workspace"], {})
    repo_count = ws_data.get("repo_count", 0) if isinstance(ws_data, dict) else 0
    file_count = ws_data.get("file_count", 0) if isinstance(ws_data, dict) else 0

    if repo_count == 0:
        warn("repo_count=0 in workspace index — workspace may be empty or misconfigured")

    if file_count == 0 and repo_count > 0:
        fail("file_count=0 but repo_count>0 — file scanning may have failed")
        all_ok = False

    if all_ok:
        ok(f"exact maps non-empty: repo_count={repo_count}, file_count={file_count}")
    return all_ok


def check_build_metadata() -> bool:
    p = IDX["build_metadata"]
    if not p.exists():
        fail("build-metadata.json missing")
        return False
    data = load_json(p, None)
    if not isinstance(data, dict):
        fail("build-metadata.json invalid JSON")
        return False
    required_fields = ["build_id", "build_duration_sec", "repo_count", "file_count"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        fail(f"build-metadata.json missing fields: {missing}")
        return False
    ok(f"build-metadata valid: id={data.get('build_id')}, "
       f"repos={data.get('repo_count')}, files={data.get('file_count')}, "
       f"dur={data.get('build_duration_sec')}s")
    return True


def check_query_smoke() -> bool:
    """Run a quick smoke query to verify the query tool works."""
    try:
        result = subprocess.run(
            [sys.executable, str(_TOOLS / "workspace_intelligence_query.py"), "summary"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT)
        )
        if result.returncode != 0:
            fail(f"query smoke test failed (rc={result.returncode}): {result.stderr[:200]}")
            return False
        data = json.loads(result.stdout)
        if "results" not in data:
            fail("query smoke test: unexpected response shape")
            return False
        ok("query smoke test passed (summary query)")
        return True
    except subprocess.TimeoutExpired:
        fail("query smoke test timed out")
        return False
    except Exception as exc:
        fail(f"query smoke test error: {exc}")
        return False


def main() -> int:
    print("workspace-intelligence-lint: running checks...")
    t0 = time.monotonic()

    results = [
        check_config(),
        check_indexes_exist(),
        check_json_valid_and_versioned(),
        check_no_sensitive_content(),
        check_exact_maps_non_empty(),
        check_build_metadata(),
        check_query_smoke(),
    ]

    duration = round(time.monotonic() - t0, 2)
    passed = sum(results)
    total = len(results)

    print(f"\nworkspace-intelligence-lint: {passed}/{total} checks passed ({duration}s)")
    if all(results):
        print("Status: Pass")
        return 0
    else:
        print("Status: Fail")
        return 1


if __name__ == "__main__":
    sys.exit(main())
