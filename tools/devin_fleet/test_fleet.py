"""Driver policy regression tests; never launch Devin or generated guest code."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("fleet_under_test", Path(__file__).with_name("fleet.py"))
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


class OwnershipTests(unittest.TestCase):
    def test_worker_scope_and_checkpoint(self):
        self.assertTrue(fleet.allowed("src/guest_storage.py", ["src/guest_storage.py"]))
        self.assertTrue(fleet.allowed(".fleet/report.json", []))
        self.assertFalse(fleet.allowed("src/epu.py", ["src/guest_storage.py"]))

    def test_protected_roots_even_with_broad_pattern(self):
        for path in ("AGENTS.md", ".git", ".git/config", ".gitignore", ".devin/config.json"):
            with self.subTest(path=path):
                self.assertFalse(fleet.allowed(path, ["**"]))

    def test_checkpoint_path_cannot_escape_root(self):
        for path in (".fleet/../state.json", ".fleet/../../outside", ".fleet//../state.json"):
            with self.subTest(path=path):
                self.assertFalse(fleet.allowed(path, []))


class ModelTests(unittest.TestCase):
    def test_expected_agent_model(self):
        fleet.check_model({"steps": [{"source": "agent", "model_name": fleet.MODEL}]})

    def test_observed_high_display_label_accepted(self):
        fleet.check_model({"steps": [{"source": "agent", "model_name": "SWE-2 High"}]})

    def test_display_label_alias_does_not_broaden_model_matching(self):
        for model in ("", "swe-2-medium", "SWE-2 Medium", "swe-2-max", "SWE-2 Max",
                      "Other High", "SWE-2 HIGH", "swe-2 high", " SWE-2 High", "SWE-2 High "):
            with self.subTest(model=model), self.assertRaises(RuntimeError):
                fleet.check_model({"steps": [{"source": "agent", "model_name": model}]})

    def test_non_agent_steps_need_no_model(self):
        fleet.check_model({"steps": [{"source": "user"}, {"source": "agent", "model_name": fleet.MODEL}]})

    def test_no_agent_evidence_fails(self):
        for export in ({}, {"steps": []}, {"steps": [{"source": "user"}]}):
            with self.subTest(export=export), self.assertRaises(RuntimeError):
                fleet.check_model(export)

    def test_fallback_or_missing_model_fails(self):
        for model in (None, "swe-2", "other-model"):
            with self.subTest(model=model), self.assertRaises(RuntimeError):
                fleet.check_model({"steps": [{"source": "agent", "model_name": fleet.MODEL},
                                             {"source": "agent", "model_name": model}]})

    def test_free_catalog_required(self):
        for tier in ("Paid", None):
            catalog = {"families": [{"variants": [{"model_uid": fleet.MODEL, "cost_tier": tier}]}]}
            with self.subTest(tier=tier), patch.object(fleet, "run", return_value=json.dumps(catalog)), \
                    self.assertRaises(RuntimeError):
                fleet.catalog_check("unused")

    def test_free_catalog_accepted(self):
        catalog = {"families": [{"variants": [{"model_uid": fleet.MODEL, "cost_tier": "Free"}]}]}
        with patch.object(fleet, "run", return_value=json.dumps(catalog)):
            fleet.catalog_check("unused")


class ConcurrencyTests(unittest.TestCase):
    def test_existing_devin_blocks_ten_new_lanes(self):
        with patch.object(fleet.os, "name", "nt"), \
                patch.object(fleet, "run", return_value='"devin.exe","1234","Console","1","1 K"'), \
                self.assertRaises(RuntimeError):
            fleet.check_existing_sessions()

    def test_no_matching_process_allows_start(self):
        with patch.object(fleet.os, "name", "nt"), \
                patch.object(fleet, "run", return_value="INFO: No tasks are running which match the specified criteria."):
            fleet.check_existing_sessions()


class PermissionConfigurationTests(unittest.TestCase):
    def configs(self):
        roles = {"coordinator": {"paths": [".fleet/**"]},
                 "machine": {"paths": ["src/epu.py", "tests/test_epu.py"]}}
        with patch.object(fleet, "read", return_value=roles), patch.object(fleet, "write") as writer:
            fleet.configure(Path("fixture-fleet"))
        return {call.args[0].stem: call.args[1] for call in writer.call_args_list}

    def test_every_role_uses_swe_2_and_blocks_nested_agents(self):
        for role, config in self.configs().items():
            with self.subTest(role=role):
                self.assertEqual(config["agent"]["model"], "swe-2-high")
                self.assertIn("run_subagent", config["permissions"]["deny"])
                self.assertIn("request_scope", config["permissions"]["deny"])

    def test_exec_allowlist_has_only_named_read_commands(self):
        expected = {"Exec(ls)", "Exec(pwd)", "Exec(head)", "Exec(tail)", "Exec(cat)", "Exec(wc)",
                    "Exec(echo)", "Exec(diff)"}
        for role, config in self.configs().items():
            with self.subTest(role=role):
                allows = config["permissions"]["allow"]
                actual = {rule for rule in allows if rule.lower().startswith("exec")}
                self.assertEqual(actual, expected)
                self.assertNotIn("*", allows)
                self.assertNotIn("**", allows)
                self.assertNotIn("exec", config["permissions"]["deny"])

    def test_coordinator_cannot_write_worker_or_control_files(self):
        config = self.configs()["coordinator"]
        writes = {rule for rule in config["permissions"]["allow"] if rule.startswith("Write(")}
        self.assertEqual(writes, {"Write(fixture-fleet/lanes/coordinator/.fleet/**)"})
        self.assertIn("Write(**/.git/**)", config["permissions"]["deny"])
        self.assertIn("Write(**/.devin/**)", config["permissions"]["deny"])


class IntegrationTests(unittest.TestCase):
    def state(self):
        return {"round": 1, "candidates": {"a" * 40: {"role": "machine", "status": "pending"}}}

    def test_unknown_candidate_never_runs_commands(self):
        with patch.object(fleet, "run") as command, self.assertRaises(RuntimeError):
            fleet.integrate(Path("unused"), self.state(), {"approve": ["b" * 40]}, {})
        command.assert_not_called()

    def test_oversized_approval_never_runs_commands(self):
        with patch.object(fleet, "run") as command, self.assertRaises(RuntimeError):
            fleet.integrate(Path("unused"), self.state(), {"approve": ["a" * 40] * 10}, {})
        command.assert_not_called()

    def test_empty_decision_does_not_touch_integration(self):
        with patch.object(fleet, "run") as command, patch.object(fleet, "git") as git:
            fleet.integrate(Path("unused"), self.state(), {}, {})
        command.assert_not_called()
        git.assert_not_called()

    def assert_invalid_decision_is_atomic(self, state, decision):
        original = copy.deepcopy(state)
        with patch.object(fleet, "run") as command, patch.object(fleet, "git") as git:
            with self.assertRaises(RuntimeError):
                fleet.integrate(Path("unused"), state, decision, {})
        self.assertEqual(state, original)
        command.assert_not_called()
        git.assert_not_called()

    def test_reject_must_be_a_list_of_commit_strings(self):
        for rejected in (None, "a" * 40, {"commit": "a" * 40}, 1,
                         [None], [1], [{}], [["a" * 40]]):
            with self.subTest(rejected=rejected):
                self.assert_invalid_decision_is_atomic(self.state(), {"reject": rejected})

    def test_reject_unknown_candidate_is_atomic(self):
        self.assert_invalid_decision_is_atomic(self.state(), {"reject": ["b" * 40]})

    def test_reject_only_pending_candidates(self):
        for status in ("integrated", "rejected", "needs_rework"):
            state = self.state()
            state["candidates"]["a" * 40]["status"] = status
            with self.subTest(status=status):
                self.assert_invalid_decision_is_atomic(state, {"reject": ["a" * 40]})

    def test_candidate_cannot_be_approved_and_rejected(self):
        self.assert_invalid_decision_is_atomic(self.state(),
                                              {"approve": ["a" * 40], "reject": ["a" * 40]})

    def test_valid_rejection_is_not_applied_before_unknown_approval_validation(self):
        self.assert_invalid_decision_is_atomic(self.state(),
                                              {"reject": ["a" * 40], "approve": ["b" * 40]})

    def test_valid_rejection_is_not_applied_before_later_invalid_rejection(self):
        self.assert_invalid_decision_is_atomic(self.state(), {"reject": ["a" * 40, "b" * 40]})

    def test_duplicate_rejects_are_invalid_without_mutation(self):
        self.assert_invalid_decision_is_atomic(self.state(), {"reject": ["a" * 40, "a" * 40]})

    def test_pending_rejection_records_status_without_git_commands(self):
        state = self.state()
        with patch.object(fleet, "run") as command, patch.object(fleet, "git") as git:
            fleet.integrate(Path("unused"), state, {"reject": ["a" * 40]}, {})
        self.assertEqual(state["candidates"]["a" * 40]["status"], "rejected")
        command.assert_not_called()
        git.assert_not_called()

    def test_failed_gate_does_not_merge(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(fleet, "run", return_value=""), \
                    patch.object(fleet, "supervised_run", side_effect=RuntimeError("test regression")), \
                    patch.object(fleet, "git", return_value="") as git:
                fleet.integrate(root, state, {"approve": ["a" * 40]}, {"python": "unused"})
            self.assertEqual(state["candidates"]["a" * 40]["status"], "needs_rework")
            self.assertIn("test regression", state["integration_error"])
            self.assertFalse(any(call.args[0] == root / "integration" and "merge" in call.args
                                 for call in git.call_args_list))


class DurableGitWorkflowTests(unittest.TestCase):
    """Use real local Git repositories; no Devin process or remote network."""

    def configure_git(self, repo):
        fleet.git(repo, "config", "user.name", "Fleet Test")
        fleet.git(repo, "config", "user.email", "fleet-test@localhost")
        fleet.git(repo, "config", "commit.gpgsign", "false")

    def new_integration(self, root):
        repo = root / "integration"
        fleet.run(["git", "init", "-b", "fleet/integration", repo])
        self.configure_git(repo)
        (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
        fleet.git(repo, "add", "baseline.txt")
        fleet.git(repo, "commit", "-m", "test baseline")
        return repo

    def clone_lane(self, root, source, role):
        repo = root / "lanes" / role
        fleet.run(["git", "clone", "--no-hardlinks", source, repo])
        self.configure_git(repo)
        with (repo / ".git/info/exclude").open("a", encoding="utf-8") as exclude:
            exclude.write("\n.fleet/\n")
        return repo

    def commit_file(self, repo, filename, content, message):
        (repo / filename).write_text(content, encoding="utf-8")
        fleet.git(repo, "add", "--", filename)
        fleet.git(repo, "commit", "-m", message)
        return fleet.sha(repo)

    def test_pending_lane_receives_another_lanes_integrated_change(self):
        with tempfile.TemporaryDirectory(prefix="fleet-sync-test-") as directory:
            root = Path(directory)
            integration = self.new_integration(root)
            machine = self.clone_lane(root, integration, "machine")
            kernel = self.clone_lane(root, integration, "kernel")
            machine_candidate = self.commit_file(machine, "machine.txt", "machine candidate\n", "machine candidate")
            kernel_candidate = self.commit_file(kernel, "kernel.txt", "integrated kernel contract\n", "kernel candidate")
            fleet.git(integration, "fetch", str(kernel), kernel_candidate)
            fleet.git(integration, "merge", "--no-ff", "--no-edit", kernel_candidate)
            state = {"round": 2, "candidates": {
                machine_candidate: {"role": "machine", "status": "pending"},
                kernel_candidate: {"role": "kernel", "status": "integrated"}}}

            fleet.sync_lane(machine, "machine", state)

            self.assertEqual((machine / "kernel.txt").read_text(encoding="utf-8"), "integrated kernel contract\n")
            self.assertEqual((machine / "machine.txt").read_text(encoding="utf-8"), "machine candidate\n")
            fleet.git(machine, "merge-base", "--is-ancestor", machine_candidate, "HEAD")
            fleet.git(machine, "merge-base", "--is-ancestor", kernel_candidate, "HEAD")
            self.assertEqual(fleet.git(machine, "status", "--porcelain"), "")
            self.assertEqual(state["candidates"][machine_candidate]["status"], "pending")

    def prepare_committed_receipt(self, root):
        integration = self.new_integration(root)
        repo = self.clone_lane(root, integration, "machine")
        base = fleet.sha(repo)
        (repo / "machine.txt").write_text("tested improvement\n", encoding="utf-8")
        fleet.git(repo, "add", "machine.txt")
        receipt = {"summary": "tested improvement", "base": base, "session": "test-session-1",
                   "changed": ["machine.txt"], "tests_passed": True, "model": fleet.MODEL,
                   "tree": fleet.git(repo, "write-tree")}
        rd = root / "runs" / "000001" / "machine"
        fleet.write(root / "roles.json", {"machine": {"paths": ["machine.txt"]}})
        fleet.write(rd / "prepared.json", receipt)
        fleet.write(rd / "session.json", {"session_id": "test-session-1",
                                           "steps": [{"source": "agent", "model_name": fleet.MODEL}]})
        fleet.git(repo, "commit", "-m", "fleet(machine): cycle 1")
        state = {"round": 1, "reports": {}, "sessions": {}, "candidates": {}}
        return repo, rd, receipt, state

    def test_crash_after_commit_recovers_prepared_receipt(self):
        with tempfile.TemporaryDirectory(prefix="fleet-recovery-test-") as directory:
            root = Path(directory)
            repo, rd, receipt, state = self.prepare_committed_receipt(root)
            commit = fleet.sha(repo)
            self.assertFalse((rd / "report.json").exists())

            fleet.recover_finished(root, state)

            self.assertEqual(state["candidates"][commit]["status"], "pending")
            self.assertEqual(state["candidates"][commit]["base"], receipt["base"])
            self.assertEqual(state["sessions"]["machine"], "test-session-1")
            self.assertEqual(state["reports"]["machine"]["commit"], commit)
            self.assertEqual(fleet.read(rd / "report.json")["commit"], commit)
            self.assertEqual(fleet.sha(repo), commit)
            self.assertEqual(fleet.git(repo, "status", "--porcelain"), "")

    def test_prepared_receipt_with_wrong_tree_is_not_recovered(self):
        with tempfile.TemporaryDirectory(prefix="fleet-invalid-recovery-test-") as directory:
            root = Path(directory)
            repo, rd, receipt, state = self.prepare_committed_receipt(root)
            receipt["tree"] = fleet.git(repo, "rev-parse", "HEAD^^{tree}")
            fleet.write(rd / "prepared.json", receipt)

            fleet.recover_finished(root, state)

            self.assertEqual(state["candidates"], {})
            self.assertEqual(state["reports"], {})
            self.assertEqual(state["sessions"], {})
            self.assertFalse((rd / "report.json").exists())

    def test_recorded_outcome_does_not_reopen_integrated_candidate(self):
        commit = "a" * 40
        candidate = {"role": "machine", "status": "integrated", "base": "b" * 40, "summary": "accepted"}
        state = {"reports": {}, "sessions": {}, "candidates": {commit: copy.deepcopy(candidate)}}
        report = {"commit": commit, "base": "b" * 40, "summary": "replayed receipt", "session": "same-session"}

        fleet.record_outcome(state, "machine", report)

        self.assertEqual(state["candidates"][commit], candidate)
        self.assertEqual(state["reports"]["machine"], report)
        self.assertEqual(state["sessions"]["machine"], "same-session")

    def rejected_chain(self, root, status):
        integration = self.new_integration(root)
        repo = self.clone_lane(root, integration, "machine")
        base = fleet.sha(repo)
        first = self.commit_file(repo, "machine.txt", "rejected behavior\n", "first candidate")
        second = self.commit_file(repo, "dependent.txt", "depends on rejected behavior\n", "second candidate")
        baseline = self.commit_file(integration, "kernel.txt", "new integration contract\n", "other role integration")
        state = {"round": 3, "integration_error": "gate exposed invalid arithmetic", "candidates": {
            first: {"role": "machine", "status": status, "base": base, "summary": "bad arithmetic"},
            second: {"role": "machine", "status": "pending", "base": first, "summary": "dependent candidate"}}}
        return repo, first, second, baseline, state

    def test_rejected_chain_is_archived_and_not_reapplied(self):
        for status in ("rejected", "needs_rework"):
            with self.subTest(status=status), tempfile.TemporaryDirectory(prefix="fleet-rework-test-") as directory:
                root = Path(directory)
                repo, first, second, baseline, state = self.rejected_chain(root, status)
                previous_state = copy.deepcopy(state)
                old_branch = fleet.git(repo, "branch", "--show-current")

                superseded = fleet.sync_lane(repo, "machine", state)

                self.assertEqual(superseded, [second])
                self.assertEqual(state, previous_state, "lane must not mutate the shared round snapshot")
                self.assertEqual(fleet.sha(repo), baseline)
                self.assertFalse((repo / "machine.txt").exists())
                self.assertFalse((repo / "dependent.txt").exists())
                self.assertEqual((repo / "kernel.txt").read_text(encoding="utf-8"), "new integration contract\n")
                self.assertEqual(fleet.git(repo, "rev-parse", old_branch), second)
                receipt = fleet.read(repo / ".fleet/rework/current.json")
                self.assertEqual(receipt["status"], "ready")
                self.assertEqual(receipt["rejected_ancestors"], [first])
                self.assertEqual(receipt["reason"], "gate exposed invalid arithmetic")
                self.assertEqual(fleet.git(repo, "rev-parse", receipt["archive_branch"]), second)
                self.assertEqual(fleet.git(repo, "branch", "--show-current"), receipt["new_branch"])
                archive = Path(receipt["archive_directory"])
                patch = (archive / "candidate-series.patch").read_text(encoding="utf-8")
                self.assertIn("rejected behavior", patch)
                self.assertIn("depends on rejected behavior", patch)
                self.assertTrue((archive / (first + ".patch")).is_file())
                self.assertTrue((archive / (second + ".patch")).is_file())
                self.assertEqual(fleet.git(repo, "status", "--porcelain"), "")
                authoritative = fleet.read(root / "rework/machine/current.json")
                self.assertEqual(authoritative["superseded"], [second])
                # Agent-authored checkpoint changes cannot forge the outer driver's receipt.
                receipt["superseded"] = []
                receipt["archive_branch"] = "model-authored-invalid-reference"
                fleet.write(repo / ".fleet/rework/current.json", receipt)
                # A crash before record_outcome must not lose superseded notifications.
                self.assertEqual(fleet.sync_lane(repo, "machine", state), [second])
                self.assertEqual(state, previous_state)
                self.assertEqual(fleet.sha(repo), baseline)

    def test_rejected_chain_with_dirty_work_is_preserved_and_paused(self):
        with tempfile.TemporaryDirectory(prefix="fleet-dirty-rework-test-") as directory:
            root = Path(directory)
            repo, first, second, baseline, state = self.rejected_chain(root, "needs_rework")
            (repo / "machine.txt").write_text("unfinished correction\n", encoding="utf-8")
            fleet.git(repo, "add", "machine.txt")
            (repo / "untracked.txt").write_text("important unsaved experiment\n", encoding="utf-8")
            before_status = fleet.git(repo, "status", "--porcelain")
            previous_state = copy.deepcopy(state)

            with self.assertRaisesRegex(RuntimeError, "dirty work"):
                fleet.sync_lane(repo, "machine", state)

            self.assertEqual(fleet.sha(repo), second)
            self.assertEqual(fleet.git(repo, "status", "--porcelain"), before_status)
            self.assertEqual((repo / "machine.txt").read_text(encoding="utf-8"), "unfinished correction\n")
            self.assertEqual((repo / "untracked.txt").read_text(encoding="utf-8"), "important unsaved experiment\n")
            self.assertEqual(state, previous_state)
            self.assertFalse((repo / ".fleet/rework").exists())


class InterruptedCheckpointTests(unittest.TestCase):
    def test_failed_turn_retains_test_evidence(self):
        state = {"reports": {}, "sessions": {}, "candidates": {}}
        receipt = {"summary": "repair required", "tests_passed": False,
                   "test_output_tail": "three helper errors", "session": "same-session"}
        fleet.record_outcome(state, "storage", receipt)
        fleet.record_outcome(state, "storage", {"summary": "lane failed", "error": "STOP"})
        self.assertEqual(state["checkpoints"]["storage"], receipt)
        self.assertFalse(state["reports"]["storage"]["tests_passed"])
        self.assertEqual(state["reports"]["storage"]["test_output_tail"], "three helper errors")
        self.assertEqual(state["reports"]["storage"]["error"], "STOP")

    def test_interrupted_round_recovers_prior_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fleet.write(root / "roles.json", {"storage": {"paths": []}})
            receipt = {"summary": "repair required", "tests_passed": False, "session": "same-session"}
            fleet.write(root / "runs/000001/storage/report.json", receipt)
            fleet.write(root / "runs/000001/storage/session.json", {
                "steps": [{"source": "agent", "model_name": fleet.MODEL}]})
            state = {"round": 2, "reports": {}, "sessions": {}, "candidates": {}}
            fleet.recover_finished(root, state)
            self.assertEqual(state["checkpoints"]["storage"], receipt)
            self.assertEqual(state["sessions"]["storage"], "same-session")


class PermissionRecoveryTests(unittest.TestCase):
    """Mock CLI boundaries, but exercise real prompt/export/report file handling."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fleet-permission-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "lanes" / "machine"
        self.repo.mkdir(parents=True)
        self.entry = {"paths": ["src/epu.py"], "title": "Machine", "mission": "Improve core",
                      "first_task": "Inspect arithmetic"}
        fleet.write(self.root / "roles.json", {"machine": self.entry})
        (self.root / "CHARTER.md").write_text("Use fixed scopes.\n", encoding="utf-8")
        fleet.configure(self.root)
        self.config = self.root / "configs" / "machine.json"
        self.config_before = self.config.read_bytes()
        self.state = {"round": 1, "reports": {}, "sessions": {}, "candidates": {}}
        self.settings = {"executable": "never-launch-devin", "python": "never-launch-python",
                         "turn_timeout_seconds": 30}
        self.calls = []

    def denied(self, model="swe-2-high"):
        return {"model": model, "exit": 1, "observation": "Tool request rejected by fixed policy"}

    def execute(self, attempts):
        def fake_popen(args, **kwargs):
            index = len(self.calls)
            self.calls.append(list(args))
            self.assertLess(index, len(attempts), "driver exceeded expected CLI attempt count")
            result = attempts[index]
            export = {"session_id": result.get("session_id", "persistent-session"), "steps": [{"source": "agent",
                      "model_name": result.get("model", fleet.MODEL),
                      "observation": result.get("observation", {})}]}
            if not result.get("omit_export"):
                fleet.write(args[args.index("--export") + 1], export)
            if result.get("report"):
                fleet.write(self.repo / ".fleet" / "report.json", result["report"])
            code = result.get("exit", 0)
            return SimpleNamespace(pid=9000 + index, returncode=code, poll=lambda: code)

        with patch.object(fleet, "sync_lane", return_value=[]), patch.object(fleet, "git", return_value="src/epu.py"), \
                patch.object(fleet, "sha", return_value="a" * 40), patch.object(fleet, "changes", return_value=[]), \
                patch.object(fleet.subprocess, "Popen", side_effect=fake_popen), \
                patch.object(fleet.subprocess, "run", side_effect=AssertionError("Unexpected subprocess execution")):
            return fleet.lane(self.root, "machine", self.entry, self.state, self.settings, self.root / "STOP")

    def assert_fixed_scopes_and_session(self):
        for index, args in enumerate(self.calls):
            self.assertEqual(args[args.index("--model") + 1], "swe-2-high")
            self.assertEqual(args[args.index("--config") + 1], str(self.config))
            self.assertEqual(args[args.index("--permission-mode") + 1], "normal")
            if index:
                self.assertEqual(args.count("--resume"), 1)
                self.assertEqual(args[args.index("--resume") + 1], "persistent-session")
                recovery_prompt = Path(args[args.index("--prompt-file") + 1]).read_text(encoding="utf-8")
                self.assertIn("Do not retry that action or seek broader permissions", recovery_prompt)
        self.assertEqual(self.config.read_bytes(), self.config_before)

    def test_denial_resumes_same_session_and_preserves_permissions(self):
        report, decision = self.execute([self.denied(), {"report": {"summary": "Reviewed core", "status": "reviewed"}}])
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("--resume", self.calls[0])
        self.assertEqual(report["session"], "persistent-session")
        self.assertEqual(report["summary"], "Reviewed core")
        self.assertEqual(decision, {})
        self.assert_fixed_scopes_and_session()

    def test_existing_session_is_not_duplicated_in_retry_arguments(self):
        self.state["sessions"]["machine"] = "persistent-session"
        self.execute([self.denied(), {"report": {"summary": "Done"}}])
        self.assertEqual(self.calls[0].count("--resume"), 1)
        self.assertEqual(self.calls[0][self.calls[0].index("--resume") + 1], "persistent-session")
        self.assert_fixed_scopes_and_session()

    def test_repeated_denial_stops_after_three_total_attempts(self):
        with self.assertRaises(fleet.PermissionBlocked):
            self.execute([self.denied(), self.denied(), self.denied()])
        self.assertEqual(len(self.calls), 3)
        self.assert_fixed_scopes_and_session()
        hold = fleet.read(self.root / "holds/machine.json")
        self.assertTrue(hold["active"])
        request = fleet.read(self.root / "runs/000001/machine/permission-request-3.json")
        self.assertFalse(request["approved"])

    def test_wrong_model_stops_without_permission_retry(self):
        with self.assertRaisesRegex(RuntimeError, "non-SWE-2"):
            self.execute([self.denied(model="other-model")])
        self.assertEqual(len(self.calls), 1)
        self.assert_fixed_scopes_and_session()

    def test_wrong_model_during_resume_stops_immediately(self):
        with self.assertRaisesRegex(RuntimeError, "non-SWE-2"):
            self.execute([self.denied(), self.denied(model="other-model")])
        self.assertEqual(len(self.calls), 2)
        self.assert_fixed_scopes_and_session()

    def test_unrelated_failure_is_not_retried(self):
        with self.assertRaises(RuntimeError):
            self.execute([{"exit": 1, "observation": "Unexpected runtime failure"}])
        self.assertEqual(len(self.calls), 1)
        self.assert_fixed_scopes_and_session()

    def test_missing_retry_export_cannot_reuse_prior_model_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "Missing or non-SWE-2"):
            self.execute([self.denied(), {"omit_export": True, "report": {"summary": "unverified result"}}])
        self.assertEqual(len(self.calls), 2)
        exports = [Path(args[args.index("--export") + 1]) for args in self.calls]
        self.assertNotEqual(exports[0], exports[1])
        self.assertTrue(exports[0].is_file())
        self.assertFalse(exports[1].exists())
        self.assertFalse((self.root / "runs" / "000001" / "machine" / "report.json").exists())
        self.assert_fixed_scopes_and_session()

    def test_retry_returning_different_session_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "changed session identity"):
            self.execute([self.denied(), {"session_id": "different-session", "report": {"summary": "wrong session"}}])
        self.assertEqual(len(self.calls), 2)
        saved = fleet.read(self.root / "runs" / "000001" / "machine" / "session.json")
        self.assertEqual(saved["session_id"], "persistent-session")
        self.assertFalse((self.root / "runs" / "000001" / "machine" / "report.json").exists())
        self.assert_fixed_scopes_and_session()


if __name__ == "__main__":
    unittest.main()
