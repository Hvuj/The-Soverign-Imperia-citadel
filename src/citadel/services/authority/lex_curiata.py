"""Lex Curiata — signed activation manifests (masterplan §5.2).

A manifest on disk holds zero authority until ratified. Ratification requires (a) schema validation — a
lease TTL (D1: no power without a lease), a bounded province clause, and no floating `:latest` image
(D6) — and (b) a valid HMAC signature. The signature *is* the activation.
"""

import hashlib
import hmac
import json

_WILDCARD_PROVINCES = {"/**", "/", "**", "/*"}


def validate_manifest(manifest: dict) -> list[str]:
    """Return schema violations (empty list = valid). Enforces D1 (lease) and D6 (no :latest)."""
    violations: list[str] = []
    lease = manifest.get("lease") or {}
    if not (lease.get("ttl_hours") or lease.get("ttl")):
        violations.append("missing lease.ttl (D1: no power without a lease)")
    provinces = manifest.get("provinces")
    if not provinces or not isinstance(provinces, list):
        violations.append("missing provinces (no province clause)")
    elif any(p in _WILDCARD_PROVINCES for p in provinces):
        violations.append("wildcard province (extraordinary command / god-mode scope)")
    image = (manifest.get("image") or {}).get("ref", "")
    if image.endswith(":latest"):
        violations.append("floating image tag :latest (D6: pin by digest)")
    return violations


def _canonical(manifest: dict) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict, *, key: bytes) -> str:
    """Return the activation signature for a manifest (the signature is the activation)."""
    return "hmac-sha256:" + hmac.new(key, _canonical(manifest), hashlib.sha256).hexdigest()


def is_ratified(manifest: dict, *, key: bytes) -> bool:
    """True iff the manifest passes schema validation AND its signature matches."""
    if validate_manifest(manifest):
        return False
    return hmac.compare_digest(manifest.get("signature", ""), sign_manifest(manifest, key=key))
