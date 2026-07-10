#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
DIR_ROOT = ROOT / "docs" / "brain" / "directories"
NODE_ROOT = ROOT / "docs" / "brain" / "nodes" / "directories"
INDEX_JSON = DIR_ROOT / "index.json"
INDEX_MD = DIR_ROOT / "index.md"
GRAPH_INDEX = ROOT / "docs" / "brain" / "graph-index.md"

IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".parcompute", ".orchestration", "node_modules", "dist", "build",
    ".idea", ".vscode", ".claude", ".cursor"
}
IGNORE_SUFFIXES = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".parquet", ".pickle", ".pkl",
    ".log", ".tmp", ".zip", ".gz", ".tar", ".png", ".jpg", ".jpeg", ".webp"
}


def slug_for(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(ROOT.resolve())
        raw = str(rel)
    except Exception:
        raw = str(path.resolve())
    raw = raw.strip("/").replace(os.sep, "__")
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)
    return raw[:120] or "repo-root"


def classify_file(path: Path) -> list[str]:
    name = path.name.lower()
    suffix = path.suffix.lower()
    tags = []
    if suffix == ".py":
        tags.append("python")
    if suffix in {".yaml", ".yml", ".json", ".toml"}:
        tags.append("config")
    if "test" in name or "tests" in path.parts:
        tags.append("test")
    if suffix == ".sql":
        tags.append("sql")
    if suffix == ".md":
        tags.append("docs")
    if "asset" in name:
        tags.append("asset")
    if "schema" in str(path).lower():
        tags.append("schema")
    if "orchestration" in str(path).lower():
        tags.append("orchestration")
    return tags or ["file"]


def should_ignore(path: Path) -> bool:
    if any(part in IGNORE_DIRS for part in path.parts):
        return True
    if path.suffix.lower() in IGNORE_SUFFIXES:
        return True
    return False


def scan_directory(base: Path, max_depth: int, max_files: int) -> list[dict]:
    base = base.resolve()
    results = []
    for p in sorted(base.rglob("*")):
        if len(results) >= max_files:
            break
        if should_ignore(p):
            continue
        try:
            rel_to_base = p.relative_to(base)
        except Exception:
            continue
        depth = len(rel_to_base.parts) - (0 if p.is_file() else 1)
        if depth > max_depth:
            continue
        if p.is_file():
            try:
                rel_repo = p.relative_to(ROOT)
            except Exception:
                rel_repo = p
            results.append({
                "path": str(rel_repo),
                "name": p.name,
                "suffix": p.suffix,
                "size": p.stat().st_size,
                "tags": classify_file(p),
            })
    return results


def infer_purpose(path: Path, files: list[dict]) -> str:
    p = str(path).lower()
    if "tests" in p or any("test" in f["tags"] for f in files):
        return "Tests and validation."
    if "assets" in p:
        return "Orchestration assets / pipeline definitions."
    if "features" in p:
        return "Feature transformation logic."
    if "schemas" in p:
        return "Schema and configuration models."
    if "rules" in p or "configuration" in p:
        return "Configuration and business rules."
    if "docs/brain" in p:
        return "Brain graph and routing metadata."
    if "docs/ai-context" in p:
        return "Claude durable memory."
    if ".claude/agents" in p:
        return "Claude agent definitions."
    if ".claude/rules" in p:
        return "Claude workflow and coding rules."
    return "Repository directory. Purpose inferred from files."


def load_index() -> dict:
    if INDEX_JSON.exists():
        try:
            return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"directories": []}


