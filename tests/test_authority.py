"""Control-plane authority (masterplan §4.7/§4.8/§5.4): fasces tokens, pomerium zones, leases."""

from citadel.services.authority import (
    DOMI,
    MILITIAE,
    FascesToken,
    LeaseReaper,
    Pomerium,
    attenuate,
    permitted,
    sign_token,
    verify_token,
)
from citadel.services.authority.fasces import DELETE_PATH, WRITE_FILE

_KEY = b"test-root-key"


def _token(mask, expiry=0.0):
    return sign_token("imp", "consul", mask, "lease1", "policy", expiry, key=_KEY)


def test_permitted_grants_held_rod():
    token = _token(WRITE_FILE)
    assert permitted(WRITE_FILE, token, in_domi=False) is True
    assert permitted(DELETE_PATH, token, in_domi=False) is False


def test_axe_removed_inside_pomerium():
    token = _token(WRITE_FILE | DELETE_PATH)
    assert permitted(DELETE_PATH, token, in_domi=False) is True
    assert permitted(DELETE_PATH, token, in_domi=True) is False
    assert permitted(WRITE_FILE, token, in_domi=True) is True


def test_hmac_binding_is_tamper_evident():
    token = _token(WRITE_FILE)
    assert verify_token(token, key=_KEY) is True
    forged = FascesToken(
        token.imperium_id, token.rank, token.mask | DELETE_PATH,
        token.lease_id, token.zone_policy, token.expiry, token.signature,
    )
    assert verify_token(forged, key=_KEY) is False
    assert permitted(DELETE_PATH, forged, in_domi=False, key=_KEY) is False


def test_expired_token_denied():
    token = _token(WRITE_FILE, expiry=1000.0)
    assert permitted(WRITE_FILE, token, in_domi=False, now=2000.0) is False
    assert permitted(WRITE_FILE, token, in_domi=False, now=500.0) is True


def test_attenuate_only_removes_bits():
    assert attenuate(WRITE_FILE | DELETE_PATH, WRITE_FILE) == WRITE_FILE
    assert attenuate(WRITE_FILE, WRITE_FILE | DELETE_PATH) == WRITE_FILE


def test_pomerium_zones_longest_prefix():
    pom = Pomerium(domi_prefixes=["/repo", "/repo/.git"], militiae_prefixes=["/repo/worktrees", "/tmp"])
    assert pom.zone("/repo/main/x.py") == DOMI
    assert pom.zone("/repo/.git/config") == DOMI
    assert pom.zone("/repo/worktrees/feature/x.py") == MILITIAE
    assert pom.zone("/tmp/scratch") == MILITIAE
    assert pom.zone("/unknown/path") == DOMI


def test_pomerium_onedrive_and_mnt_c_always_domi():
    pom = Pomerium(militiae_prefixes=["/mnt/c/tmp"])
    assert pom.zone("/mnt/c/tmp/x") == DOMI
    assert pom.zone("C:/Users/x/OneDrive/proj/.claude") == DOMI


def test_lease_grant_expire_revoke_reap():
    reaper = LeaseReaper()
    reaper.grant("L1", "worker-A", ttl_seconds=100, now=1000.0)
    assert reaper.is_valid("L1", now=1050.0) is True
    assert reaper.is_valid("L1", now=1200.0) is False
    reaper.grant("L2", "worker-B", ttl_seconds=100, now=1000.0)
    reaper.revoke("L2")
    assert reaper.is_valid("L2", now=1050.0) is False
    dead = reaper.reap(now=1200.0)
    assert {d.lease_id for d in dead} == {"L1", "L2"}
    assert reaper.next_expiry() is None


def test_lease_next_expiry_is_minimum():
    reaper = LeaseReaper()
    reaper.grant("A", "s", 50, now=0.0)
    reaper.grant("B", "s", 10, now=0.0)
    assert reaper.next_expiry() == 10.0
