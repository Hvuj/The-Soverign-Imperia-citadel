"""provinces.py — provincial assignment (System 5): map runtime engines to isolated environments.

The Senate assigns engines to **Provinces** — isolated container/zone environments. Protected work
(`domi`) runs on trusted local engines; risky/outward work (`militiae`) is routed to a sandboxed container
(Docker/MCP). This reuses the `Pomerium` zone classifier (longest-prefix, O(depth)), so a task/path is routed
to the Province that matches its zone — the Bulkhead that keeps one province's blast radius contained.
"""

from dataclasses import dataclass

from citadel.services.authority.pomerium import Pomerium


@dataclass(frozen=True, slots=True)
class Province:
    name: str
    zone: str        # domi | militiae
    container: str   # "local" | "docker:<image>" | "sandbox" | …


class Provinces:
    def __init__(self, pomerium: Pomerium | None = None) -> None:
        self._pomerium = pomerium or Pomerium()
        self._by_name: dict[str, Province] = {}
        self._by_zone: dict[str, Province] = {}

    def define(self, province: Province) -> "Provinces":
        self._by_name[province.name] = province
        self._by_zone.setdefault(province.zone, province)  # first defined wins as the zone's default
        return self

    def get(self, name: str) -> Province | None:
        return self._by_name.get(name)

    def zone_of(self, path) -> str:
        return self._pomerium.zone(path)

    def route(self, path) -> Province | None:
        """Route a path/task to the Province governing its zone (domi→trusted, militiae→sandbox)."""
        return self._by_zone.get(self._pomerium.zone(path))

    def names(self) -> list[str]:
        return sorted(self._by_name)
