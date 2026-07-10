#!/usr/bin/env python3
"""Build docs/brain/graph.json from brain node markdown files plus runtime state.

Extends the original markdown-only loader with:
  - manifest node  (.claude/state/execution-manifest.json)
  - artifact nodes (.claude/state/artifacts/current/)
  - capsule nodes  (.claude/state/brain-search/capsules/)
  - source-file nodes (files referenced by existing nodes / artifacts / capsules)
  - directory nodes (parent dirs of the above)
  - typed links between all of the above

Config limits: .claude/brain/graph-aware-config.json → "graph_build" section.
"""

import re
from collections import Counter, defaultdict
from pathlib import Path

from _brain_common import (
    CONFIG,
    ROOT,
    SEARCH_STATE,
    STATE,
    load_json,
    parse_frontmatter,
    slug,
    write_json,
)

_DEFAULTS: dict = {
    "max_file_nodes":            200,
    "max_directory_nodes":       100,
    "max_artifact_nodes":         60,
    "max_capsule_nodes":          40,
    "include_runtime_artifacts":  True,
    "include_manifest_node":      True,
    "include_capsule_nodes":      True,
    "include_source_file_nodes":  True,
    "excluded_node_subdirs":     ["commits"],
}

_BTICK = re.compile(r'`([^`\n]{3,120})`')
_FILE_EXT = re.compile(r'\.(py|md|json|yaml|yml|sh|toml|sql|txt|csv|parquet)$', re.IGNORECASE)


def _norm(p: str) -> str:
    """Strip leading ./ while preserving .dotdir/ paths like .claude/."""
    return p[2:] if p.startswith("./") else p


def _load_cfg() -> dict:
    raw = load_json(CONFIG, {})
    cfg = dict(_DEFAULTS)
    cfg.update(raw.get("graph_build", {}))
    return cfg


def _mk(nid: str, title: str, ntype: str, path: str = "") -> dict:
    return {"id": nid, "title": title, "type": ntype,
            "path": path, "tags": [], "files": []}


def _add(nodes: list, seen: set, node: dict) -> bool:
    """Add node if id not yet seen. Returns True when added."""
    if node["id"] in seen:
        return False
    seen.add(node["id"])
    nodes.append(node)
    return True


def _link(links: list, lseen: set, node_seen: set,
          src: str, tgt: str, ltype: str) -> None:
    """Emit a directed link only when both endpoints exist and the pair is new."""
    if src not in node_seen or tgt not in node_seen:
        return
    k = (src, tgt)
    if k not in lseen:
        lseen.add(k)
        links.append({"source": src, "target": tgt, "type": ltype})


def _file_refs(text: str) -> set[str]:
    """Extract backtick-quoted tokens that look like repo file paths."""
    found: set[str] = set()
    for m in _BTICK.finditer(text):
        v = _norm(m.group(1).strip())
        if "/" in v and _FILE_EXT.search(v):
            found.add(v)
    return found


def _md_nodes(nodes: list, seen: set, links: list, lseen: set, cfg: dict) -> dict[str, set]:
    """Load docs/brain/nodes/**/*.md.

    Skips subdirectories listed in cfg["excluded_node_subdirs"] (default: ["commits"]).
    Also accumulates a node_files mapping: node_id → set of referenced paths.
    """
    node_files: dict[str, set] = defaultdict(set)
    base = ROOT / "docs/brain/nodes"
    if not base.exists():
        return node_files
    excluded_subdirs: set = set(cfg.get("excluded_node_subdirs", ["commits"]))
    n2f: dict = load_json(SEARCH_STATE / "node-to-files.json", {})
    for p in sorted(base.rglob("*.md")):
        try:
            rel_parts = p.relative_to(base).parts
            if rel_parts and rel_parts[0] in excluded_subdirs:
                continue
        except ValueError:
            pass
        meta, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
        nid = str(meta.get("id") or p.stem)
        if nid in seen:
            continue
        seen.add(nid)
        nodes.append({
            "id":    nid,
            "title": str(meta.get("title") or nid),
            "type":  str(meta.get("type") or p.parent.name.rstrip("s")),
            "path":  str(p.relative_to(ROOT)),
            "tags":  meta.get("tags") if isinstance(meta.get("tags"), list) else [],
            "files": meta.get("files") if isinstance(meta.get("files"), list) else [],
        })
        for t in (meta.get("links", []) if isinstance(meta.get("links"), list) else []):
            k = (nid, str(t))
            if k not in lseen:
                lseen.add(k)
                links.append({"source": nid, "target": str(t), "type": "related_to"})
        fset: set = set()
        if isinstance(meta.get("files"), list):
            fset.update(_norm(f) for f in meta["files"] if isinstance(f, str))
        if isinstance(n2f.get(nid), list):
            fset.update(_norm(f) for f in n2f[nid] if isinstance(f, str))
        if fset:
            node_files[nid] = fset
    return node_files


