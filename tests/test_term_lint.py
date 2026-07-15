"""Term-lint (masterplan §1): banned brand tokens fail; history/design docs are exempt; repo stays clean."""

import sys
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import term_lint  # noqa: E402


def test_flags_banned_tokens(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text("MODE = 'swarm dispatch'\n", encoding="utf-8")
    (tmp_path / "src" / "brand.py").write_text("NAME = 'VIREN'\n", encoding="utf-8")
    (tmp_path / "src" / "ok.py").write_text("NAME = 'citadel legion'\n", encoding="utf-8")
    files = {f for f, _, _ in term_lint.scan(tmp_path)}
    assert "src/bad.py" in files
    assert "src/brand.py" in files
    assert "src/ok.py" not in files


def test_exempts_history_and_design_docs(tmp_path):
    (tmp_path / "docs" / "history").mkdir(parents=True)
    (tmp_path / "docs" / "history" / "old.md").write_text("VIREN swarm era\n", encoding="utf-8")
    (tmp_path / "docs" / "citadel").mkdir(parents=True)
    (tmp_path / "docs" / "citadel" / "audit.md").write_text("VIREN migration\n", encoding="utf-8")
    assert term_lint.scan(tmp_path) == []


def test_repo_is_clean():
    assert term_lint.scan() == []
