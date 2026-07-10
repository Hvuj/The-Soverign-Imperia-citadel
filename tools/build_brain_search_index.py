#!/usr/bin/env python3
import argparse
from collections import defaultdict

from _brain_common import CONFIG, ROOT, SEARCH_STATE, load_json, parse_frontmatter, slug, tokenize, write_json
from build_capsule_cache import build as build_capsules


def md_node(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    meta, body = parse_frontmatter(text)
    rel = str(path.relative_to(ROOT))
    nid = str(meta.get("id") or slug(path.stem))
    title = str(meta.get("title") or nid)
    typ = str(meta.get("type") or path.parent.name.rstrip("s") or "node")
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    links = meta.get("links") if isinstance(meta.get("links"), list) else []
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    kws = sorted(set(tokenize(" ".join([nid, title, typ, rel, " ".join(tags), body[:3000]]))))
    return {"id": nid, "title": title, "type": typ, "path": rel, "tags": tags, "links": links, "files": files, "keywords": kws, "summary": " ".join(body.strip().split())[:700]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quiet", action="store_true"); args = ap.parse_args()
    cfg = load_json(CONFIG, {})
    nodes = []
    base = ROOT / "docs/brain/nodes"
    if base.exists():
        for p in sorted(base.rglob("*.md")):
            nodes.append(md_node(p))
    for topic, aliases in cfg.get("topic_aliases", {}).items():
        nodes.append({"id": f"topic:{topic}", "title": topic.replace("-", " ").title(), "type": "topic", "path": "", "tags": ["topic", topic], "links": [], "files": [], "keywords": sorted(set(tokenize(" ".join([topic, *aliases])))), "summary": f"Concept topic node for {topic}.", "topic": topic})
    for p in sorted((ROOT / ".claude/agents").glob("*.md")) if (ROOT / ".claude/agents").exists() else []:
        text = p.read_text(encoding="utf-8", errors="ignore"); meta, body = parse_frontmatter(text); name = str(meta.get("name") or p.stem); rel = str(p.relative_to(ROOT))
        nodes.append({"id": name, "title": name, "type": "agent", "path": rel, "tags": ["agent"], "links": [], "files": [rel], "keywords": tokenize(name + " " + body[:2000]), "summary": str(meta.get("description") or "Agent.")})
    for p in sorted((ROOT / ".claude/skills").glob("*/SKILL.md")) if (ROOT / ".claude/skills").exists() else []:
        name = p.parent.name; rel = str(p.relative_to(ROOT)); text = p.read_text(encoding="utf-8", errors="ignore")
        nodes.append({"id": f"skill:{name}", "title": name, "type": "skill", "path": rel, "tags": ["skill"], "links": [], "files": [rel], "keywords": tokenize(name + " " + text[:2000]), "summary": " ".join(text.split())[:700]})
    dedup = {}
    for n in nodes:
        dedup.setdefault(n["id"], n)
    nodes = list(dedup.values())
    node_ids = {n["id"] for n in nodes}
    edges = []
    for n in nodes:
        for link in n.get("links", []):
            if link:
                edges.append({"source": n["id"], "target": str(link), "type": "related_to", "weight": 1})
    for domain, agents in cfg.get("domain_to_agents", {}).items():
        topic = f"topic:{domain}"
        if topic in node_ids:
            for a in agents:
                if a in node_ids: edges.append({"source": topic, "target": a, "type": "uses_agent", "weight": 3})
    for domain, skills in cfg.get("domain_to_skills", {}).items():
        topic = f"topic:{domain}"
        if topic in node_ids:
            for s in skills:
                sid = f"skill:{s}"
                if sid in node_ids: edges.append({"source": topic, "target": sid, "type": "uses_skill", "weight": 2})
    kw, alias, path_idx, neigh, n_agents, n_skills, rank = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), {}
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        for k in n.get("keywords", []): kw[k].append(n["id"])
        for t in n.get("tags", []): alias[str(t).lower()].append(n["id"])
        if n.get("path"): path_idx[n["path"]].append(n["id"])
        for f in n.get("files", []): path_idx[f].append(n["id"])
    for e in edges:
        s, t = e["source"], e["target"]; neigh[s].append({"id": t, "type": e.get("type"), "weight": e.get("weight", 1)}); neigh[t].append({"id": s, "type": "reverse_" + e.get("type", "related_to"), "weight": e.get("weight", 1)})
        if t in by_id and by_id[t]["type"] == "agent": n_agents[s].append(t)
        if str(t).startswith("skill:"): n_skills[s].append(t)
    for n in nodes: rank[n["id"]] = {"degree": len(neigh.get(n["id"], [])), "base_rank": len(neigh.get(n["id"], [])) + len(n.get("keywords", []))/100}
    SEARCH_STATE.mkdir(parents=True, exist_ok=True)
    write_json(SEARCH_STATE / "index.json", {"nodes": by_id, "edges": edges})
    for name, data in {"keyword-to-nodes.json": kw, "alias-to-nodes.json": alias, "path-to-nodes.json": path_idx, "node-to-neighbors.json": neigh, "node-to-agents.json": n_agents, "node-to-skills.json": n_skills, "node-rank.json": rank}.items():
        write_json(SEARCH_STATE / name, dict(data))
    build_capsules(quiet=True)
    if not args.quiet:
        print(f"brain search index built: {len(nodes)} nodes, {len(edges)} edges")


if __name__ == "__main__": main()
