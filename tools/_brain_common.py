import json
import os
import re
from pathlib import Path


def _resolve_workspace_root() -> Path:
    env = os.environ.get("CITADEL_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / ".citadel" / "config.toml").is_file():
            return candidate
    return Path(__file__).resolve().parents[1]


ROOT = _resolve_workspace_root()
STATE = ROOT / ".claude" / "state"
SEARCH_STATE = STATE / "brain-search"
CONFIG = ROOT / ".claude" / "brain" / "graph-aware-config.json"
_BRAIN_DIR = ROOT / ".claude" / "brain"
_ARTIFACT_POLICY_PATH = _BRAIN_DIR / "artifact-policy.json"
_MEMORY_POLICY_PATH = _BRAIN_DIR / "memory-policy.json"
_MANIFEST_CFG_PATH = _BRAIN_DIR / "workflow-manifest-config.json"


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def write_json(path, data):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_artifact_policy() -> dict:
    """Load artifact types and task_type_to_artifacts from artifact-policy.json.

    Falls back to workflow-manifest-config.json for backwards compatibility.
    """
    pol = load_json(_ARTIFACT_POLICY_PATH, None)
    if pol and "artifact_types" in pol:
        return pol
    cfg = load_json(_MANIFEST_CFG_PATH, {})
    return {
        "artifact_types": cfg.get("artifact_types", {}),
        "task_type_to_artifacts": cfg.get("task_type_to_artifacts", {}),
    }


def load_memory_policy() -> dict:
    """Load memory_policy_rules and domain_join_rules from memory-policy.json.

    Falls back to workflow-manifest-config.json for backwards compatibility.
    """
    pol = load_json(_MEMORY_POLICY_PATH, None)
    if pol and "memory_policy_rules" in pol:
        return pol
    cfg = load_json(_MANIFEST_CFG_PATH, {})
    return {
        "memory_policy_rules": cfg.get("memory_policy_rules", {}),
        "domain_join_rules": {
            "sample_feature_join_rule": cfg.get("sample_feature_join_rule", {})
        } if cfg.get("sample_feature_join_rule") else {},
    }


def tokenize(text):
    return [t for t in re.findall(r"[a-zA-Z0-9_][a-zA-Z0-9_\-]{1,}", text.lower()) if len(t) > 1]


def slug(v):
    return re.sub(r"[^a-z0-9]+", "-", v.strip().lower()).strip("-") or "unknown"


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw, body = parts[1], parts[2]
    meta, current = {}, None
    for line in raw.splitlines():
        if line.startswith("  - ") and current:
            meta.setdefault(current, []).append(line[4:].strip()); continue
        if ":" in line:
            k, v = line.split(":", 1); k = k.strip(); v = v.strip(); current = k
            if v.startswith("[") and v.endswith("]"):
                meta[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
            elif v == "":
                meta[k] = []
            else:
                meta[k] = v
    return meta, body
