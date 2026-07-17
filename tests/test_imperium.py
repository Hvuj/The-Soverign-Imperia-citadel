"""P4 — the Imperia: family→Imperium routing + jurisdiction rails (trie) + the capability-token gate. An op
outside a family's rails is refused; inside + a valid fasces token, allowed; inside but no/insufficient
token, refused (the capability token is required)."""

from citadel.services.authority.fasces import DELETE_PATH, WRITE_FILE, sign_token
from citadel.services.authority.pomerium import DOMI, MILITIAE, Pomerium
from citadel.services.imperium.rails import Rails, op_capability
from citadel.services.imperium.registry import Imperium, ImperiumRegistry

_KEY = b"test-key"


def _token(mask: int, *, expiry: float = 9_999_999_999.0):  # far-future epoch seconds
    return sign_token("gpt-oss", "legatus", mask, "lease-1", DOMI, expiry, key=_KEY)


# ── rails trie ────────────────────────────────────────────────────────────────────────
def test_rails_default_deny_and_allow():
    r = Rails(allow=["write:src/**", "net:api.groq.com"])
    assert r.permits("write:src/app.py") is True
    assert r.permits("write:src/pkg/mod.py") is True     # ** spans segments
    assert r.permits("net:api.groq.com") is True
    assert r.permits("delete:src/app.py") is False       # no allow rule → default-deny
    assert r.permits("net:evil.com") is False


def test_rails_deny_takes_precedence():
    r = Rails(allow=["write:src/**"], deny=["write:src/secrets/**"])
    assert r.permits("write:src/app.py") is True
    assert r.permits("write:src/secrets/keys.py") is False   # deny wins over the broader allow
    ok, reason = r.check("write:src/secrets/keys.py")
    assert ok is False
    assert "denied" in reason


def test_rails_single_star_matches_one_segment():
    r = Rails(allow=["read:*"])
    assert r.permits("read:file") is True
    assert r.permits("read:dir/file") is False           # '*' is one segment, not '**'


def test_double_star_allow_all():
    assert Rails(allow=["**"]).permits("anything:goes/here") is True
    assert Rails().permits("anything") is False           # empty allow → deny everything


def test_op_capability_maps_verbs():
    assert op_capability("write:src/a.py") == WRITE_FILE
    assert op_capability("delete:x") == DELETE_PATH
    assert op_capability("read:x") == 0                   # read needs no mutate right


# ── registry routing + two-gate authorize ───────────────────────────────────────────────
def _registry() -> ImperiumRegistry:
    imp = Imperium(
        family="gpt-oss",
        rails=Rails(allow=["write:src/**", "read:**"], deny=["write:src/secrets/**"]),
        fasces_mask=WRITE_FILE,
        legion=["provider:groq:openai/gpt-oss-120b", "provider:groq:openai/gpt-oss-20b"],
        auxilia=["web-search", "retrieval"],
        pomerium=Pomerium(militiae_prefixes=["/tmp"], default_zone=MILITIAE),
    )
    return ImperiumRegistry().register(imp)


def test_registry_routes_model_to_family_imperium():
    reg = _registry()
    imp = reg.for_model("provider:groq:openai/gpt-oss-120b")
    assert imp is not None
    assert imp.family == "gpt-oss"
    assert reg.for_model("provider:nvidia:meta/llama-3.3-70b") is None   # different family, ungoverned


def test_op_outside_rails_is_refused():
    reg = _registry()
    ok, reason = reg.authorize("provider:groq:openai/gpt-oss-120b", "force_push:main", token=_token(WRITE_FILE))
    assert ok is False
    assert "jurisdiction" in reason


def test_op_inside_rails_needs_capability_token():
    reg = _registry()
    # no token → refused even though rails allow it
    ok, reason = reg.authorize("provider:groq:openai/gpt-oss-120b", "write:src/app.py", path="/tmp/app.py")
    assert ok is False
    assert "token" in reason
    # valid token granting WRITE_FILE → authorized
    ok, _ = reg.authorize("provider:groq:openai/gpt-oss-120b", "write:src/app.py",
                          token=_token(WRITE_FILE), key=_KEY, path="/tmp/app.py")
    assert ok is True
    # a token that lacks WRITE_FILE → refused
    ok, reason = reg.authorize("provider:groq:openai/gpt-oss-120b", "write:src/app.py",
                               token=_token(DELETE_PATH), key=_KEY, path="/tmp/app.py")
    assert ok is False
    assert "capability" in reason


def test_read_op_inside_rails_needs_no_token():
    reg = _registry()
    ok, _ = reg.authorize("provider:groq:openai/gpt-oss-120b", "read:src/app.py")
    assert ok is True                                     # read is rails-governed only


def test_ungoverned_family_is_denied():
    reg = _registry()
    ok, reason = reg.authorize("provider:nvidia:meta/llama-3.3-70b", "read:x")
    assert ok is False
    assert "ungoverned" in reason