def save_index(index: dict) -> None:
    DIR_ROOT.mkdir(parents=True, exist_ok=True)
    index["directories"] = sorted(index.get("directories", []), key=lambda x: x.get("id", ""))
    INDEX_JSON.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Directory Brain Index",
        "",
        "Compact index of directories Claude has mapped.",
        "",
        "Query with:",
        "",
        '```bash',
        'python tools/dir_brain_query.py "<task keywords>" --limit 3',
        '```',
        "",
        "## Mapped directories",
        "",
    ]
    if not index["directories"]:
        lines.append("No directories mapped yet.")
    for d in index["directories"]:
        lines.append(f"- `{d['id']}` → `{d['path']}` — {d.get('purpose','')}")
    INDEX_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def checksum(files: list[dict]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f"{f['path']}|{f.get('size',0)}|{','.join(f.get('tags',[]))}\n".encode())
    return h.hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-files", type=int, default=120)
    parser.add_argument("--auto-hook", action="store_true")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.is_absolute():
        target = (ROOT / target).resolve()
    if target.is_file():
        target = target.parent
    if not target.exists() or not target.is_dir():
        print(f"Directory not found: {target}")
        raise SystemExit(1)

    dir_id = slug_for(target)
    files = scan_directory(target, args.max_depth, args.max_files)
    purpose = infer_purpose(target, files)
    sum_hash = checksum(files)
    now = datetime.now(UTC).isoformat()

    dir_dir = DIR_ROOT / dir_id
    dir_dir.mkdir(parents=True, exist_ok=True)
    files_json = dir_dir / "files.json"
    brain_md = dir_dir / "directory-brain.md"
    access_md = dir_dir / "access-log.md"

    read_first = [f for f in files if f["name"] in {"__init__.py", "README.md", "pyproject.toml", "definitions.py"} or "asset" in f["tags"] or "schema" in f["tags"]][:12]
    tests = [f for f in files if "test" in f["tags"]][:12]

    files_json.write_text(json.dumps({
        "id": dir_id,
        "path": str(target),
        "mapped_at": now,
        "max_depth": args.max_depth,
        "max_files": args.max_files,
        "checksum": sum_hash,
        "files": files,
    }, indent=2, sort_keys=True), encoding="utf-8")

    brain_lines = [
        f"# Directory Brain: {dir_id}",
        "",
        f"Path: `{target}`",
        f"Purpose: {purpose}",
        f"Mapped at: {now}",
        f"Checksum: `{sum_hash}`",
        "",
        "## Read first",
        "",
    ]
    if read_first:
        for f in read_first:
            brain_lines.append(f"- `{f['path']}` — {', '.join(f['tags'])}")
    else:
        brain_lines.append("- No obvious read-first files found.")

    brain_lines += ["", "## Tests / validation candidates", ""]
    if tests:
        for f in tests:
            brain_lines.append(f"- `{f['path']}`")
    else:
        brain_lines.append("- No test files detected in bounded scan.")

    brain_lines += ["", "## File summary", ""]
    by_tag = {}
    for f in files:
        for tag in f["tags"]:
            by_tag[tag] = by_tag.get(tag, 0) + 1
    for tag, count in sorted(by_tag.items()):
        brain_lines.append(f"- {tag}: {count}")

    brain_lines += ["", "## Known next-time shortcut", ""]
    brain_lines.append("1. Query this directory brain before broad-scanning this path.")
    brain_lines.append("2. Read only the listed read-first files initially.")
    brain_lines.append("3. Run listed tests first when relevant.")
    brain_lines.append("4. Escalate to graph/dependency mapping only if the bounded map is insufficient.")

    brain_lines += ["", "## Files scanned", ""]
    for f in files[:80]:
        brain_lines.append(f"- `{f['path']}` — {', '.join(f['tags'])}")

    if len(files) >= args.max_files:
        brain_lines += ["", "## Truncation", "", f"Scan reached max-files={args.max_files}. Use deep mapping if needed."]

    brain_md.write_text("\n".join(brain_lines) + "\n", encoding="utf-8")

    if not access_md.exists():
        access_md.write_text(f"# Access Log: {dir_id}\n\n", encoding="utf-8")
    with access_md.open("a", encoding="utf-8") as fh:
        fh.write(f"- {now}: mapped path `{target}` checksum `{sum_hash}`\n")

    NODE_ROOT.mkdir(parents=True, exist_ok=True)
    node_path = NODE_ROOT / f"{dir_id}.md"
    rel_brain = brain_md.relative_to(ROOT)
    rel_files = files_json.relative_to(ROOT)
    node_text = f"""---
id: dir-{dir_id}
title: Directory Brain: {dir_id}
type: directory-brain
tags: [directory, dynamic-map]
links: [dynamic-directory-brain, directory-brain-index]
files:
  - {rel_brain}
  - {rel_files}
---

# Directory Brain: {dir_id}

Path: `{target}`

Purpose: {purpose}

Use `{rel_brain}` before broad-scanning this directory.
"""
    node_path.write_text(node_text, encoding="utf-8")

    index = load_index()
    dirs = [d for d in index.get("directories", []) if d.get("id") != dir_id]
    dirs.append({
        "id": dir_id,
        "path": str(target),
        "purpose": purpose,
        "mapped_at": now,
        "checksum": sum_hash,
        "brain": str(rel_brain),
        "files": str(rel_files),
        "node": str(node_path.relative_to(ROOT)),
    })
    index["directories"] = dirs
    save_index(index)

    if GRAPH_INDEX.exists():
        gi = GRAPH_INDEX.read_text(encoding="utf-8")
        marker = "## directory brain"
        if marker not in gi:
            gi = gi.rstrip() + "\n\n## directory brain\n\n- directory-brain-index → mapped directories\n"
        line = f"- dir-{dir_id} → `{target}`"
        if line not in gi:
            gi = gi.rstrip() + "\n" + line + "\n"
        GRAPH_INDEX.write_text(gi, encoding="utf-8")

    print(f"Mapped directory: {target}")
    print(f"id: {dir_id}")
    print(f"files: {len(files)}")
    print(f"brain: {rel_brain}")


if __name__ == "__main__":
    main()
