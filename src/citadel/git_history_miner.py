"""git_history_miner.py — Read-only git-history miner.

Reads `git log <branch>` and classifies commits into brain nodes:
  feat  → type: feature
  fix   → type: bug
  chore/ci/docs/build/style → type: chore
  test  → type: test
  refactor/perf → type: refactor

No checkout, no working-tree mutation, no LLM calls.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

NodeType = Literal["feature", "bug", "chore", "test", "refactor", "unknown"]


_CC_MAP: dict[str, NodeType] = {
    "feat":     "feature",
    "fix":      "bug",
    "bugfix":   "bug",
    "hotfix":   "bug",
    "chore":    "chore",
    "ci":       "chore",
    "docs":     "chore",
    "build":    "chore",
    "style":    "chore",
    "test":     "test",
    "tests":    "test",
    "refactor": "refactor",
    "perf":     "refactor",
    "revert":   "chore",
}

_CC_RE = re.compile(r"^(\w+)(?:\([^)]*\))?!?:", re.IGNORECASE)

_TICKET_STRIP = re.compile(r"^[A-Z][A-Z0-9]+-\d+\s+", re.IGNORECASE)

_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


@dataclass
class CommitNode:
    sha: str
    author: str
    date: str
    subject: str
    body: str
    files: list[str]
    node_type: NodeType
    scope: str
    ticket: str
    tags: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)


def _classify(subject: str, files: list[str]) -> tuple[NodeType, str, str]:
    """Return (NodeType, scope, ticket) from commit subject + changed files."""
    cleaned = _TICKET_STRIP.sub("", subject.strip())
    m = _CC_RE.match(cleaned)
    if m:
        prefix = m.group(1).lower()
        node_type = _CC_MAP.get(prefix, "unknown")
        scope_m = re.match(r"^\w+\(([^)]+)\)", cleaned)
        scope = scope_m.group(1) if scope_m else ""
    else:
        node_type = _infer_from_paths(files)
        scope = ""

    if not scope and files:
        first = Path(files[0])
        scope = first.parts[0] if len(first.parts) > 1 else first.stem

    ticket_m = _TICKET_RE.search(scope + " " + subject)
    ticket = ticket_m.group(1) if ticket_m else ""

    return node_type, scope, ticket


def _infer_from_paths(files: list[str]) -> NodeType:
    """Fallback type inference from changed file paths."""
    for f in files:
        low = f.lower()
        if "/test" in low or low.startswith("test") or low.endswith("_test.py"):
            return "test"
        if ".claude/agents/" in low or ".claude/skills/" in low:
            return "chore"
    return "unknown"


def _slug(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len]


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_MAX_FILES_FOR_LINK = 60


def _new_side_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Parse a `git show --unified=0` diff into new-side line ranges per file.

    Returns {new_path: [(start_line, count), ...]}. Deletions (+++ /dev/null) and
    zero-count hunks contribute nothing.
    """
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
        elif line.startswith("@@") and current is not None:
            m = _HUNK_RE.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                if count > 0:
                    ranges.setdefault(current, []).append((start, count))
    return ranges


