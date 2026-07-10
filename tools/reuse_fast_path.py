#!/usr/bin/env python3

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
PATTERNS = ROOT / "docs" / "ai-context" / "feature-implementation-patterns.md"
CACHE_INDEX = ROOT / "docs" / "ai-context" / "implementation-cache-index.md"
GRAPH = ROOT / "docs" / "brain" / "graph.json"

CARD_RE = re.compile(r"^##\s+(.+?)\n(.*?)(?=^##\s+|\Z)", re.M | re.S)


def tokens(s: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_./-]+", s) if len(t) > 1]


def score_text(query_tokens: list[str], text: str) -> int:
    hay = text.lower()
    return sum(hay.count(t) for t in query_tokens)


def compact_card(title: str, body: str) -> dict:
    def lines_after(prefix: str, max_lines: int = 8) -> list[str]:
        lines = body.splitlines()
        out, active = [], False
        for line in lines:
            if line.startswith(prefix):
                active = True
                suffix = line[len(prefix):].strip()
                if suffix:
                    out.append(suffix)
                continue
            if active:
                if re.match(r"^[A-Z][A-Za-z /]+:", line):
                    break
                if line.strip():
                    out.append(line.strip())
                if len(out) >= max_lines:
                    break
        return out
    return {
        "id": title.split(":", 1)[0].strip(),
        "title": title.strip(),
        "tags": lines_after("Tags:", 1),
        "domain": lines_after("Domain:", 1),
        "files": [x[2:].strip() if x.startswith("- ") else x for x in lines_after("Files:")],
        "tests": [x[2:].strip() if x.startswith("- ") else x for x in lines_after("Tests:")],
        "reuse": lines_after("Reuse next time:"),
        "agents": [x[2:].strip() if x.startswith("- ") else x for x in lines_after("Agents to escalate:")],
        "graph_links": [x[2:].strip() if x.startswith("- ") else x for x in lines_after("Graph links:")],
        "avoid": [x[2:].strip() if x.startswith("- ") else x for x in lines_after("Pitfalls avoided:")],
    }


def graph_matches(query_tokens: list[str], limit: int) -> list[dict]:
    if not GRAPH.exists():
        return []
    data = json.loads(GRAPH.read_text(encoding="utf-8"))
    scored = []
    for n in data.get("nodes", []):
        text = " ".join([
            n.get("id", ""), n.get("title", ""), n.get("type", ""),
            " ".join(n.get("tags", [])), " ".join(n.get("files", [])), n.get("path", "")
        ])
        score = score_text(query_tokens, text)
        if score:
            scored.append((score, n))
    return [n for _, n in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]


def evaluate(query: str, limit: int = 3) -> dict:
    """Score a task query against learned patterns + graph nodes.

    Reusable core of the fast-path (imported by services.reuse.decider — DRY).
    Returns {query, confidence, patterns, graph_nodes, fast_path_available}.
    """
    q_tokens = tokens(query)

    patterns = []
    if PATTERNS.exists():
        text = PATTERNS.read_text(encoding="utf-8")
        for title, body in CARD_RE.findall(text):
            if title.strip().lower() == "template":
                continue
            score = score_text(q_tokens, title + "\n" + body)
            if score:
                card = compact_card(title, body)
                card["score"] = score
                patterns.append(card)

    patterns = sorted(patterns, key=lambda x: x["score"], reverse=True)[:limit]
    nodes = graph_matches(q_tokens, limit)

    confidence = "none"
    if patterns and patterns[0]["score"] >= 5:
        confidence = "high"
    elif patterns:
        confidence = "medium"
    elif nodes:
        confidence = "low"

    return {
        "query": query,
        "confidence": confidence,
        "patterns": patterns,
        "graph_nodes": nodes,
        "fast_path_available": confidence in {"high", "medium"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="+")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    query = " ".join(args.query)
    result = evaluate(query, args.limit)
    patterns = result["patterns"]
    confidence = result["confidence"]
    nodes = result["graph_nodes"]

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("# Reuse Fast Path")
    print(f"query: {query}")
    print(f"confidence: {confidence}")
    print(f"fast_path_available: {str(result['fast_path_available']).lower()}")

    if patterns:
        print("patterns:")
        for p in patterns:
            print(f"- {p['id']} score={p['score']}")
            if p["files"]:
                print("  files:")
                for f in p["files"][:6]:
                    print(f"    - {f}")
            if p["tests"]:
                print("  tests:")
                for t in p["tests"][:6]:
                    print(f"    - {t}")
            if p["agents"]:
                print("  agents:")
                for a in p["agents"][:6]:
                    print(f"    - {a}")
            if p["reuse"]:
                print("  reuse:")
                for r in p["reuse"][:4]:
                    print(f"    - {r}")

    if nodes:
        print("graph_nodes:")
        for n in nodes:
            print(f"- {n.get('id')} ({n.get('type')}) path={n.get('path')}")

    if not patterns and not nodes:
        print("No reuse path found. Use distributed scheduler.")


if __name__ == "__main__":
    main()
