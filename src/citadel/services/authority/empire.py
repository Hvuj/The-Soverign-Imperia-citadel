"""The Empire — the command hierarchy (masterplan §5.6, §4).

An Imperium is a holder of authority: a capability mask (its fasces), a pomerium (its zone policy), and a
lease id (its grant is never forever). Delegation can only ATTENUATE — a Legatus receives `parent & requested`,
so no legate can out-rank the officer who appointed it, and its effective mask is precomputed once, making a
later permission check a single AND rather than a walk up the chain. Two constitutional invariants bind even
the top of the hierarchy: the pomerium removes the axe inside protected zones for *every* rank (the emperor
may not wield the axe within the wall), and a Dictator's extraordinary grant rides a short auto-expiring lease
(absolute power, but only until the reaper collects it). The MagisterEquitum is the Dictator's pre-authorized
second — a hot standby that assumes the same imperium if the principal falls, with no fresh grant ceremony.
"""

from dataclasses import dataclass, replace

from citadel.services.authority.fasces import AXE_CLASS, attenuate
from citadel.services.authority.lease import LeaseReaper
from citadel.services.authority.pomerium import Pomerium

# The full rod set (reversible) and the full axe set (irreversible) — Maius holds both.
RODS_ALL = (1 << 6) - 1
IMPERIUM_MAIUS = RODS_ALL | AXE_CLASS


@dataclass(frozen=True, slots=True)
class Imperium:
    imperium_id: str
    rank: str
    mask: int
    pomerium: Pomerium
    lease_id: str

    def permits(self, required: int, path: str) -> bool:
        """O(1) check against the precomputed effective mask: the axe is stripped inside the pomerium."""
        in_domi = self.pomerium.in_domi(path)
        effective = self.mask & ~AXE_CLASS if in_domi else self.mask
        return (required & effective) == required

    def delegate(self, legate_id: str, requested_mask: int, lease_id: str, *, rank: str = "legatus") -> "Imperium":
        """Appoint a Legatus. Attenuation-only: the legate's mask is `self.mask & requested` — never more."""
        return Imperium(legate_id, rank, attenuate(self.mask, requested_mask), self.pomerium, lease_id)


def imperium_maius(pomerium: Pomerium, lease_id: str, *, imperium_id: str = "maius") -> Imperium:
    """The root supervisor — every rod and every axe."""
    return Imperium(imperium_id, "maius", IMPERIUM_MAIUS, pomerium, lease_id)


@dataclass(slots=True)
class Dictator:
    """An extraordinary imperium: a broad mask on a short auto-expiring lease, with a pre-named second in
    command. The lease is the safeguard — when the reaper collects it the dictatorship simply ends."""

    imperium: Imperium
    reaper: LeaseReaper
    ttl_seconds: float
    magister_equitum_id: str
    _now: float = 0.0

    def is_in_command(self, *, now: float | None = None) -> bool:
        return self.reaper.is_valid(self.imperium.lease_id, now=now)

    def hand_to_magister(self) -> Imperium:
        """Hot standby: the MagisterEquitum assumes the same imperium (same mask, same lease) with no new grant."""
        return replace(self.imperium, imperium_id=self.magister_equitum_id, rank="magister_equitum")


def appoint_dictator(
    pomerium: Pomerium,
    reaper: LeaseReaper,
    *,
    ttl_seconds: float,
    magister_equitum_id: str,
    lease_id: str = "dictatura",
    now: float | None = None,
) -> Dictator:
    """Grant the dictatorship: broad mask, short TTL lease (the reaper auto-expires it), a standby pre-named."""
    reaper.grant(lease_id, "dictator", ttl_seconds, now=now)
    imperium = Imperium("dictator", "dictator", IMPERIUM_MAIUS, pomerium, lease_id)
    return Dictator(imperium, reaper, ttl_seconds, magister_equitum_id)
