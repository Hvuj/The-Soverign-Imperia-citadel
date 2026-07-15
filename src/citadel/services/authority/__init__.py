"""citadel.services.authority — the control-plane primitives (masterplan §4-§5).

fasces: signed capability tokens (rods = reversible, axe = irreversible). pomerium: filesystem zone policy
that removes the axe inside protected paths. lease: TTL leases with a min-heap reaper — no grant is forever.
"""

from citadel.services.authority.fasces import (
    AXE_CLASS,
    FascesToken,
    attenuate,
    permitted,
    sign_token,
    verify_token,
)
from citadel.services.authority.auxilia import GeminiFunditor
from citadel.services.authority.empire import (
    IMPERIUM_MAIUS,
    Dictator,
    Imperium,
    appoint_dictator,
    imperium_maius,
)
from citadel.services.authority.intercessio import Gate, dual_gate
from citadel.services.authority.lease import Lease, LeaseReaper
from citadel.services.authority.lex_curiata import is_ratified, sign_manifest, validate_manifest
from citadel.services.authority.pomerium import DOMI, MILITIAE, Pomerium
from citadel.services.authority.tribune import SacrosanctRegistry
from citadel.services.authority.trust import TrustLedger

__all__ = [
    "AXE_CLASS",
    "DOMI",
    "IMPERIUM_MAIUS",
    "Dictator",
    "FascesToken",
    "Gate",
    "GeminiFunditor",
    "Imperium",
    "Lease",
    "LeaseReaper",
    "MILITIAE",
    "Pomerium",
    "SacrosanctRegistry",
    "TrustLedger",
    "appoint_dictator",
    "attenuate",
    "dual_gate",
    "imperium_maius",
    "is_ratified",
    "permitted",
    "sign_manifest",
    "sign_token",
    "validate_manifest",
    "verify_token",
]
