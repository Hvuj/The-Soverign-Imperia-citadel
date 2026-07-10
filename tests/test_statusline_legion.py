"""Test the statusline's legion_mix() segment (pure-file-read per-worker model tally)."""

import json
from pathlib import Path

import pytest

_STATUSLINE = Path(__file__).resolve().parents[1] / ".citadel" / ".claude" / "statusline.py"
_MULT = "\u00d7"

if not _STATUSLINE.exists():
    # statusline.py is a runtime asset installed into a workspace by `citadel init` (it lives in
    # the packaged .claude template), not part of the dev source tree \u2014 skip when it isn't present.
    pytest.skip("statusline.py template asset not present in this checkout", allow_module_level=True)


def _load_legion_mix():
    """Import statusline.py's legion_mix without executing its render body.

    statusline.py runs its render at import (it's the entrypoint), so load the source,
    strip everything from the first top-level render statement onward, exec the defs only.
    """
    src = _STATUSLINE.read_text(encoding="utf-8")
    marker = "d=stdin_json()"
    head = src.split(marker)[0]
    ns: dict = {}
    exec(compile(head, str(_STATUSLINE), "exec"), ns)
    return ns["legion_mix"]


legion_mix = _load_legion_mix()


def _make_run(tmp_path: Path, run_id: str, events: list[dict]) -> Path:
    state = tmp_path / ".claude" / "state"
    runs = state / "legion-runs"
    (runs / run_id).mkdir(parents=True)
    (runs / "current-run.json").write_text(json.dumps({"run_id": run_id, "task": "t", "started_at": 1.0}))
    with (runs / run_id / "ledger.ndjson").open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return state


def test_no_run_returns_empty(tmp_path):
    (tmp_path / ".claude" / "state").mkdir(parents=True)
    assert legion_mix(tmp_path / ".claude" / "state") == ""


def test_tallies_models_by_tier(tmp_path):
    state = _make_run(tmp_path, "run_x", [
        {"event": "worker-start", "worker": "worker-A", "model": "claude-opus-4-8"},
        {"event": "worker-start", "worker": "worker-B", "model": "claude-haiku-4-5-20251001"},
        {"event": "worker-start", "worker": "worker-C", "model": "claude-haiku-4-5-20251001"},
    ])
    out = legion_mix(state)
    assert "3 workers" in out
    assert f"opus{_MULT}1" in out
    assert f"haiku{_MULT}2" in out


def test_respawn_updates_current_model(tmp_path):
    state = _make_run(tmp_path, "run_y", [
        {"event": "worker-start", "worker": "worker-A", "model": "claude-haiku-4-5-20251001"},
        {"event": "worker-respawn", "worker": "worker-A", "model": "claude-sonnet-4-6"},
    ])
    out = legion_mix(state)
    assert "1 workers" in out
    assert f"sonnet{_MULT}1" in out
    assert "haiku" not in out


def test_half_written_pointer_never_raises(tmp_path):
    state = tmp_path / ".claude" / "state"
    (state / "legion-runs").mkdir(parents=True)
    (state / "legion-runs" / "current-run.json").write_text("{not json")
    assert legion_mix(state) == ""