def _manifest(nodes: list, seen: set, cfg: dict) -> dict | None:
    """Add a manifest node and return the parsed manifest data (or None)."""
    if not cfg.get("include_manifest_node"):
        return None
    mp = STATE / "execution-manifest.json"
    if not mp.exists():
        return None
    data = load_json(mp, {})
    _add(nodes, seen, _mk(
        "manifest:execution-manifest",
        "Execution Manifest",
        "manifest",
        str(mp.relative_to(ROOT)),
    ))
    return data


def _artifacts(nodes: list, seen: set, cfg: dict,
               mdata: dict | None) -> tuple[dict[str, str], set[str]]:
    """Add artifact nodes. Returns (path_to_nid, art_paths).

    required_artifacts from the manifest are added even if the file is absent.
    """
    if not cfg.get("include_runtime_artifacts"):
        return {}, set()
    cap = int(cfg.get("max_artifact_nodes", 60))
    art_dir = STATE / "artifacts" / "current"
    path_to_nid: dict[str, str] = {}
    art_paths: set[str] = set()

    def _reg(nid: str, path: str, title: str) -> None:
        if len(path_to_nid) >= cap:
            return
        np = _norm(path) if path else ""
        _add(nodes, seen, _mk(nid, title, "artifact", path))
        if np:
            path_to_nid[np] = nid
            art_paths.add(np)

    for art in (mdata or {}).get("required_artifacts", []):
        rp = art.get("path", "")
        aid = art.get("id") or slug(Path(rp).stem if rp else "artifact")
        _reg(f"artifact:{aid}", rp, art.get("filename") or aid)

    if art_dir.exists():
        for p in sorted(art_dir.glob("*.md")):
            rp = str(p.relative_to(ROOT))
            if _norm(rp) in path_to_nid:
                continue
            _reg(f"artifact:{slug(p.stem)}", rp, p.name)

    return path_to_nid, art_paths


def _capsules(nodes: list, seen: set, cfg: dict) -> tuple[list, dict[str, str], set[str]]:
    """Add capsule nodes. Returns (infos, stem_to_nid, capsule_paths).

    infos: list of (nid, node_id_ref, topic, rel_files)
    """
    if not cfg.get("include_capsule_nodes"):
        return [], {}, set()
    cap = int(cfg.get("max_capsule_nodes", 40))
    cap_dir = SEARCH_STATE / "capsules"
    if not cap_dir.exists():
        return [], {}, set()

    infos: list = []
    stem_to_nid: dict[str, str] = {}
    capsule_paths: set[str] = set()

    for p in sorted(cap_dir.glob("*.json")):
        if len(infos) >= cap:
            break
        data = load_json(p, {})
        nid = f"capsule:{p.stem}"
        topic = str(data.get("topic") or p.stem)
        node_id_ref = str(data.get("node_id") or "")
        rel_files = [
            _norm(f) for f in (data.get("related_files") or [])
            if isinstance(f, str) and f
        ]
        cp = str(p.relative_to(ROOT))
        _add(nodes, seen, _mk(nid, f"Capsule: {topic}", "capsule", cp))
        stem_to_nid[p.stem] = nid
        capsule_paths.add(cp)
        infos.append((nid, node_id_ref, topic, rel_files))

    return infos, stem_to_nid, capsule_paths


def _source_files(nodes: list, seen: set, cfg: dict,
                  node_files: dict, art_paths: set, cap_infos: list,
                  cap_paths: set) -> dict[str, str]:
    """Add source-file nodes for paths connected to the graph (never the whole repo).

    Returns path_to_fid mapping.  Excludes paths already represented as
    artifact or capsule nodes to avoid redundant double-representation.
    """
    if not cfg.get("include_source_file_nodes"):
        return {}
    cap = int(cfg.get("max_file_nodes", 200))
    excluded = art_paths | cap_paths

    connected: set[str] = set()
    for paths in node_files.values():
        connected.update(paths)
    for _, _, _, rel_files in cap_infos:
        connected.update(rel_files)
    art_dir = STATE / "artifacts" / "current"
    if art_dir.exists():
        for p in art_dir.glob("*.md"):
            try:
                connected.update(_file_refs(p.read_text(encoding="utf-8", errors="ignore")))
            except Exception:
                pass

    path_to_fid: dict[str, str] = {}
    for raw in sorted(connected):
        if len(path_to_fid) >= cap:
            break
        p = _norm(raw)
        if not p or p in excluded:
            continue
        fid = f"file:{p}"
        _add(nodes, seen, _mk(fid, Path(p).name, "source-file", p))
        path_to_fid[p] = fid

    return path_to_fid


