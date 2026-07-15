"""The Law (masterplan §5.2/§5.3/§5.5): Lex Curiata manifests (G6), Intercessio dual-gate (G7), Tribune
sacrosanct registry — plus the §5.7 chaos-drill assertions (god-manifest reject, lease-overrun ladder)."""

from citadel.services.authority import (
    Gate,
    LeaseReaper,
    SacrosanctRegistry,
    dual_gate,
    is_ratified,
    sign_manifest,
    validate_manifest,
)

_KEY = b"root-signing-key"


def _good_manifest():
    return {
        "imperium": "imperium-mutationis",
        "lease": {"ttl_hours": 24},
        "provinces": ["/repo/**"],
        "image": {"ref": "registry.local/x@sha256:abc"},
    }


def test_g6_valid_manifest_passes_and_ratifies():
    manifest = _good_manifest()
    assert validate_manifest(manifest) == []
    manifest["signature"] = sign_manifest(manifest, key=_KEY)
    assert is_ratified(manifest, key=_KEY) is True


def test_g6_god_manifest_rejected_before_signature():
    manifest = {"lease": {"ttl": None}, "provinces": ["/**"], "image": {"ref": "x:latest"}}
    violations = validate_manifest(manifest)
    assert any("lease" in v for v in violations)
    assert any("wildcard" in v for v in violations)
    assert any("latest" in v for v in violations)
    assert is_ratified(manifest, key=_KEY) is False


def test_g6_tampered_manifest_not_ratified():
    manifest = _good_manifest()
    manifest["signature"] = sign_manifest(manifest, key=_KEY)
    manifest["provinces"] = ["/repo/**", "/etc/**"]
    assert is_ratified(manifest, key=_KEY) is False


def test_g7_axe_needs_two_uncorrelated_gates():
    approved, _ = dual_gate([Gate("claude", True), Gate("gemini", True)])
    assert approved is True
    approved, reason = dual_gate([Gate("claude", True), Gate("claude", True)])
    assert approved is False
    assert "uncorrelated" in reason
    approved, _ = dual_gate([Gate("claude", True), Gate("gemini", False)])
    assert approved is False


def test_tribune_refuses_to_kill_sacrosanct():
    registry = SacrosanctRegistry()
    registry.protect(4242)
    assert registry.may_kill(9999) is True
    assert registry.may_kill(4242) is False
    assert 4242 in registry.violations


def test_chaos_lease_overrun_ladder_reaps_expired():
    reaper = LeaseReaper()
    reaper.grant("runaway", "worker", ttl_seconds=10, now=0.0)
    assert reaper.is_valid("runaway", now=5.0) is True
    dead = reaper.reap(now=100.0)
    assert [d.lease_id for d in dead] == ["runaway"]
    assert reaper.is_valid("runaway", now=100.0) is False
