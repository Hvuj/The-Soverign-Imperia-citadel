"""Tests for the mtime-cached lazy JSON loader and touched-repo inference."""

import os
import time

import pytest

from citadel.services import _lazy_load as L


def test_reads_disk_once_until_mtime_changes(tmp_path):
    p = tmp_path / "idx.json"
    p.write_text('{"a": 1}')
    L.invalidate()
    before = L._read_count()
    for _ in range(5):
        assert L.lazy_json(p) == {"a": 1}
    assert L._read_count() - before == 1

    os.utime(p, None)
    time.sleep(0.01)
    p.write_text('{"a": 2}')
    assert L.lazy_json(p) == {"a": 2}
    assert L._read_count() - before == 2


def test_missing_and_corrupt_return_default(tmp_path):
    assert L.lazy_json(tmp_path / "nope.json", default={"d": True}) == {"d": True}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert L.lazy_json(bad, default=[]) == []


def test_touched_repos_parses_ledger(tmp_path, monkeypatch):
    from citadel import paths as vp

    ws = tmp_path
    (ws / ".claude" / "state").mkdir(parents=True)
    scan_root = tmp_path / "work"
    ledger = ws / ".claude" / "state" / "tool-batches.ndjson"
    ledger.write_text(
        f'{{"tool_input": {{"file_path": "{scan_root}/acme-repo/a.py"}}}}\n'
        f'{{"cmd": "grep x {scan_root}/widget-repo/b.py"}}\n'
        f'{{"noise": "no path here"}}\n'
    )
    monkeypatch.setattr(vp, "workspace_root", lambda *a, **k: ws)

    from citadel.mine_engine import touched_repos

    touched = touched_repos(ws, scan_root=scan_root)
    assert touched == {"acme-repo", "widget-repo"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
