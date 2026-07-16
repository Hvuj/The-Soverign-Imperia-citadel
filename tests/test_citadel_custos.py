"""Custodiae context guard (masterplan §6.V): count-first (gate G4), output splicing, secret redaction."""

import sys
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import citadel_custos as cc  # noqa: E402


def test_redact_masks_common_secrets():
    text = (
        "openai sk-ABCDEFGHIJKLMNOP1234567890\n"
        "github ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n"
        "aws AKIAIOSFODNN7EXAMPLE\n"
        "auth Bearer abcdefghijklmnop.qrstuvwx\n"
        "DATABASE_PASSWORD=hunter2secret\n"
        "normal line stays\n"
    )
    out = cc.redact(text)
    assert "sk-ABCDEFGHIJKLMNOP1234567890" not in out
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "hunter2secret" not in out
    assert "DATABASE_PASSWORD=[REDACTED]" in out
    assert "normal line stays" in out


def test_redact_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIBsecretkeymaterial\n-----END RSA PRIVATE KEY-----\n"
    assert "secretkeymaterial" not in cc.redact(text)


def test_counts():
    result = cc.counts("a\nb\nc")
    assert result["lines"] == 3
    assert result["bytes"] == 5


def test_splice_under_and_over_budget():
    body, served, total = cc.splice("hello", max_bytes=100)
    assert body == "hello" and served == 5 and total == 5
    body, served, total = cc.splice("x" * 1000, max_bytes=100)
    assert served == 100 and total == 1000 and len(body) == 100


def test_guard_output_always_has_preamble_small():
    guarded = cc.guard_output("short output")
    assert guarded["preamble"].startswith("[")
    assert guarded["truncated"] is False
    assert guarded["body"] == "short output"


def test_guard_output_truncates_large_and_reports_totals():
    text = "\n".join(f"line {i}" for i in range(1000))
    guarded = cc.guard_output(text, max_lines=50)
    assert guarded["truncated"] is True
    assert guarded["total_lines"] == 1000
    assert guarded["body"].count("\n") <= 50
    assert "showing" in guarded["preamble"]


def test_guard_output_redacts_body():
    guarded = cc.guard_output("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 here")
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in guarded["body"]
    assert "[REDACTED]" in guarded["body"]
