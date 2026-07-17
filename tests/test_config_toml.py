"""`.citadel/config.toml` writer/reader robustness — regression guards for the Windows-path bug where a
backslash path in a double-quoted TOML string (C:\\Users -> \\U) crashed tomllib and took `citadel up` down."""

import tomllib
from pathlib import Path

from citadel import paths
from citadel.commands.init import _write_config_toml


def test_write_config_toml_is_valid_toml(tmp_path):
    (tmp_path / ".citadel").mkdir(parents=True)
    _write_config_toml(tmp_path, "main")
    cfg = tmp_path / ".citadel" / "config.toml"

    # On Windows tmp_path is C:\Users\... — a double-quoted TOML string used to make tomllib
    # read \U as a Unicode escape and raise. The written file must always parse.
    with cfg.open("rb") as fh:
        data = tomllib.load(fh)
    assert Path(data["workspace"]["root"]) == Path(tmp_path)
    assert "\\" not in data["workspace"]["root"]  # stored as forward slashes


def test_resolve_home_survives_malformed_config(tmp_path, monkeypatch):
    home = tmp_path / paths.HOME_DIR_NAME / ".citadel"
    home.mkdir(parents=True)
    # A raw Windows path (the exact shape the old writer produced) — invalid TOML.
    (home / "config.toml").write_text('[workspace]\nroot = "C:\\Users\\x"\n', encoding="utf-8")
    monkeypatch.delenv("CITADEL_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)

    # Must degrade to the citadel-home dir instead of raising TOMLDecodeError.
    assert paths.resolve_home().resolve() == (tmp_path / paths.HOME_DIR_NAME).resolve()
