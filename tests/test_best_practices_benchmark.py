"""Tests for tools/best_practices_benchmark.py — deterministic 0-100 composite, weights, artifact."""

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import best_practices_benchmark as bpb  # noqa: E402


def _no_ruff(monkeypatch):
    """Make PEP8 sub-score deterministic + avoid a hard ruff dependency in unit tests."""
    monkeypatch.setattr(bpb, "_ruff_violations", lambda files: {})


def test_score_repo_clean_file_scores_high(tmp_path, monkeypatch):
    _no_ruff(monkeypatch)
    repo = tmp_path / "clean"
    repo.mkdir()
    (repo / "m.py").write_text('"""M."""\n\n\ndef f(a: int) -> int:\n    """Doc."""\n    return a\n', encoding="utf-8")
    report = bpb.score_repo(repo)
    assert 0 <= report["composite"] <= 100
    assert report["composite"] > 80
    assert set(report["per_principle"]) == set(bpb._ANALYZERS) | {bpb._PEP8_KEY}
    assert report["file_count"] == 1
    assert report["loc_total"] > 0


def test_worse_file_scores_lower(tmp_path, monkeypatch):
    _no_ruff(monkeypatch)
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "m.py").write_text('"""M."""\n\n\ndef f(a: int) -> int:\n    """D."""\n    return a\n', encoding="utf-8")
    messy = tmp_path / "messy"
    messy.mkdir()
    body = "".join(f"    if x == {i}:\n        x += 1\n" for i in range(12))
    (messy / "m.py").write_text(f"def BadName(X):\n{body}    return x\n", encoding="utf-8")
    assert bpb.score_repo(clean)["composite"] > bpb.score_repo(messy)["composite"]


def test_pep8_subscore_reflects_ruff_violations(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    f = repo / "m.py"
    f.write_text('"""M."""\n\n\ndef f() -> int:\n    """D."""\n    return 1\n', encoding="utf-8")
    monkeypatch.setattr(bpb, "_ruff_violations", lambda files: {str(f): 9})
    report = bpb.score_repo(repo)
    assert report["files"][0]["ruff_violations"] == 9
    assert report["files"][0]["scores"]["pep8"] == round(1.0 / (1.0 + 9), 4)


def test_weights_applied_to_composite(tmp_path, monkeypatch):
    _no_ruff(monkeypatch)
    monkeypatch.setattr(bpb, "_weights", lambda: {**dict.fromkeys(bpb._ANALYZERS, 1.0), bpb._PEP8_KEY: 1.0})
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "m.py").write_text('"""M."""\n\n\ndef f(a: int) -> int:\n    """D."""\n    return a\n', encoding="utf-8")
    report = bpb.score_repo(repo)
    assert isinstance(report["weights"], dict)
    assert bpb._PEP8_KEY in report["weights"]


def test_run_benchmark_writes_artifact(tmp_path, monkeypatch):
    _no_ruff(monkeypatch)
    monkeypatch.setattr(bpb, "BENCH_DIR", tmp_path / "benchmark")
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / "m.py").write_text('"""M."""\n\n\ndef f() -> int:\n    """D."""\n    return 1\n', encoding="utf-8")

    rc = bpb.run_benchmark([repo], tmp_path, max_workers=2)
    assert rc == 0
    latest = (tmp_path / "benchmark" / "repo1-latest.json")
    assert latest.exists()
    data = json.loads(latest.read_text())
    assert 0 <= data["composite"] <= 100
    assert data["repo"] == "repo1"


def test_dry_run_scores_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(bpb, "BENCH_DIR", tmp_path / "benchmark")
    rc = bpb.run_benchmark([tmp_path], tmp_path, max_workers=1, dry_run=True)
    assert rc == 0
    assert not (tmp_path / "benchmark").exists()
