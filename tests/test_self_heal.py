"""Tests for tools/legion_self_heal.py — init failure-class detection and safe repair."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "legion_self_heal.py"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CITADEL_WORKSPACE": str(ws)}
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(ws), env=env, capture_output=True, text=True, timeout=60,
    )


def _findings(ws: Path, *args: str) -> list[dict]:
    r = _run(ws, "--json", *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["findings"]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    for d in ("context-capsules", "validation-results", "learning-candidates"):
        (tmp_path / ".claude" / "state" / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_clean_workspace_has_no_findings(ws: Path):
    assert _findings(ws, "--check") == []


def test_malformed_json_detected(ws: Path):
    brain = ws / ".claude" / "brain"
    brain.mkdir()
    (brain / "bad.json").write_text("{ not valid json", encoding="utf-8")
    kinds = {f["kind"] for f in _findings(ws, "--check")}
    assert "malformed_json" in kinds


def test_unguarded_git_flagged_but_guarded_is_ok(ws: Path):
    hooks = ws / ".claude" / "hooks"
    hooks.mkdir()
    (hooks / "bad.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\ngit diff\n", encoding="utf-8")
    (hooks / "good.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\ngit diff 2>/dev/null || true\n", encoding="utf-8"
    )
    flagged = {
        f["path"].split("/")[-1]
        for f in _findings(ws, "--check")
        if f["kind"] == "unguarded_git_in_hook"
    }
    assert "bad.sh" in flagged
    assert "good.sh" not in flagged


def test_unguarded_git_repaired_under_fix(ws: Path):
    hooks = ws / ".claude" / "hooks"
    hooks.mkdir()
    bad = hooks / "bad.sh"
    bad.write_text("#!/usr/bin/env bash\nset -euo pipefail\ngit diff --name-only\n", encoding="utf-8")

    fixed = [f for f in _findings(ws, "--fix") if f["kind"] == "unguarded_git_in_hook"]
    assert fixed
    assert "repaired" in fixed[0]["action"]
    assert "|| true" in bad.read_text(encoding="utf-8")
    assert not bad.with_suffix(".sh.bak_heal").exists()

    assert _findings(ws, "--check") == []


def test_malformed_json_repaired_under_fix(ws: Path):
    brain = ws / ".claude" / "brain"
    brain.mkdir()
    bad = brain / "trailing.json"
    bad.write_text('{"a": 1,}\n', encoding="utf-8")
    empty = brain / "empty.json"
    empty.write_text("", encoding="utf-8")

    findings = [f for f in _findings(ws, "--fix") if f["kind"] == "malformed_json"]
    assert len(findings) == 2
    assert all("repaired" in f["action"] for f in findings)
    json.loads(bad.read_text(encoding="utf-8"))
    json.loads(empty.read_text(encoding="utf-8"))
    assert _findings(ws, "--check") == []


def test_malformed_json_unrecoverable_left_reported(ws: Path):
    brain = ws / ".claude" / "brain"
    brain.mkdir()
    bad = brain / "garbage.json"
    bad.write_text("{ not valid json at all", encoding="utf-8")

    findings = [f for f in _findings(ws, "--fix") if f["kind"] == "malformed_json"]
    assert findings
    assert "manual repair" in findings[0]["action"]
    assert bad.read_text(encoding="utf-8") == "{ not valid json at all"


def test_missing_hook_script_stubbed_under_fix(ws: Path):
    (ws / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{"command": "bash .claude/hooks/ghost.sh"}]}]},
    }), encoding="utf-8")

    findings = [f for f in _findings(ws, "--fix") if f["kind"] == "missing_hook_script"]
    assert findings
    assert "stubbed" in findings[0]["action"]
    stub = ws / ".claude" / "hooks" / "ghost.sh"
    assert stub.exists()
    assert os.access(stub, os.X_OK)
    assert _findings(ws, "--check") == []


def test_duplicate_divergent_hook_quarantined_under_fix(ws: Path):
    hooks = ws / ".claude" / "hooks"
    hooks.mkdir()
    (hooks / "dup.sh").write_text("echo canonical\n", encoding="utf-8")
    stale = ws / ".claude" / "dup.sh"
    stale.write_text("echo stale\n", encoding="utf-8")

    dup = [f for f in _findings(ws, "--fix") if f["kind"] == "duplicate_divergent_hook"]
    assert dup
    assert "quarantined" in dup[0]["action"]
    assert not stale.exists()
    assert (ws / ".claude" / "state" / "self-heal" / "quarantine" / "dup.sh").exists()
    assert (hooks / "dup.sh").exists()
