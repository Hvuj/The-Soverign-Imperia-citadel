#!/usr/bin/env python3
"""grounding_quote_extractor.py — Extract relevant quotes from source documents.

Local-only, no AI calls, no external APIs.

Output matches .claude/schemas/quote-extraction.schema.json.

Usage:
  python tools/grounding_quote_extractor.py --source <file_or_dir> --query "<query>" [--max-quotes N]
  echo "text content" | python tools/grounding_quote_extractor.py --stdin --query "<query>"
"""

import argparse
import json
import re
import sys
from pathlib import Path


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _score(tokens_query: list[str], tokens_chunk: list[str]) -> float:
    if not tokens_query or not tokens_chunk:
        return 0.0
    chunk_set = set(tokens_chunk)
    hits = sum(1 for t in tokens_query if t in chunk_set)
    return hits / len(tokens_query)


def _split_chunks(text: str, source_path: str) -> list[dict]:
    """Split text into chunks by heading/paragraph. Returns list of chunk dicts."""
    chunks = []
    current_heading: str | None = None
    current_lines: list[str] = []
    line_num = 0

    def flush(heading: str | None, lines: list[str], start_line: int) -> None:
        body = "\n".join(lines).strip()
        if body:
            chunks.append({
                "text": body,
                "source_path": source_path,
                "heading": heading,
                "line": start_line,
            })

    heading_re = re.compile(r"^#{1,6}\s+(.+)$")
    lines = text.splitlines()
    para_start = 1

    for i, line in enumerate(lines, start=1):
        m = heading_re.match(line)
        if m:
            flush(current_heading, current_lines, para_start)
            current_heading = m.group(1).strip()
            current_lines = []
            para_start = i + 1
        elif not line.strip() and current_lines:
            flush(current_heading, current_lines, para_start)
            current_lines = []
            para_start = i + 1
        else:
            current_lines.append(line)
            line_num = i

    flush(current_heading, current_lines, para_start)
    return chunks


def extract_quotes(source_text: str, source_path: str, query: str, max_quotes: int = 5) -> dict:
    """Extract relevant quotes from source_text matching query."""
    chunks = _split_chunks(source_text, source_path)
    tokens_query = _tokenize(query)

    scored = []
    for chunk in chunks:
        tokens_chunk = _tokenize(chunk["text"])
        score = _score(tokens_query, tokens_chunk)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_quotes]

    quotes = []
    for score, chunk in top:
        text = chunk["text"]
        if len(text) > 500:
            text = text[:500] + " [...]"
        quotes.append({
            "text": text,
            "source_path": chunk["source_path"],
            "heading": chunk["heading"],
            "line": chunk["line"],
            "relevance_score": round(score, 3),
        })

    return {
        "no_quotes_found": len(quotes) == 0,
        "source_scope": source_path,
        "query": query,
        "quotes": quotes,
    }


def extract_from_file(path: Path, query: str, max_quotes: int) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "no_quotes_found": True,
            "source_scope": str(path),
            "query": query,
            "quotes": [],
            "error": str(exc),
        }
    return extract_quotes(text, str(path), query, max_quotes)


def extract_from_dir(dirpath: Path, query: str, max_quotes: int) -> dict:
    """Aggregate quotes from all .md and .txt files in a directory."""
    all_chunks: list[dict] = []
    tokens_query = _tokenize(query)

    for p in sorted(dirpath.rglob("*")):
        if p.is_file() and p.suffix in {".md", ".txt", ".rst"}:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks = _split_chunks(text, str(p))
            for chunk in chunks:
                tokens_chunk = _tokenize(chunk["text"])
                score = _score(tokens_query, tokens_chunk)
                if score > 0:
                    all_chunks.append((score, chunk))

    all_chunks.sort(key=lambda x: x[0], reverse=True)
    top = all_chunks[:max_quotes]

    quotes = []
    for score, chunk in top:
        text = chunk["text"]
        if len(text) > 500:
            text = text[:500] + " [...]"
        quotes.append({
            "text": text,
            "source_path": chunk["source_path"],
            "heading": chunk["heading"],
            "line": chunk["line"],
            "relevance_score": round(score, 3),
        })

    return {
        "no_quotes_found": len(quotes) == 0,
        "source_scope": str(dirpath),
        "query": query,
        "quotes": quotes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract relevant quotes from source documents.")
    parser.add_argument("--source", default=None, help="File or directory to extract from.")
    parser.add_argument("--stdin", action="store_true", help="Read source text from stdin.")
    parser.add_argument("--query", required=True, help="Query to score relevance against.")
    parser.add_argument("--max-quotes", type=int, default=5, help="Max quotes to return (default 5).")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    if args.stdin or (not args.source and not sys.stdin.isatty()):
        text = sys.stdin.read()
        result = extract_quotes(text, "<stdin>", args.query, args.max_quotes)
    elif args.source:
        p = Path(args.source)
        if p.is_dir():
            result = extract_from_dir(p, args.query, args.max_quotes)
        elif p.is_file():
            result = extract_from_file(p, args.query, args.max_quotes)
        else:
            result = {
                "no_quotes_found": True,
                "source_scope": args.source,
                "query": args.query,
                "quotes": [],
                "error": f"source not found: {args.source}",
            }
    else:
        parser.error("Provide --source <file_or_dir> or pipe text via stdin.")

    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent))


if __name__ == "__main__":
    main()
