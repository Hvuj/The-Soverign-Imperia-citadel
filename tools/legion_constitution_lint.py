#!/usr/bin/env python3
"""
Legion Phase 0 exit gate lint.

Validates:
  1. All 12 LEGION schemas exist and are valid JSON with required fields.
  2. .claude/legion/constitution.json has all 6 required rules.
  3. .claude/legion/board-config.json has directors and precedence_rules.
  4. .claude/legion/model-tiering.json has all three tiers (T0, T1, T2).
  5. tools/_content_address.py is importable and smoke-tests pass.
  6. tools/model_backend.py is importable and hardware probe completes.

Exit code: 0 = Pass, 1 = Needs Fix, 2 = Blocked.
"""


import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])

PASS = 0
NEEDS_FIX = 1
BLOCKED = 2

issues: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    issues.append(f"  FAIL: {msg}")


def warn(msg: str) -> None:
    warnings.append(f"  WARN: {msg}")


def ok(msg: str) -> None:
    print(f"  OK  : {msg}")


REQUIRED_SCHEMAS = [
    "provenance-span.schema.json",
    "atomic-claim.schema.json",
    "principle-scorecard.schema.json",
    "gate-scorecard.schema.json",
    "tier-decision.schema.json",
    "bug-record.schema.json",
    "codemod.schema.json",
    "silver-frontmatter.schema.json",
    "gold-page.schema.json",
    "canary-pair.schema.json",
    "team-report.schema.json",
    "learning-record.schema.json",
]

SCHEMA_REQUIRED_FIELDS = {
    "provenance-span.schema.json":    {"source_hash", "char_start", "char_end"},
    "atomic-claim.schema.json":       {"claim_id", "text", "provenance_span", "confidence"},
    "principle-scorecard.schema.json":{"task_id", "diff_hash", "companies", "conflicts"},
    "gate-scorecard.schema.json":     {"write_id", "l0_passed", "l1_passed", "model_tier_used"},
    "tier-decision.schema.json":      {"decision_id", "task_id", "tier", "deciding_member", "conflict_set"},
    "bug-record.schema.json":         {"bug_id", "fingerprints", "status"},
    "codemod.schema.json":            {"codemod_id", "target_language", "error_classes", "status"},
    "silver-frontmatter.schema.json": {"source_hash", "summary", "claims"},
    "gold-page.schema.json":          {"concept_name", "source_hashes", "status", "related"},
    "canary-pair.schema.json":        {"canary_id", "question", "expected_answer_keys", "corpus"},
    "team-report.schema.json":        {"task_id", "team", "contract_satisfiable"},
    "learning-record.schema.json":    {"decisions_by_tier", "model_tiers_used", "outcome"},
}

print("\n[1] Checking LEGION schemas...")
schemas_dir = ROOT / ".claude" / "schemas"
for schema_name in REQUIRED_SCHEMAS:
    path = schemas_dir / schema_name
    if not path.exists():
        fail(f"Schema missing: {path.relative_to(ROOT)}")
        continue
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Schema invalid JSON ({schema_name}): {e}")
        continue
    props = doc.get("properties", {})
    if not props:
        props = doc.get("definitions", {})
    required_in_schema = set(doc.get("required", []))
    needed = SCHEMA_REQUIRED_FIELDS.get(schema_name, set())
    missing_props = needed - set(props.keys())
    missing_req = needed - required_in_schema
    if missing_props:
        fail(f"{schema_name}: missing properties: {sorted(missing_props)}")
    else:
        ok(f"{schema_name}")


print("\n[2] Checking .claude/legion/constitution.json...")
REQUIRED_RULE_IDS = {
    "no_silent_merge",
    "no_verification_ladder_bypass",
    "no_secret_exfiltration",
    "no_unapproved_destructive_op",
    "audit_tier_decisions",
    "promote_recurring_decisions",
}

const_path = ROOT / ".claude" / "legion" / "constitution.json"
if not const_path.exists():
    fail("constitution.json not found")
