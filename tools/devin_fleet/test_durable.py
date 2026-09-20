"""Local fault injection only: no Devin/network calls or live runtime edits."""
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from . import durable
except ImportError:
    import durable


def state(round_number=1):
    return {"round": round_number, "status": "checkpoint", "candidates": {}, "reports": {}, "sessions": {}}


class DurableStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fleet-durable-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "state.json"

    def test_atomic_write_fsyncs_and_replaces(self):
        with patch.object(durable.os, "fsync", wraps=durable.os.fsync) as sync:
            durable.atomic_write_json(self.path, {"unicode": "回復"})
        self.assertGreaterEqual(sync.call_count, 1)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"unicode": "回復"})
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_transient_windows_share_error_retries(self):
        actual_replace = durable.os.replace
        attempts = []
        def flaky(source, target):
            attempts.append(1)
            if len(attempts) < 3:
                failure = PermissionError(errno.EACCES, "sharing violation")
                failure.winerror = 32
                raise failure
            return actual_replace(source, target)
        with patch.object(durable.os, "replace", side_effect=flaky), patch.object(durable.time, "sleep"):
            durable.atomic_write_json(self.path, state())
        self.assertEqual(len(attempts), 3)

    def test_permanent_replace_failure_preserves_previous_file(self):
        durable.atomic_write_json(self.path, state(1))
        with patch.object(durable.os, "replace", side_effect=PermissionError(errno.EACCES, "denied")) as replace, \
                patch.object(durable.time, "sleep"):
            with self.assertRaises(PermissionError):
                durable.atomic_write_json(self.path, state(2))
        self.assertEqual(replace.call_count, 6)
        self.assertEqual(json.loads(self.path.read_text())["round"], 1)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_nonsharing_error_is_not_retried(self):
        with patch.object(durable.os, "replace", side_effect=OSError(errno.ENOSPC, "disk full")) as replace:
            with self.assertRaises(OSError):
                durable.atomic_write_json(self.path, state())
        self.assertEqual(replace.call_count, 1)

    def test_backup_is_previous_valid_generation(self):
        durable.write_state(self.path, state(1))
        durable.write_state(self.path, state(2))
        self.assertEqual(durable.read_state(self.path)["round"], 2)
        self.assertEqual(json.loads((self.root / "state.json.bak").read_text())["round"], 1)

    def test_corrupt_primary_recovers_backup_and_preserves_exact_bytes(self):
        durable.write_state(self.path, state(1))
        durable.write_state(self.path, state(2))
        corrupt = b'{"round": 3,'
        self.path.write_bytes(corrupt)
        result = durable.read_state(self.path)
        self.assertEqual(result["round"], 1)
        self.assertEqual(Path(result["recovery"]["corrupt_evidence"]).read_bytes(), corrupt)
        self.assertEqual(durable.read_state(self.path), result)

    def test_valid_json_wrong_schema_is_not_accepted(self):
        durable.write_state(self.path, state(1))
        self.path.write_text('{"round":99}', encoding="utf-8")
        self.assertEqual(durable.read_state(self.path)["round"], 1)

    def test_both_invalid_fail_without_reset_or_evidence_mutation(self):
        self.path.write_bytes(b"corrupt")
        backup = self.root / "state.json.bak"
        backup.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(durable.RecoveryError, "no automatic reset"):
            durable.read_state(self.path)
        self.assertEqual(self.path.read_bytes(), b"corrupt")
        self.assertEqual(backup.read_text(), "[]")

    def test_missing_primary_can_recover_valid_backup(self):
        durable.write_state(self.path, state())
        self.path.unlink()
        self.assertIsNone(durable.read_state(self.path)["recovery"]["corrupt_evidence"])

    def test_invalid_new_state_cannot_replace_good_state_or_backup(self):
        durable.write_state(self.path, state())
        original = self.path.read_bytes()
        with self.assertRaises(durable.RecoveryError):
            durable.write_state(self.path, {"round": 5})
        self.assertEqual(self.path.read_bytes(), original)

    def test_corrupt_old_primary_cannot_poison_backup_during_write(self):
        durable.write_state(self.path, state())
        backup = (self.root / "state.json.bak").read_bytes()
        self.path.write_bytes(b"bad")
        with self.assertRaises(durable.RecoveryError):
            durable.write_state(self.path, state(2))
        self.assertEqual((self.root / "state.json.bak").read_bytes(), backup)
        self.assertEqual(self.path.read_bytes(), b"bad")

    def test_core_schema_rejects_unsafe_receipts_but_accepts_extensions(self):
        valid = state()
        valid["new_extension"] = {"v": 1}
        self.assertIs(durable.validate_state(valid), valid)
        for mutate in (
                lambda s: s.update(round=True),
                lambda s: s.update(status="unrecognized"),
                lambda s: s["sessions"].update(machine=7),
                lambda s: s["reports"].update(machine="not an object"),
                lambda s: s["candidates"].update({"HEAD": {"role": "machine", "status": "pending"}}),
                lambda s: s["candidates"].update({"a" * 40: {"role": "machine", "status": "trusted"}})):
            invalid = state()
            mutate(invalid)
            with self.subTest(state=invalid), self.assertRaises(durable.RecoveryError):
                durable.validate_state(invalid)

    def test_nonfinite_json_is_not_written(self):
        with self.assertRaises(ValueError):
            durable.atomic_write_json(self.path, {"invalid": float("nan")})
        self.assertFalse(self.path.exists())


class IntegrationJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fleet-journal-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "integration.json"
        self.log = self.root / "validation.log"
        self.log.write_text("All tests passed\n", encoding="utf-8")
        self.before, self.target, self.selected = "a" * 40, "b" * 40, ["c" * 40]

    def prepare(self):
        return durable.write_integration_journal(self.path, self.before, self.target, self.selected, 2, self.log)

    def test_crash_before_ref_update_proposes_exact_validated_target(self):
        self.prepare()
        result = durable.integration_recovery(self.path, self.before, True)
        self.assertEqual(result["action"], "apply")
        self.assertEqual(result["journal"]["target"], self.target)

    def test_crash_after_ref_update_only_finalizes_candidate_states(self):
        self.prepare()
        self.assertEqual(durable.integration_recovery(self.path, self.target, True)["action"], "finalize")
        durable.advance_integration_journal(self.path, "applied")
        self.assertEqual(durable.integration_recovery(self.path, self.target, True)["action"], "finalize")
        durable.advance_integration_journal(self.path, "complete")
        self.assertEqual(durable.integration_recovery(self.path, "d" * 40, True)["action"], "complete")

    def test_unknown_head_or_dirty_worktree_pauses(self):
        self.prepare()
        for head, clean in (("d" * 40, True), (self.before, False), (self.target, False)):
            with self.subTest(head=head, clean=clean), self.assertRaises(durable.RecoveryError):
                durable.integration_recovery(self.path, head, clean)

    def test_applied_journal_with_rolled_back_ref_requires_inspection(self):
        self.prepare()
        durable.advance_integration_journal(self.path, "applied")
        with self.assertRaisesRegex(durable.RecoveryError, "HEAD disagrees"):
            durable.integration_recovery(self.path, self.before, True)

    def test_changed_or_missing_validation_log_prevents_recovery(self):
        self.prepare()
        self.log.write_text("different result\n", encoding="utf-8")
        with self.assertRaisesRegex(durable.RecoveryError, "evidence changed"):
            durable.integration_recovery(self.path, self.target, True)
        self.log.unlink()
        with self.assertRaisesRegex(durable.RecoveryError, "evidence is unavailable"):
            durable.integration_recovery(self.path, self.before, True)

    def test_unfinished_journal_cannot_be_overwritten(self):
        self.prepare()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(durable.RecoveryError, "Unfinished"):
            self.prepare()
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_transition_or_receipt_fails_closed(self):
        self.prepare()
        with self.assertRaisesRegex(durable.RecoveryError, "transition"):
            durable.advance_integration_journal(self.path, "complete")
        record = json.loads(self.path.read_text())
        record["target"] = "HEAD"
        self.path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(durable.RecoveryError, "Invalid integration journal"):
            durable.integration_recovery(self.path, self.before, True)

    def test_no_journal_is_no_recovery(self):
        self.assertIsNone(durable.integration_recovery(self.path, self.before, True))


if __name__ == "__main__":
    unittest.main()