def link_commit_functions(repo: Path, sha: str, repo_id: str) -> list[str]:
    """Map a commit's changed lines to the functions they live in.

    Parses the *exact revision* of each changed file (`git show <sha>:<path>`) so
    line numbers are accurate for that commit — no drift against the current tree.
    Returns sorted keys ``repo_id/relpath::qualname``. Fail-soft: any git/parse error
    on a file skips just that file.
    """
    from citadel.services.index.symbols import AstSymbolIndex, extract_symbols

    try:
        diff = subprocess.run(
            ["git", "-C", str(repo), "show", sha, "--unified=0", "--no-color", "--format="],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return []

    ranges = _new_side_ranges(diff)
    if not ranges or len(ranges) > _MAX_FILES_FOR_LINK:
        return []

    touched: set[str] = set()
    for path, spans in ranges.items():
        if not path.endswith(".py"):
            continue
        try:
            source = subprocess.run(
                ["git", "-C", str(repo), "show", f"{sha}:{path}"],
                capture_output=True, text=True, check=True,
            ).stdout
        except subprocess.CalledProcessError:
            continue
        index = AstSymbolIndex(extract_symbols(source, repo_id, path))
        for start, count in spans:
            for line in range(start, start + count):
                sym = index.enclosing(repo_id, path, line)
                if sym is not None:
                    touched.add(f"{repo_id}/{path}::{sym.qualname}")
    return sorted(touched)


def mine_history(
    repo_path: str | Path,
    branch: str,
    *,
    last_mined_sha: str | None = None,
    max_commits: int | None = 2000,
    repo_id: str | None = None,
    link_functions: bool = True,
    max_link_commits: int = 800,
) -> list[CommitNode]:
    """Return CommitNode list for `branch` in `repo_path`.

    If `last_mined_sha` is given, only commits AFTER that SHA are returned
    (incremental mode). The git log is read in one subprocess call.

    `max_commits=None` mines the entire branch history with no cap (used for a
    one-time full sweep, e.g. `citadel init`); the default 2000 bounds routine/
    incremental mining.

    When `link_functions` is True, the most recent `max_link_commits` commits also get
    their `functions` field populated (line-level commit->function linkage). Older
    commits keep file-level linkage only — line-level parsing of the whole history is
    bounded to keep a full backfill cheap (YAGNI: recent commits carry the signal).
    """
    repo = Path(repo_path).resolve()
    if not (repo / ".git").exists():
        raise ValueError(f"Not a git repository: {repo}")
    rid = repo_id or repo.name

    rev_range = f"{last_mined_sha}..{branch}" if last_mined_sha else branch

    fmt = "%x1e%H%x1f%an%x1f%aI%x1f%s%x1f%b"
    log_cmd = [
        "git", "-C", str(repo),
        "log", rev_range,
        "--no-merges",
        f"--pretty=format:{fmt}",
        "--name-only",
    ]
    if max_commits is not None:
        log_cmd.append(f"--max-count={max_commits}")
    try:
        result = subprocess.run(
            log_cmd,
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git log failed on {repo} branch={branch}: {exc.stderr.strip()}"
        ) from exc

    raw = result.stdout.strip()
    if not raw:
        return []

    nodes: list[CommitNode] = []
    for record in raw.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\n", 1)
        header = parts[0]
        files_block = parts[1] if len(parts) > 1 else ""

        fields = header.split("\x1f")
        if len(fields) < 4:
            continue
        sha, author, date_iso, subject = fields[0], fields[1], fields[2], fields[3]
        body = fields[4] if len(fields) > 4 else ""
        changed_files = [f for f in files_block.splitlines() if f.strip()]

        node_type, scope, ticket = _classify(subject, changed_files)
        tags = [scope] if scope else []
        if node_type != "unknown":
            tags.append(node_type)
        if ticket:
            tags.append(ticket)

        nodes.append(CommitNode(
            sha=sha,
            author=author,
            date=date_iso,
            subject=subject,
            body=body.strip(),
            files=changed_files,
            node_type=node_type,
            scope=scope,
            ticket=ticket,
            tags=tags,
        ))

    if link_functions:
        for node in nodes[:max_link_commits]:
            node.functions = link_commit_functions(repo, node.sha, rid)

    return nodes


def write_brain_nodes(
    nodes: list[CommitNode],
    nodes_dir: Path,
) -> list[Path]:
    """Write each CommitNode as a brain .md node file.

    Uses the existing brain node frontmatter format so build_brain_search_index
    ingests them unchanged.
    """
    written: list[Path] = []
    type_dirs = {
        "feature":  nodes_dir / "commits" / "features",
        "bug":      nodes_dir / "commits" / "bugs",
        "chore":    nodes_dir / "commits" / "chores",
        "test":     nodes_dir / "commits" / "tests",
        "refactor": nodes_dir / "commits" / "refactors",
        "unknown":  nodes_dir / "commits" / "misc",
    }
    for d in set(type_dirs.values()):
        d.mkdir(parents=True, exist_ok=True)

    for node in nodes:
        node_dir = type_dirs[node.node_type]
        fname = node_dir / f"commit-{node.sha[:8]}.md"
        lines = [
            "---",
            f"id: commit-{node.sha[:8]}",
            f"title: \"{node.subject[:120]}\"",
            f"type: {node.node_type}",
            f"tags: [{', '.join(node.tags)}]",
            "links: []",
            f"files: [{', '.join(repr(f) for f in node.files[:10])}]",
            f"functions: [{', '.join(repr(fn) for fn in node.functions[:30])}]",
            f"commit: {node.sha}",
            f"author: {node.author}",
            f"date: {node.date}",
            f"scope: {node.scope}",
            f"ticket: {node.ticket}",
            "---",
            "",
            f"## {node.subject}",
            "",
        ]
        if node.body:
            lines.extend([node.body, ""])
        if node.files:
            lines.append("**Changed files:**")
            for f in node.files[:20]:
                lines.append(f"- `{f}`")
        fname.write_text("\n".join(lines) + "\n")
        written.append(fname)

    return written


def load_miner_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_miner_state(state_file: Path, branch: str, last_sha: str) -> None:
    """Legacy single-repo state writer (branch-keyed at the top level)."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = load_miner_state(state_file)
    data[branch] = {"last_mined_sha": last_sha, "mined_at": datetime.now(UTC).isoformat()}
    state_file.write_text(json.dumps(data, indent=2) + "\n")


def get_last_sha(state: dict, repo_id: str, branch: str) -> str | None:
    """Read the last-mined SHA for (repo_id, branch) from repo-nested state."""
    return state.get("repos", {}).get(repo_id, {}).get(branch, {}).get("last_mined_sha")


def save_repo_branch_state(state_file: Path, repo_id: str, branch: str, last_sha: str) -> None:
    """Persist last-mined SHA under repos[repo_id][branch] (multi-repo, multi-branch)."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = load_miner_state(state_file)
    repos = data.setdefault("repos", {})
    repos.setdefault(repo_id, {})[branch] = {
        "last_mined_sha": last_sha,
        "mined_at": datetime.now(UTC).isoformat(),
    }
    tmp = state_file.with_suffix(state_file.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(state_file)


def branch_head_sha(repo_path: str | Path, branch: str) -> str | None:
    """Return the tip SHA of `branch`, or None if the branch does not exist."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return None
    sha = result.stdout.strip()
    return sha or None
