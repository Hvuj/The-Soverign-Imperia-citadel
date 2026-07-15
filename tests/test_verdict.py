"""Verdict ledger + condemned set (masterplan §4.3) + content-addressed pre-image backup."""

from citadel.services.execute.verdict import PASS, VerdictLedger, artifact_hash


def test_artifact_hash_stable_and_distinct():
    assert artifact_hash("A = 1") == artifact_hash("A = 1")
    assert artifact_hash("A = 1") != artifact_hash("A = 2")


def test_record_and_verdict(tmp_path):
    ledger = VerdictLedger(tmp_path)
    digest = artifact_hash("x")
    ledger.record(digest, PASS)
    assert ledger.verdict(digest) == PASS
    assert ledger.is_condemned(digest) is False


def test_condemn_rejects_forever_and_persists(tmp_path):
    ledger = VerdictLedger(tmp_path)
    digest = artifact_hash("bad artifact")
    ledger.condemn(digest)
    assert ledger.is_condemned(digest) is True
    assert VerdictLedger(tmp_path).is_condemned(digest) is True


def test_backup_content_addressed_dedup(tmp_path):
    root = tmp_path / "ledger"
    ledger = VerdictLedger(root)
    target = tmp_path / "mod.py"
    target.write_text("OLD\n", encoding="utf-8")
    first = ledger.backup(target)
    second = ledger.backup(target)
    assert first == second
    pre_images = list((root / "pre-images").iterdir())
    assert len(pre_images) == 1
    assert pre_images[0].read_text(encoding="utf-8") == "OLD\n"


def test_backup_absent_file_returns_none(tmp_path):
    assert VerdictLedger(tmp_path).backup(tmp_path / "nope.py") is None
