"""Redis connection config: the resolver precedence (explicit > env > config.toml > default), the
`enabled=false` opt-out, and the targeted config writer that preserves other sections."""

import pytest

from citadel import paths


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("CITADEL_REDIS_URL", raising=False)


def test_default_when_nothing_set(tmp_path):
    assert paths.resolve_redis_url(tmp_path) == "redis://127.0.0.1:6379"


def test_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("CITADEL_REDIS_URL", "redis://env:6379")
    assert paths.resolve_redis_url(tmp_path, explicit="redis://explicit:6379") == "redis://explicit:6379"


def test_env_beats_config(tmp_path, monkeypatch):
    paths.set_redis_config(tmp_path, url="redis://config:6379")
    monkeypatch.setenv("CITADEL_REDIS_URL", "redis://env:6379")
    assert paths.resolve_redis_url(tmp_path) == "redis://env:6379"


def test_config_used_when_no_explicit_or_env(tmp_path):
    paths.set_redis_config(tmp_path, url="redis://myhost:6380")
    assert paths.resolve_redis_url(tmp_path) == "redis://myhost:6380"


def test_disabled_returns_none(tmp_path):
    paths.set_redis_config(tmp_path, enabled=False)
    assert paths.resolve_redis_url(tmp_path) is None


def test_writer_preserves_other_sections(tmp_path):
    cfg = tmp_path / ".citadel" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[git]\nbranches = ["main"]\n\n[index]\nscan_root = "/x"\n', encoding="utf-8")
    paths.set_redis_config(tmp_path, url="redis://myhost:6379")
    text = cfg.read_text(encoding="utf-8")
    assert "[git]" in text and 'branches = ["main"]' in text
    assert "[index]" in text and 'scan_root = "/x"' in text
    assert paths.resolve_redis_url(tmp_path) == "redis://myhost:6379"


def test_writer_replaces_existing_redis_block(tmp_path):
    paths.set_redis_config(tmp_path, url="redis://old:6379")
    paths.set_redis_config(tmp_path, url="redis://new:6379")
    text = (tmp_path / ".citadel" / "config.toml").read_text(encoding="utf-8")
    assert text.count("[redis]") == 1  # replaced, not duplicated
    assert paths.resolve_redis_url(tmp_path) == "redis://new:6379"