def _directories(nodes: list, seen: set, cfg: dict,
                 path_to_fid: dict, art_path_to_id: dict,
                 cap_paths: set) -> dict[str, str]:
    """Add directory nodes for all parent dirs of source-file/artifact/capsule nodes."""
    cap = int(cfg.get("max_directory_nodes", 100))
    dir_set: set[str] = set()

    for p in path_to_fid:
        d = str(Path(p).parent)
        if d not in ("", "."):
            dir_set.add(d)
    for p in art_path_to_id:
        d = str(Path(p).parent)
        if d not in ("", "."):
            dir_set.add(d)
    for cp in cap_paths:
        d = str(Path(cp).parent)
        if d not in ("", "."):
            dir_set.add(d)

    dir_id_map: dict[str, str] = {}
    for dp in sorted(dir_set):
        if len(dir_id_map) >= cap:
            break
        did = f"dir:{dp}"
        _add(nodes, seen, _mk(did, Path(dp).name or dp, "directory", dp))
        dir_id_map[dp] = did

    return dir_id_map


def _runtime_links(links: list, lseen: set, nodes: list, seen: set,
                   mdata: dict | None, art_path_to_id: dict,
                   cap_infos: list, stem_to_nid: dict,
                   node_files: dict, path_to_fid: dict,
                   dir_id_map: dict) -> None:
    """Emit all new link types for runtime nodes.

    Only emits a link when both source and target exist in seen.
    """

    def L(s: str, t: str, lt: str) -> None:
        _link(links, lseen, seen, s, t, lt)

    wf = (mdata or {}).get("selected_workflow", "")
    if wf:
        L("manifest:execution-manifest", wf, "defines")

    for art in (mdata or {}).get("required_artifacts", []):
        rp = art.get("path", "")
        aid = art.get("id") or slug(Path(rp).stem if rp else "artifact")
        a_nid = f"artifact:{aid}"
        L("manifest:execution-manifest", a_nid, "produces")
        if wf:
            L(wf, a_nid, "produces")

    art_dir = STATE / "artifacts" / "current"
    if art_dir.exists():
        for p in sorted(art_dir.glob("*.md")):
            a_nid = art_path_to_id.get(str(p.relative_to(ROOT)))
            if not a_nid:
                continue
            try:
                refs = _file_refs(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                refs = set()
            for ref in refs:
                f_nid = path_to_fid.get(ref)
                if f_nid:
                    L(a_nid, f_nid, "references")

    for node_id, paths in node_files.items():
        for fp in paths:
            f_nid = path_to_fid.get(fp)
            if f_nid:
                L(node_id, f_nid, "references")

    for fp, f_nid in path_to_fid.items():
        d_nid = dir_id_map.get(str(Path(fp).parent))
        if d_nid:
            L(f_nid, d_nid, "located_in")

    for c_nid, node_id_ref, _, _ in cap_infos:
        if node_id_ref:
            L(c_nid, node_id_ref, "summarizes")

    t2c: dict = load_json(SEARCH_STATE / "topic-to-capsule.json", {})
    for topic_name, cap_path_raw in t2c.items():
        c_nid = stem_to_nid.get(Path(cap_path_raw).stem)
        if c_nid:
            L(f"topic:{topic_name}", c_nid, "maps_to")

    n2c: dict = load_json(SEARCH_STATE / "node-to-capsule.json", {})
    type_map = {n["id"]: n["type"] for n in nodes}
    for node_id, cap_path_raw in n2c.items():
        if type_map.get(node_id) != "agent":
            continue
        c_nid = stem_to_nid.get(Path(cap_path_raw).stem)
        if c_nid:
            L(node_id, c_nid, "maps_to")


def main() -> None:
    cfg = _load_cfg()
    nodes: list = []
    links: list = []
    seen: set = set()
    lseen: set = set()

    node_files                      = _md_nodes(nodes, seen, links, lseen, cfg)
    mdata                           = _manifest(nodes, seen, cfg)
    art_p2id, art_paths             = _artifacts(nodes, seen, cfg, mdata)
    cap_infos, stem_to_nid, cap_pth = _capsules(nodes, seen, cfg)
    path_to_fid                     = _source_files(nodes, seen, cfg, node_files,
                                                    art_paths, cap_infos, cap_pth)
    dir_id_map                      = _directories(nodes, seen, cfg, path_to_fid,
                                                   art_p2id, cap_pth)
    _runtime_links(links, lseen, nodes, seen, mdata,
                   art_p2id, cap_infos, stem_to_nid, node_files, path_to_fid, dir_id_map)

    out = ROOT / "docs/brain/graph.json"
    write_json(out, {"nodes": nodes, "links": links})
    counts = Counter(n.get("type", "unknown") for n in nodes)
    type_summary = "  ".join(f"{t}:{c}" for t, c in sorted(counts.items()))
    print(f"wrote {out} with {len(nodes)} nodes and {len(links)} links")
    print(f"types: {type_summary}")


if __name__ == "__main__":
    main()
