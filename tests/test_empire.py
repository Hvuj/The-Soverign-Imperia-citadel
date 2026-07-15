"""The Empire (masterplan §5.6/§4): the command hierarchy — Maius holds all authority, Legati are
attenuation-only (no escalation), the pomerium binds even the emperor, and a Dictator's extraordinary
grant auto-expires via the lease reaper with a pre-authorized MagisterEquitum standby."""

from citadel.services.authority import (
    IMPERIUM_MAIUS,
    LeaseReaper,
    Pomerium,
    appoint_dictator,
    imperium_maius,
)
from citadel.services.authority.fasces import CONDEMN, DELETE_PATH, WRITE_FILE

_MILITIAE = Pomerium(domi_prefixes=["/repo/.git"], militiae_prefixes=["/tmp", "/sandbox"])


def test_maius_holds_every_rod_and_axe():
    maius = imperium_maius(_MILITIAE, "root-lease")
    assert maius.mask == IMPERIUM_MAIUS
    assert maius.permits(WRITE_FILE, "/sandbox/x")
    assert maius.permits(DELETE_PATH | CONDEMN, "/sandbox/x")


def test_legatus_delegation_is_attenuation_only():
    maius = imperium_maius(_MILITIAE, "root-lease")
    # a legate asks for the whole world but is a write-only officer: it receives write only
    legate = maius.delegate("legate-1", WRITE_FILE, "legate-lease")
    assert legate.permits(WRITE_FILE, "/sandbox/x")
    assert not legate.permits(DELETE_PATH, "/sandbox/x")


def test_legatus_cannot_escalate_beyond_parent():
    write_only = imperium_maius(_MILITIAE, "root-lease").delegate("l1", WRITE_FILE, "l1-lease")
    # a sub-legate requests the axe; the parent lacks it, so attenuation yields nothing extra
    sub = write_only.delegate("l2", DELETE_PATH | CONDEMN, "l2-lease")
    assert sub.mask == 0
    assert not sub.permits(DELETE_PATH, "/sandbox/x")


def test_pomerium_removes_the_axe_even_for_maius():
    maius = imperium_maius(_MILITIAE, "root-lease")
    # inside the protected .git zone the axe is stripped for every rank
    assert not maius.permits(DELETE_PATH, "/repo/.git/config")
    assert maius.permits(WRITE_FILE, "/repo/.git/config")  # rods survive


def test_dictator_auto_expires_via_the_reaper():
    reaper = LeaseReaper()
    dictator = appoint_dictator(
        _MILITIAE, reaper, ttl_seconds=180, magister_equitum_id="magister-1", now=0.0
    )
    assert dictator.is_in_command(now=100.0) is True
    assert dictator.imperium.permits(DELETE_PATH, "/sandbox/x") is True
    # the reaper collects the dictatorship after its short TTL
    dead = reaper.reap(now=1000.0)
    assert [d.lease_id for d in dead] == ["dictatura"]
    assert dictator.is_in_command(now=1000.0) is False


def test_magister_equitum_is_a_hot_standby_with_no_new_grant():
    reaper = LeaseReaper()
    dictator = appoint_dictator(
        _MILITIAE, reaper, ttl_seconds=180, magister_equitum_id="magister-1", now=0.0
    )
    standby = dictator.hand_to_magister()
    assert standby.imperium_id == "magister-1"
    assert standby.rank == "magister_equitum"
    assert standby.mask == dictator.imperium.mask  # same imperium, no ceremony
    assert standby.lease_id == dictator.imperium.lease_id
