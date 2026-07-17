"""citadel.services.senate — the Senate (System 5): governance atop the shared brain.

A persistent, read-optimized knowledge + routing layer. Knowledge is promoted up the **Cursus Honorum**
(each rung gated by a not-self distinct-identity quorum) until it becomes an authoritative **Senatus
Consultum** (content-addressed, versioned, weighted — appealable, never a hard law). The **Princeps** speaks
first but cannot dictate (quorum required); stale Consulta are **JIT-demoted** when their sources change.
"""

from citadel.services.senate.aerarium import Aerarium
from citadel.services.senate.consulta import ConsultaStore, SenatusConsultum
from citadel.services.senate.cursus import RANKS, CursusHonorum, Proposal
from citadel.services.senate.decay import is_stale, sweep
from citadel.services.senate.foreign import ForeignPolicy
from citadel.services.senate.princeps import Princeps
from citadel.services.senate.provinces import Province, Provinces
from citadel.services.senate.scu import CircuitBreaker, SenatusConsultumUltimum

__all__ = [
    "RANKS",
    "Aerarium",
    "CircuitBreaker",
    "ConsultaStore",
    "CursusHonorum",
    "ForeignPolicy",
    "Princeps",
    "Proposal",
    "Province",
    "Provinces",
    "SenatusConsultum",
    "SenatusConsultumUltimum",
    "is_stale",
    "sweep",
]
