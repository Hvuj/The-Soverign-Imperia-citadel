"""Master plan §11.4 — the dot-directory contract matrix. `ensure_dot_dir` must never break these,
so the ".claude is broken when clicked" class of bug cannot regress."""

from pathlib import Path

import pytest

from citadel.paths import CitadelBootError, ensure_dot_dir, is_unsafe_placement


def test_1_fresh_create(tmp_path):
    created = ensure_dot_dir(tmp_path / ".claude")
    assert created.is_dir()
    assert not (created / ".citadel-probe").exists()


def test_2_idempotent(tmp_path):
    target = tmp_path / ".claude"
    assert ensure_dot_dir(target) == ensure_dot_dir(target)
    assert target.is_dir()


def test_3_file_squatting_is_quarantined(tmp_path):
    target = tmp_path / ".claude"
    target.write_text("i am a squatting file", encoding="utf-8")
    created = ensure_dot_dir(target)
    assert created.is_dir()
    broken = list(tmp_path.glob(".claude.broken.*"))
    assert len(broken) == 1
    assert broken[0].read_text(encoding="utf-8") == "i am a squatting file"


def test_4_symlink_to_dir_accepted(tmp_path):
    real = tmp_path / "realdir"
    real.mkdir()
    link = tmp_path / ".claude"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")
    assert ensure_dot_dir(link).is_dir()


def test_5_symlink_to_file_quarantined(tmp_path):
    realfile = tmp_path / "realfile"
    realfile.write_text("x", encoding="utf-8")
    link = tmp_path / ".claude"
    try:
        link.symlink_to(realfile)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")
    assert ensure_dot_dir(link).is_dir()


def test_6_mkdir_failure_raises_boot_error(tmp_path, monkeypatch):
    def boom(self, *args, **kwargs):
        raise OSError("read-only parent")

    monkeypatch.setattr(Path, "mkdir", boom)
    with pytest.raises(CitadelBootError):
        ensure_dot_dir(tmp_path / ".claude")


def test_7_mnt_c_refused_in_strict_mode():
    assert is_unsafe_placement(Path("/mnt/c/Users/x/.claude")) is not None
    with pytest.raises(CitadelBootError):
        ensure_dot_dir("/mnt/c/Users/x/.claude", strict=True)


def test_8_onedrive_refused_in_strict_mode(tmp_path):
    target = tmp_path / "OneDrive" / "proj" / ".claude"
    assert is_unsafe_placement(target) is not None
    with pytest.raises(CitadelBootError):
        ensure_dot_dir(target, strict=True)


def test_9_repeated_invoke_no_torn_state(tmp_path):
    target = tmp_path / ".claude"
    for _ in range(5):
        assert ensure_dot_dir(target).is_dir()


def test_10_nested_create(tmp_path):
    created = ensure_dot_dir(tmp_path / ".claude" / "agents")
    assert created.is_dir()
    assert (tmp_path / ".claude").is_dir()


def test_11_probe_failure_raises_and_leaves_no_marker(tmp_path, monkeypatch):
    original = Path.write_text

    def fail_probe(self, *args, **kwargs):
        if self.name == ".citadel-probe":
            raise OSError("disk full")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_probe)
    with pytest.raises(CitadelBootError):
        ensure_dot_dir(tmp_path / ".claude")
    assert not (tmp_path / ".claude" / ".citadel-probe").exists()


def test_safe_placement_returns_none(tmp_path):
    assert is_unsafe_placement(tmp_path / ".claude") is None
