#!/usr/bin/env python3
"""Build precomputed per-node/topic context capsules and capsule index files."""
import argparse

from _brain_common import CONFIG, ROOT, SEARCH_STATE, load_json, write_json

CAPSULE_DIR = SEARCH_STATE / "capsules"
MANIFEST_CFG = ROOT / ".claude" / "brain" / "workflow-manifest-config.json"


def _capsule(node_id, node, cfg):
    ntype = node.get("type", "")
    topic = node.get("topic") or (node_id.replace("topic:", "") if node_id.startswith("topic:") else "")
    agents = cfg.get("domain_to_agents", {}).get(topic, []) if topic else []
    skills = cfg.get("domain_to_skills", {}).get(topic, []) if topic else []
    aliases = cfg.get("topic_aliases", {}).get(topic, []) if topic else []
    max_chars = int(cfg.get("max_capsule_chars", 2000))
    files = list(node.get("files") or [])
    if node.get("path"):
        files.append(node["path"])

    default_workflow = ""
    default_skills: list = []
    default_artifacts: list = []
    default_validations: list = []
    default_skip_rules: list = []
    default_memory_policy = ""
    try:
        wf_cfg = load_json(MANIFEST_CFG, {})
        if topic and wf_cfg:
            _domain_to_task = {
                "orchestration": "orchestration", "parcompute": "parcompute", "sql": "sql",
                "bi-logic": "bi_logic", "testing": "test_creation",
                "graph-brain": "graph_brain_tooling", "feature-engineering": "feature_change",
                "docs-ingestion": "docs_ingestion",
            }
            tt = _domain_to_task.get(topic, "")
            if tt:
                wf_id = wf_cfg.get("task_type_to_workflow", {}).get(tt, "")
                wf = wf_cfg.get("workflows", {}).get(wf_id, {})
                default_workflow = wf_id
                default_skills = wf.get("required_skills", [])[:4]
                default_artifacts = wf.get("required_artifacts", [])[:6]
                default_validations = wf.get("required_validations", [])[:4]
                default_skip_rules = wf.get("skip_rules", [])[:4]
                default_memory_policy = wf.get("memory_policy", "")
    except Exception:
        pass

    cap = {
        "node_id": node_id,
        "topic": topic or ntype,
        "domain": topic or ntype,
        "purpose": node.get("summary", "")[:max_chars // 4],
        "when_to_use": aliases[:6],
        "when_to_skip": [],
        "related_files": files,
        "recommended_agents": agents[:6],
        "recommended_skills": skills[:4],
        "validation_hints": [],
        "memory_refs": [],
        "known_pitfalls": [],
        "token_budget": int(cfg.get("token_budget", {}).get("prompt_capsule_chars", 8000)),
    }
    if default_workflow:
        cap["default_workflow"] = default_workflow
    if default_skills:
        cap["default_skills"] = default_skills
    if default_artifacts:
        cap["default_artifacts"] = default_artifacts
    if default_validations:
        cap["default_validations"] = default_validations[:2]
    if default_skip_rules:
        cap["skip_rules"] = default_skip_rules
    if default_memory_policy:
        cap["memory_policy"] = default_memory_policy
    return cap


def build(dirty_nodes=None, quiet=False):
    cfg = load_json(CONFIG, {})
    idx = load_json(SEARCH_STATE / "index.json", {"nodes": {}})
    nodes = idx.get("nodes", {})
    CAPSULE_DIR.mkdir(parents=True, exist_ok=True)

    node_to_capsule = load_json(SEARCH_STATE / "node-to-capsule.json", {})
    topic_to_capsule = load_json(SEARCH_STATE / "topic-to-capsule.json", {})

    built = 0
    for node_id, node in nodes.items():
        if dirty_nodes is not None and node_id not in dirty_nodes:
            continue
        ntype = node.get("type", "")
        if ntype not in ("topic", "knowledge"):
            continue
        cap = _capsule(node_id, node, cfg)
        safe_id = node_id.replace(":", "__").replace("/", "_")
        cap_path = CAPSULE_DIR / f"{safe_id}.json"
        write_json(cap_path, cap)
        rel = str(cap_path.relative_to(ROOT))
        node_to_capsule[node_id] = rel
        if ntype == "topic":
            topic = node.get("topic") or node_id.replace("topic:", "")
            topic_to_capsule[topic] = rel
        built += 1

    write_json(SEARCH_STATE / "node-to-capsule.json", node_to_capsule)
    write_json(SEARCH_STATE / "topic-to-capsule.json", topic_to_capsule)
    if not quiet:
        print(f"capsule cache built: {built} capsules")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--node", default=None, help="rebuild only this node id")
    args = ap.parse_args()
    dirty = {args.node} if args.node else None
    build(dirty_nodes=dirty, quiet=args.quiet)


if __name__ == "__main__":
    main()