else:
    try:
        const = json.loads(const_path.read_text(encoding="utf-8"))
        raw_rules = const.get("rules", {})
        if isinstance(raw_rules, dict):
            rules = set(raw_rules.keys())
        else:
            rules = {r["id"] for r in raw_rules if "id" in r}
        canonical_map = {
            "01_no_silent_merge": "no_silent_merge",
            "02_no_ladder_bypass": "no_verification_ladder_bypass",
            "03_no_secret_exfiltration": "no_secret_exfiltration",
            "04_no_unapproved_destructive_ops": "no_unapproved_destructive_op",
            "05_tier_decision_audit": "audit_tier_decisions",
            "06_recurring_decision_mandate": "promote_recurring_decisions",
        }
        canonical_found = {canonical_map.get(r, r) for r in rules}
        missing_rules = REQUIRED_RULE_IDS - canonical_found
        if missing_rules:
            fail(f"constitution.json missing rules: {sorted(missing_rules)}")
        else:
            ok(f"constitution.json — all {len(rules)} rules present")
    except json.JSONDecodeError as e:
        fail(f"constitution.json invalid JSON: {e}")


print("\n[3] Checking .claude/legion/board-config.json...")
board_path = ROOT / ".claude" / "legion" / "board-config.json"
if not board_path.exists():
    fail("board-config.json not found")
else:
    try:
        board = json.loads(board_path.read_text(encoding="utf-8"))
        raw_dirs = board.get("directors", [])
        if raw_dirs and isinstance(raw_dirs[0], dict):
            directors = [d["id"] for d in raw_dirs if "id" in d]
        else:
            directors = list(raw_dirs)
        required_directors = {"correctness", "velocity", "maintainability"}
        missing_directors = required_directors - set(directors)
        if missing_directors:
            fail(f"board-config.json missing directors: {sorted(missing_directors)}")
        else:
            ok(f"board-config.json — directors: {sorted(directors)}")
        prec = board.get("precedence_rules", [])
        n_rules = len(prec) if isinstance(prec, (list, dict)) else 0
        if n_rules < 3:
            fail(f"board-config.json: too few precedence_rules ({n_rules}, need ≥3)")
        else:
            ok(f"board-config.json — {n_rules} precedence rules")
    except json.JSONDecodeError as e:
        fail(f"board-config.json invalid JSON: {e}")


print("\n[4] Checking .claude/legion/model-tiering.json...")
tiering_path = ROOT / ".claude" / "legion" / "model-tiering.json"
if not tiering_path.exists():
    fail("model-tiering.json not found")
else:
    try:
        tiering = json.loads(tiering_path.read_text(encoding="utf-8"))
        if "task_routing" in tiering:
            routing = tiering["task_routing"]
            for tier in ("T0", "T1", "T2"):
                if tier not in routing:
                    fail(f"model-tiering.json: missing tier '{tier}' in task_routing")
                else:
                    n_tasks = len(routing[tier].get("tasks", []))
                    ok(f"model-tiering.json — {tier}: {n_tasks} tasks mapped")
        elif "tasks" in tiering:
            tasks_map = tiering["tasks"]
            counts = {}
            for task, tier in tasks_map.items():
                counts[tier] = counts.get(tier, 0) + 1
            for tier in ("T0", "T1", "T2"):
                if tier not in counts:
                    fail(f"model-tiering.json: no tasks mapped to tier '{tier}'")
                else:
                    ok(f"model-tiering.json — {tier}: {counts[tier]} tasks mapped")
        else:
            fail("model-tiering.json: must have 'tasks' or 'task_routing' key")
    except json.JSONDecodeError as e:
        fail(f"model-tiering.json invalid JSON: {e}")


print("\n[5] Checking tools/_content_address.py...")
ca_path = ROOT / "tools" / "_content_address.py"
if not ca_path.exists():
    fail("tools/_content_address.py not found")
else:
    result = subprocess.run(
        [sys.executable, str(ca_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        fail(f"_content_address smoke test failed:\n{result.stdout}\n{result.stderr}")
    else:
        ok("_content_address.py smoke test passed")


print("\n[6] Checking tools/model_backend.py...")
mb_path = ROOT / "tools" / "model_backend.py"
if not mb_path.exists():
    fail("tools/model_backend.py not found")
else:
    result = subprocess.run(
        [sys.executable, str(mb_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        fail(f"model_backend hardware probe crashed:\n{result.stdout}\n{result.stderr}")
    else:
        ok("model_backend.py hardware probe completed without crash")
        for line in result.stdout.splitlines():
            if "Device" in line or "GPU" in line or "tier" in line:
                print(f"         {line.strip()}")


print()
if issues:
    for i in issues:
        print(i)
    if warnings:
        for w in warnings:
            print(w)
    print(f"\nStatus: Needs Fix ({len(issues)} issue(s))")
    sys.exit(NEEDS_FIX)
else:
    if warnings:
        for w in warnings:
            print(w)
    print("Status: Pass — Phase 0 exit gate cleared")
    sys.exit(PASS)
