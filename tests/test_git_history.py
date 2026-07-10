"""Tests for git-history miner helpers: hunk parsing + multi-repo/branch state."""

from citadel.git_history_miner import (
    _new_side_ranges,
    get_last_sha,
    load_miner_state,
    save_repo_branch_state,
)

DIFF = """\
diff --git a/pkg/mod.py b/pkg/mod.py
index 111..222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -10,0 +11,3 @@ def foo():
+    a = 1
+    b = 2
+    c = 3
@@ -40 +43 @@ def bar():
-    old()
+    new()
diff --git a/deleted.py b/deleted.py
deleted file mode 100644
--- a/deleted.py
+++ /dev/null
@@ -1,5 +0,0 @@
"""


def test_new_side_ranges_parses_added_and_changed():
    ranges = _new_side_ranges(DIFF)
    assert ranges["pkg/mod.py"] == [(11, 3), (43, 1)]
    assert "deleted.py" not in ranges


def test_new_side_ranges_default_count():
    diff = "+++ b/x.py\n@@ -5 +7 @@\n+line\n"
    assert _new_side_ranges(diff) == {"x.py": [(7, 1)]}


def test_repo_branch_state_roundtrip(tmp_path):
    state_file = tmp_path / "git-miner-state.json"
    save_repo_branch_state(state_file, "repoA", "dev", "abc123")
    save_repo_branch_state(state_file, "repoA", "main", "def456")
    save_repo_branch_state(state_file, "repoB", "dev", "999aaa")

    state = load_miner_state(state_file)
    assert get_last_sha(state, "repoA", "dev") == "abc123"
    assert get_last_sha(state, "repoA", "main") == "def456"
    assert get_last_sha(state, "repoB", "dev") == "999aaa"
    assert get_last_sha(state, "repoA", "master") is None
    assert get_last_sha(state, "nope", "dev") is None


def test_repo_branch_state_advances(tmp_path):
    state_file = tmp_path / "s.json"
    save_repo_branch_state(state_file, "r", "dev", "sha1")
    save_repo_branch_state(state_file, "r", "dev", "sha2")
    assert get_last_sha(load_miner_state(state_file), "r", "dev") == "sha2"
