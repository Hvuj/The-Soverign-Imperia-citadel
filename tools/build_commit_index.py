#!/usr/bin/env python3
"""Build commit knowledge index from mined commit nodes.

Reads per-commit markdown files from docs/brain/nodes/commits/** and:
  1. Groups by ticket ID (e.g. AIDE-3925, NG-20182) or type+scope fallback
  2. Writes high-level feature rollup .md files into docs/brain/nodes/features/
     (type: feature or bug). Oversized rollups are split into a pointer file +
     chunk files so each file stays small and access is O(1) via the hash index.
  3. Writes .claude/state/brain-search/commit-index.json — the O(1) hash map:
       "sha"     -> path to per-commit .md
       "ticket"  -> rollup path for that ticket
       "file"    -> list of commit SHAs that touched that file
       "feature" -> rollup path by feature ID or safe slug

The graph builder reads docs/brain/nodes/features/ normally (type: feature/bug).
The commit detail files in docs/brain/nodes/commits/ are excluded from the graph
(too many) but are indexed by the brain search index for reuse lookups.

CHUNK_THRESHOLD: rollup body exceeding this char count → pointer + chunk files.
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path.cwd()).resolve()

COMMITS_DIR = ROOT / "docs" / "brain" / "nodes" / "commits"
FEATURES_DIR = ROOT / "docs" / "brain" / "nodes" / "features"
STATE_DIR = ROOT / ".claude" / "state" / "brain-search"
INDEX_PATH = STATE_DIR / "commit-index.json"

CHUNK_THRESHOLD = 8_000
CHUNK_SIZE = 40

_FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_KV_RE = re.compile(r"^(\w[\w-]*):\s*(.*)$", re.MULTILINE)
_TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _parse_fm(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m:
        return {}
    kv: dict = {}
    for km in _KV_RE.finditer(m.group(1)):
        k, v = km.group(1), km.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            kv[k] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()] if inner else []
        else:
            kv[k] = v.strip("\"'")
    return kv


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len]


def _load_commits() -> list[dict]:
    commits: list[dict] = []
    if not COMMITS_DIR.exists():
        return commits
    for p in sorted(COMMITS_DIR.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        fm = _parse_fm(text)
        sha_full = fm.get("commit", "")
        if not sha_full:
            continue
        commits.append({
            "path":      str(p.relative_to(ROOT)),
            "sha8":      sha_full[:8],
            "sha_full":  sha_full,
            "ticket":    fm.get("ticket", ""),
            "scope":     fm.get("scope", ""),
            "title":     fm.get("title", "").strip('"'),
            "type":      fm.get("type", "unknown"),
            "date":      fm.get("date", ""),
            "author":    fm.get("author", ""),
            "files":     fm.get("files", []) if isinstance(fm.get("files"), list) else [],
            "functions": fm.get("functions", []) if isinstance(fm.get("functions"), list) else [],
        })
    return commits


def _group_key(c: dict) -> str:
    """Primary key: ticket ID; fallback: type-scope slug."""
    if c["ticket"]:
        return c["ticket"]
    scope = c["scope"] or "misc"
    return f"{c['type']}-{_slug(scope)}"


def _rollup_type(commits: list[dict]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for c in commits:
        counts[c["type"]] += 1
    top = max(counts, key=lambda k: counts[k], default="unknown")
    return "feature" if top == "feature" else "bug" if top == "bug" else "knowledge"


def _build_rollup_body(group_id: str, commits: list[dict], rtype: str) -> str:
    safe_id = _slug(group_id)
    lines = [
        "---",
        f"id: feature-{safe_id}",
        f'title: "{group_id}"',
        f"type: {rtype}",
        f"tags: [{rtype}, git-history, {group_id}]",
        "links: []",
        "files: []",
        f"commit_count: {len(commits)}",
        "---",
        "",
        f"# {group_id}",
        "",
        f"**{len(commits)} commits** | type: `{rtype}`",
        "",
        "## Commits",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c['sha8']}` **{c['title']}** — {c['date'][:10]} @{c['author']}")
        lines.append(f"  → [{c['path']}]({c['path']})")
    return "\n".join(lines) + "\n"


def _write_rollup(group_id: str, commits: list[dict]) -> list[Path]:
    """Write rollup .md (+ pointer+chunks if oversized). Returns written paths."""
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    rtype = _rollup_type(commits)
    safe_id = _slug(group_id)
    ordered = sorted(commits, key=lambda c: c["date"], reverse=True)
    body = _build_rollup_body(group_id, ordered, rtype)
    written: list[Path] = []

    if len(body) <= CHUNK_THRESHOLD:
        out = FEATURES_DIR / f"feature-{safe_id}.md"
        out.write_text(body, encoding="utf-8")
        written.append(out)
        return written

    chunks = [ordered[i:i + CHUNK_SIZE] for i in range(0, len(ordered), CHUNK_SIZE)]
    chunk_paths: list[str] = []

    for idx, chunk in enumerate(chunks):
        chunk_id = f"{safe_id}-chunk-{idx}"
        c_lines = [
            "---",
            f"id: feature-{chunk_id}",
            f'title: "{group_id} (part {idx + 1}/{len(chunks)})"',
            f"type: {rtype}",
            f"tags: [{rtype}, git-history, {group_id}, chunk]",
            f"links: [feature-{safe_id}]",
            "files: []",
            "---",
            "",
            f"# {group_id} — Part {idx + 1}/{len(chunks)}",
            "",
            "## Commits",
            "",
        ]
        for c in chunk:
            c_lines.append(f"- `{c['sha8']}` **{c['title']}** — {c['date'][:10]} @{c['author']}")
            c_lines.append(f"  → [{c['path']}]({c['path']})")
        chunk_out = FEATURES_DIR / f"feature-{chunk_id}.md"
        chunk_out.write_text("\n".join(c_lines) + "\n", encoding="utf-8")
        written.append(chunk_out)
        chunk_paths.append(str(chunk_out.relative_to(ROOT)))

    ptr_lines = [
        "---",
        f"id: feature-{safe_id}",
        f'title: "{group_id}"',
        f"type: {rtype}",
        f"tags: [{rtype}, git-history, {group_id}, pointer]",
        "links: []",
        "files: []",
        f"commit_count: {len(ordered)}",
        f"chunk_count: {len(chunks)}",
        "---",
        "",
        f"# {group_id} — Feature Pointer",
        "",
        f"**{len(ordered)} commits** across **{len(chunks)} chunks**.",
        "Access any chunk in O(1) via commit-index.json `feature` key.",
        "",
        "## Chunks",
        "",
    ]
    for cp in chunk_paths:
        ptr_lines.append(f"- [{cp}]({cp})")
    ptr_out = FEATURES_DIR / f"feature-{safe_id}.md"
    ptr_out.write_text("\n".join(ptr_lines) + "\n", encoding="utf-8")
    written.insert(0, ptr_out)
    return written


def build(*, verbose: bool = True) -> dict:
    commits = _load_commits()
    if verbose:
        print(f"[build_commit_index] {len(commits)} commit nodes found")

    groups: dict[str, list[dict]] = defaultdict(list)
    for c in commits:
        groups[_group_key(c)].append(c)

    sha_to_path: dict[str, str] = {}
    ticket_to_rollup: dict[str, str] = {}
    file_to_shas: dict[str, list[str]] = defaultdict(list)
    feature_to_rollup: dict[str, str] = {}
    function_to_shas: dict[str, list[str]] = defaultdict(list)
    sha_to_functions: dict[str, list[str]] = {}

    for c in commits:
        sha_to_path[c["sha8"]] = c["path"]
        sha_to_path[c["sha_full"]] = c["path"]
        for f in c["files"]:
            file_to_shas[f].append(c["sha8"])
        if c["functions"]:
            sha_to_functions[c["sha8"]] = c["functions"]
            for fn in c["functions"]:
                function_to_shas[fn].append(c["sha8"])

    if FEATURES_DIR.exists():
        for stale in FEATURES_DIR.glob("feature-*.md"):
            try:
                stale.unlink()
            except Exception:
                pass

    total_files = 0
    for group_id, group_commits in sorted(groups.items()):
        written = _write_rollup(group_id, group_commits)
        if written:
            rollup_path = str(written[0].relative_to(ROOT))
            safe_id = _slug(group_id)
            feature_to_rollup[group_id] = rollup_path
            feature_to_rollup[f"feature-{safe_id}"] = rollup_path
            if _TICKET_RE.match(group_id):
                ticket_to_rollup[group_id] = rollup_path
            total_files += len(written)

    if verbose:
        print(f"[build_commit_index] {total_files} rollup file(s) for {len(groups)} group(s)")

    index = {
        "sha":              sha_to_path,
        "ticket":           ticket_to_rollup,
        "file":             dict(file_to_shas),
        "feature":          feature_to_rollup,
        "function":         dict(function_to_shas),
        "sha_to_functions": sha_to_functions,
    }

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if verbose:
        print(
            f"[build_commit_index] wrote {INDEX_PATH} — "
            f"{len(sha_to_path)//2} SHAs, {len(ticket_to_rollup)} tickets, "
            f"{len(feature_to_rollup)} features, {len(function_to_shas)} functions"
        )
    return index


if __name__ == "__main__":
    verbose = "--quiet" not in sys.argv
    build(verbose=verbose)
