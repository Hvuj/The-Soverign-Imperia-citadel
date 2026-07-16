"""Fasces — signed capability tokens (masterplan §4.7).

A `uint64` mask carries the permissions: low bits are **rods** (reversible mutate-class — WRITE_FILE,
APPLY_PATCH, …) and the high 16 bits are the **axe** (irreversible destroy-class — DELETE_PATH, FORCE_PUSH,
…). An HMAC over the token fields is the red-leather binding: alter any field and the binding breaks, so the
token is tamper-evident. `permitted()` is O(1): remove the axe inside the pomerium, then one bitwise AND.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass

WRITE_FILE = 1 << 0
APPLY_PATCH = 1 << 1
RESTART_SVC = 1 << 2
INDEX_WRITE = 1 << 3
CACHE_EVICT = 1 << 4
FORMAT = 1 << 5

AXE_CLASS = 0xFFFF_0000_0000_0000
DELETE_PATH = 1 << 48
DROP_TABLE = 1 << 49
FORCE_PUSH = 1 << 50
KILL_PID = 1 << 51
LEASE_REVOKE = 1 << 52
CONDEMN = 1 << 53


@dataclass(frozen=True, slots=True)
class FascesToken:
    imperium_id: str
    rank: str
    mask: int
    lease_id: str
    zone_policy: str
    expiry: float
    signature: str


def _canonical(imperium_id: str, rank: str, mask: int, lease_id: str, zone_policy: str, expiry: float) -> bytes:
    return f"{imperium_id}|{rank}|{mask}|{lease_id}|{zone_policy}|{expiry}".encode("utf-8")


def sign_token(
    imperium_id: str, rank: str, mask: int, lease_id: str, zone_policy: str, expiry: float, *, key: bytes
) -> FascesToken:
    signature = hmac.new(
        key, _canonical(imperium_id, rank, mask, lease_id, zone_policy, expiry), hashlib.sha256
    ).hexdigest()
    return FascesToken(imperium_id, rank, mask, lease_id, zone_policy, expiry, signature)


def verify_token(token: FascesToken, *, key: bytes) -> bool:
    expected = hmac.new(
        key,
        _canonical(token.imperium_id, token.rank, token.mask, token.lease_id, token.zone_policy, token.expiry),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, token.signature)


def permitted(
    required: int, token: FascesToken, *, in_domi: bool, key: bytes | None = None, now: float | None = None
) -> bool:
    """O(1) capability check: unexpired, signature valid (when a key is given), and the effective mask — with
    the axe removed inside the pomerium — grants every required bit."""
    current = time.time() if now is None else now
    if token.expiry and current >= token.expiry:
        return False
    if key is not None and not verify_token(token, key=key):
        return False
    effective = token.mask & ~AXE_CLASS if in_domi else token.mask
    return (required & effective) == required


def attenuate(parent_mask: int, requested_mask: int) -> int:
    """Delegation is attenuation-only (§5.6): a child mask can only drop bits, never add them."""
    return parent_mask & requested_mask
