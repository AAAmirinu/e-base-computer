"""Control-plane crash/race regression tests; no Devin or generated code is run."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fleet
from process_control import GlobalLock, LockUnavailable


class ControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fleet-control-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.roles = {"coordinator": {"paths": []}, **{f"worker{i}": {"paths": []} for i in range(9)}}
        fleet.write(self.root / "roles.json", self.roles)
        fleet.write(self.root / "settings.json", {"model": fleet.MODEL, "max_disk_gb": 5,
                    "executable": "never-launch-devin", "python": "never-launch-python"})
        self.state = {"round": 1, "status": "paused", "candidates": {}, "sessions": {}, "reports": {}}
        fleet.write(self.root / "state.json", self.state)
        self.locks = self.root / "test-global.lock"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(fleet, "GlobalLock", side_effect=lambda path=None: GlobalLock(path or self.locks)))
        self.stack.enter_context(patch.object(fleet, "check_existing_sessions"))
        self.stack.enter_context(patch.object(fleet, "recover_integration"))

    def test_start_does_not_clear_stop(self):
        fleet.request_stop(self.root, "stop")
        marker = (self.root / "STOP").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "explicitly Resume"):
            fleet.prepare(self.root)
        self.assertEqual((self.root / "STOP").read_bytes(), marker)

    def test_resume_preserves_sessions_and_clears_old_stop_and_drain(self):
        self.state["sessions"] = {"worker0": "same-session"}
        fleet.write(self.root / "state.json", self.state)
        for name in ("stop", "drain"):
            fleet.request_stop(self.root, name)
        result = fleet.prepare(self.root, resume=True)
        self.assertEqual(result["sessions"], self.state["sessions"])
        self.assertFalse((self.root / "STOP").exists())
        self.assertFalse((self.root / "DRAIN").exists())

    def test_new_stop_during_resume_is_not_erased(self):
        fleet.request_stop(self.root, "stop")
        with patch.object(fleet, "recover_integration", side_effect=lambda *args: fleet.request_stop(self.root, "stop")):
            with self.assertRaisesRegex(RuntimeError, "request changed"):
                fleet.prepare(self.root, resume=True)
        self.assertTrue((self.root / "STOP").exists())

    def test_existing_lock_blocks_recovery(self):
        with GlobalLock(self.locks), self.assertRaises(LockUnavailable):
            fleet.prepare(self.root, resume=True)
        fleet.recover_integration.assert_not_called()

    def test_orphan_check_precedes_receipt_recovery(self):
        with patch.object(fleet, "check_existing_sessions", side_effect=RuntimeError("existing Devin")), \
                patch.object(fleet, "recover_finished") as recovery, self.assertRaisesRegex(RuntimeError, "existing Devin"):
            fleet.prepare(self.root, resume=True)
        recovery.assert_not_called()

    def test_hold_receipt_survives_state_backup_recovery(self):
        fleet.write(self.root / "holds/worker0.json", {"active": True, "reason": "review required"})
        (self.root / "state.json").write_text("{broken", encoding="utf-8")
        state = fleet.prepare(self.root, resume=True)
        self.assertTrue(state["blocked_roles"]["worker0"]["active"])
        self.assertTrue(list(self.root.glob("state.json.corrupt-*")))

    def test_manual_retry_is_durable_but_does_not_modify_permissions(self):
        fleet.write(self.root / "holds/worker0.json", {"active": True, "reason": "review required"})
        settings_before = (self.root / "settings.json").read_bytes()
        fleet.prepare(self.root, resume=True, retry_role="worker0")
        # Simulate restoring older state that still claims the role is blocked.
        state = copy.deepcopy(self.state)
        state["blocked_roles"] = {"worker0": {"active": True}}
        fleet.recover_holds(self.root, state)
        self.assertNotIn("worker0", state["blocked_roles"])
        self.assertEqual((self.root / "settings.json").read_bytes(), settings_before)
        hold = fleet.read(self.root / "holds/worker0.json")
        self.assertFalse(hold["permission_granted"])
        self.assertFalse(hold["active"])

    def test_retry_requires_resume_and_known_role(self):
        with self.assertRaisesRegex(RuntimeError, "explicit resume"):
            fleet.prepare(self.root, retry_role="worker0")
        with self.assertRaisesRegex(RuntimeError, "Unknown retry"):
            fleet.prepare(self.root, resume=True, retry_role="outside")

    def test_coordinator_hold_prevents_resume_and_retains_stop(self):
        fleet.request_stop(self.root, "stop")
        fleet.write(self.root / "holds/coordinator.json", {"active": True})
        with self.assertRaisesRegex(RuntimeError, "Coordinator is held"):
            fleet.prepare(self.root, resume=True)
        self.assertTrue((self.root / "STOP").exists())

    def test_status_never_repairs_corrupt_state(self):
        (self.root / "state.json").write_text("{broken", encoding="utf-8")
        with patch.object(fleet, "global_lock_held", return_value=True):
            status = fleet.status_snapshot(self.root)
        self.assertTrue(status["runner_lock_held"])
        self.assertIn("state_error", status)
        self.assertEqual((self.root / "state.json").read_text(encoding="utf-8"), "{broken")
        self.assertFalse(list(self.root.glob("state.json.corrupt-*")))

    def test_direct_run_with_stop_never_applies_journal_or_launches(self):
        fleet.request_stop(self.root, "stop")
        with patch.object(fleet, "lane") as lane:
            fleet.loop(self.root, 1)
        lane.assert_not_called()
        fleet.recover_integration.assert_not_called()

    def test_held_worker_is_skipped_and_other_roles_continue(self):
        fleet.write(self.root / "holds/worker0.json", {"active": True})
        called = []
        def lane(root, role, *args):
            called.append(role)
            return {"summary": "bounded checkpoint"}, {}
        with patch.object(fleet, "lane", side_effect=lane), patch.object(fleet, "catalog_check"), \
                patch.object(fleet, "integrate"), patch.object(fleet, "sha", return_value="a" * 40), \
                patch.object(fleet.time, "sleep"):
            fleet.loop(self.root, 1)
        self.assertEqual(set(called), set(self.roles) - {"worker0"})
        state = fleet.load_state(self.root)
        self.assertEqual(state["status"], "checkpoint")
        self.assertIn("worker0", state["blocked_roles"])


if __name__ == "__main__":
    unittest.main()
