"""Windows junction regressions for repeated/forced initialization."""

import os

import pytest

from citadel.commands import init as init_command

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")


def _create_junction(target, link):
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def test_ensure_root_symlinks_preserves_correct_junction(tmp_path):
    managed = tmp_path / ".citadel" / ".claude"
    managed.mkdir(parents=True)
    root_link = tmp_path / ".claude"
    _create_junction(managed, root_link)
    original_file_id = os.lstat(root_link).st_ino

    try:
        init_command._ensure_root_symlinks(tmp_path)

        assert os.path.isjunction(root_link)
        assert os.path.samefile(root_link, managed)
        assert os.lstat(root_link).st_ino == original_file_id
    finally:
        if os.path.lexists(root_link):
            init_command._remove_link(root_link)


def test_ensure_root_symlinks_replaces_stale_junction(tmp_path):
    managed = tmp_path / ".citadel" / ".claude"
    managed.mkdir(parents=True)
    stale_target = tmp_path / "stale-claude"
    stale_target.mkdir()
    root_link = tmp_path / ".claude"
    _create_junction(stale_target, root_link)

    try:
        init_command._ensure_root_symlinks(tmp_path)

        assert os.path.isjunction(root_link)
        assert os.path.samefile(root_link, managed)
        assert not os.path.samefile(root_link, stale_target)
    finally:
        if os.path.lexists(root_link):
            init_command._remove_link(root_link)
