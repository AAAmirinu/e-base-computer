"""Restart recovery against disposable real Git trees; no models or network."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fleet
from durable import write_integration_journal


class IntegrationRestartTests(unittest.TestCase):
    def configure_git(self, repo):
        fleet.git(repo, "config", "user.name", "Fleet Restart Test")
        fleet.git(repo, "config", "user.email", "fleet-restart@localhost")
        fleet.git(repo, "config", "commit.gpgsign", "false")

    def commit(self, repo, filename, content):
        (repo / filename).write_text(content, encoding="utf-8")
        fleet.git(repo, "add", "--", filename)
        fleet.git(repo, "commit", "-m", filename)
        return fleet.sha(repo)

    def fixture(self, root):
        integration = root / "integration"
        fleet.run(["git", "init", "-b", "fleet/integration", integration])
        self.configure_git(integration)
        before = self.commit(integration, "baseline.txt", "baseline\n")
        lane = root / "lanes" / "machine"
        fleet.run(["git", "clone", "--no-hardlinks", integration, lane])
        self.configure_git(lane)
        candidate = self.commit(lane, "machine.txt", "tested candidate\n")
        gate = root / "gates" / "2"
        fleet.run(["git", "clone", "--no-hardlinks", integration, gate])
        self.configure_git(gate)
        fleet.git(gate, "fetch", str(lane), candidate)
        fleet.git(gate, "merge", "--no-ff", "--no-edit", candidate)
        target = fleet.sha(gate)
        log = root / "gates" / "2-validation.log"
        log.write_text("fixture validation passed\n", encoding="utf-8")
        journal = root / "integration-journal.json"
        write_integration_journal(journal, before, target, [candidate], 2, log)
        state = {"round": 2, "status": "running", "reports": {}, "sessions": {},
                 "candidates": {candidate: {"role": "machine", "status": "pending", "base": before}}}
        fleet.write(root / "state.json", state)
        return integration, gate, before, target, candidate, state, log

    def test_validated_before_fast_forward_recovers_exact_tested_target(self):
        with tempfile.TemporaryDirectory(prefix="fleet-ff-restart-") as directory:
            root = Path(directory)
            integration, gate, before, target, candidate, state, log = self.fixture(root)

            fleet.recover_integration(root, state)

            self.assertEqual(fleet.sha(integration), target)
            self.assertEqual(state["candidates"][candidate]["status"], "integrated")
            self.assertEqual(state["integration_commit"], target)
            self.assertEqual(fleet.read(root / "integration-journal.json")["phase"], "complete")
            self.assertEqual(fleet.read(root / "state.json")["candidates"][candidate]["status"], "integrated")
            self.assertEqual(fleet.git(integration, "status", "--porcelain"), "")
            self.assertEqual((integration / "machine.txt").read_text(), "tested candidate\n")

    def test_fast_forward_finished_before_checkpoint_does_not_merge_twice(self):
        with tempfile.TemporaryDirectory(prefix="fleet-postff-restart-") as directory:
            root = Path(directory)
            integration, gate, before, target, candidate, state, log = self.fixture(root)
            fleet.git(integration, "fetch", str(gate), target)
            fleet.git(integration, "merge", "--ff-only", target)
            with patch.object(fleet, "git", wraps=fleet.git) as commands:
                fleet.recover_integration(root, state)
                fleet.recover_integration(root, state)
            merge_calls = [call for call in commands.call_args_list if len(call.args) > 1 and call.args[1] == "merge"]
            self.assertEqual(merge_calls, [])
            self.assertEqual(fleet.sha(integration), target)
            self.assertEqual(state["candidates"][candidate]["status"], "integrated")
            self.assertEqual(fleet.read(root / "integration-journal.json")["phase"], "complete")

    def test_dirty_gate_or_modified_validation_log_fails_closed(self):
        for corruption in ("dirty_gate", "validation_log"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory(prefix="fleet-evidence-restart-") as directory:
                root = Path(directory)
                integration, gate, before, target, candidate, state, log = self.fixture(root)
                previous = copy.deepcopy(state)
                saved = (root / "state.json").read_bytes()
                if corruption == "dirty_gate":
                    (gate / "machine.txt").write_text("untested edit\n", encoding="utf-8")
                else:
                    log.write_text("altered validation evidence\n", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    fleet.recover_integration(root, state)
                self.assertEqual(fleet.sha(integration), before)
                self.assertEqual(state, previous)
                self.assertEqual((root / "state.json").read_bytes(), saved)
                self.assertEqual(fleet.read(root / "integration-journal.json")["phase"], "validated")
                if corruption == "dirty_gate":
                    self.assertEqual((gate / "machine.txt").read_text(), "untested edit\n")

    def test_unknown_integration_head_is_preserved_and_requires_review(self):
        with tempfile.TemporaryDirectory(prefix="fleet-unknown-head-restart-") as directory:
            root = Path(directory)
            integration, gate, before, target, candidate, state, log = self.fixture(root)
            unknown = self.commit(integration, "manual.txt", "operator change\n")
            previous = copy.deepcopy(state)
            with self.assertRaisesRegex(RuntimeError, "HEAD disagrees"):
                fleet.recover_integration(root, state)
            self.assertEqual(fleet.sha(integration), unknown)
            self.assertEqual((integration / "manual.txt").read_text(), "operator change\n")
            self.assertEqual(state, previous)
            self.assertEqual(fleet.read(root / "integration-journal.json")["phase"], "validated")


class SessionRestartTests(unittest.TestCase):
    def test_latest_verified_export_recovers_session_without_erasing_prior_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="fleet-session-restart-") as directory:
            root = Path(directory)
            fleet.write(root / "roles.json", {"storage": {"paths": []}})
            old_receipt = {"summary": "repair these failures", "tests_passed": False,
                           "test_output_tail": "specific prior failure", "session": "old-session"}
            fleet.write(root / "runs/000001/storage/report.json", old_receipt)
            fleet.write(root / "runs/000001/storage/session.json", {
                "session_id": "old-session", "steps": [{"source": "agent", "model_name": fleet.MODEL}]})
            new_directory = root / "runs/000002/storage"
            fleet.write(new_directory / "attempt-1.json", {
                "session_id": "new-session", "steps": [{"source": "agent", "model_name": fleet.MODEL}]})
            # Newest attempts may be torn by reboot; never infer model or discard them.
            (new_directory / "attempt-2.json").write_bytes(b"")
            truncated = b'{"session_id":"unverified",'
            (new_directory / "attempt-3.json").write_bytes(truncated)
            state = {"round": 1, "status": "running", "reports": {}, "sessions": {}, "candidates": {}}

            fleet.recover_finished(root, state)

            self.assertEqual(state["round"], 2)
            self.assertEqual(state["sessions"]["storage"], "new-session")
            self.assertEqual(state["checkpoints"]["storage"], old_receipt)
            self.assertEqual(state["reports"]["storage"]["test_output_tail"], "specific prior failure")
            self.assertEqual((new_directory / "attempt-3.json").read_bytes(), truncated)
            self.assertFalse((new_directory / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
