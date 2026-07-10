"""Tests for tools/legion_orchestrator.py's pure planning/spawn-command logic.

Deliberately avoids exercising `run()`/`_supervise()` (real subprocess spawn of the
`claude` binary, real governance writes) — those are integration-level and covered
by mocked-Popen behavior implicitly through `decide()`/`legion_governance` unit
tests. This file locks down the part the user explicitly asked to see: that
concurrent workers really do get DIFFERENT models/efforts, not one blanket model.
"""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from legion_orchestrator import (  # noqa: E402
    ZERO_TOKEN_FIRST_MANDATE,
    _build_worker_argv,
    _effective_worker_count,
    _select_companies,
    _worker_prompt,
    plan_run,
)

from citadel.services.corporate import Company  # noqa: E402


def _company(repo_id: str) -> Company:
    return Company(repo_id=repo_id, path=Path(f"/tmp/{repo_id}"), is_git=True, python_root=".")


def test_effective_worker_count_respects_all_caps():
    assert _effective_worker_count(max_workers=10, num_companies=2) == 2
    assert _effective_worker_count(max_workers=1, num_companies=10) == 1
    assert _effective_worker_count(max_workers=0, num_companies=10) == 1


def test_select_companies_filters_by_substring():
    companies = [_company("alpha-repo"), _company("beta-repo")]
    assert [c.repo_id for c in _select_companies(companies, "alpha")] == ["alpha-repo"]


def test_select_companies_no_match_falls_back_to_all():
    companies = [_company("alpha-repo"), _company("beta-repo")]
    assert _select_companies(companies, "nonexistent") == companies


def test_select_companies_no_filter_returns_all():
    companies = [_company("alpha-repo"), _company("beta-repo")]
    assert _select_companies(companies, None) == companies


def test_plan_run_gives_lead_worker_a_distinct_tier_from_support_workers():
    companies = [_company("primary"), _company("secondary"), _company("tertiary")]
    specs = plan_run("refactor entire billing pipeline", companies, num_workers=3)

    assert len(specs) == 3
    lead, *support = specs
    assert lead.worker_id == "worker-A"
    assert lead.tier == "strong-planning"
    for spec in support:
        assert spec.tier == "cheap"
        assert spec.model != lead.model or spec.effort != lead.effort


def test_plan_run_low_complexity_task_uses_cheap_lead_tier():
    companies = [_company("only-repo")]
    specs = plan_run("fix a typo in the readme", companies, num_workers=1)
    assert specs[0].tier == "cheap"


def test_plan_run_raises_without_companies():
    import pytest
    with pytest.raises(ValueError, match="no companies"):
        plan_run("anything", [], num_workers=1)


def test_worker_prompt_embeds_zero_token_first_mandate():
    prompt = _worker_prompt("do the thing", _company("repo"), "lead")
    assert ZERO_TOKEN_FIRST_MANDATE in prompt
    assert "never edit files yourself" in prompt


def test_build_worker_argv_uses_print_mode_not_interactive():
    argv = _build_worker_argv("claude", "claude-haiku-4-5-20251001", "acceptEdits")
    assert argv[0] == "claude"
    assert "--print" in argv
    assert "--model" in argv
    assert "claude-haiku-4-5-20251001" in argv
    assert "--ide" not in argv
