import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import prepared_trial_project as trial


@unittest.skipUnless(shutil.which("git"), "Git required")
class PreparedTrialProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artifact = self.root / "production-candidate-trial-project-v1"
        replacements = (("ROOT", self.root), ("ARTIFACT", self.artifact),
                        ("PROJECT", self.artifact / "project"),
                        ("BUNDLE", self.artifact / "parent.bundle"),
                        ("MANIFEST", self.artifact / "manifest.json"))
        for name, value in replacements:
            context = patch.object(trial, name, value)
            context.start()
            self.addCleanup(context.stop)
        for name, value in (("require_managed_namespace", None), ("global_lock_held", True)):
            context = patch.object(trial, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)

    def test_prepare_and_independent_inspect(self):
        result = trial.prepare()
        self.assertTrue(result["verified"])
        self.assertFalse(result["production_admitted"])
        self.assertEqual(result, trial.inspect())
        self.assertEqual(set(os.listdir(self.artifact)), {"project", "parent.bundle", "manifest.json"})
        manifest = json.loads((self.artifact / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["task_request"], trial.TASK_REQUEST)
        self.assertEqual(trial.TASK_REQUEST["entry"],
                         json.loads((self.artifact / "project" / "roles.json").read_text())["machine"])
        self.assertEqual(trial.TASK_REQUEST["entry"]["paths"], ["add.py"])
        self.assertEqual(trial.TASK_REQUEST["settings"]["turn_timeout_seconds"], 300)
        for key in ("round", "reports", "candidates", "missions", "sessions"):
            self.assertIn(key, trial.TASK_REQUEST["state"])
        with self.assertRaises(FileExistsError):
            trial.prepare()

    def test_project_content_extra_and_symlink_are_refused(self):
        trial.prepare()
        add = self.artifact / "project" / "add.py"
        add.write_text("def add(left, right): return left + right\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            trial.inspect()
        add.write_bytes(trial.FILES["add.py"])
        (self.artifact / "project" / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaises(ValueError):
            trial.inspect()
        (self.artifact / "project" / "extra.txt").unlink()
        try:
            (self.artifact / "link").symlink_to(self.artifact / "manifest.json")
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(ValueError):
            trial.inspect()

    def test_manifest_bundle_and_ref_changes_are_refused(self):
        trial.prepare()
        manifest = self.artifact / "manifest.json"
        original = manifest.read_bytes()
        value = json.loads(original)
        value["activated"] = True
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            trial.inspect()
        manifest.write_bytes(original)
        with (self.artifact / "parent.bundle").open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(ValueError):
            trial.inspect()

    def test_lock_required_before_reservation(self):
        with patch.object(trial, "global_lock_held", return_value=False):
            with self.assertRaises(ValueError):
                trial.prepare()
        self.assertFalse(self.artifact.exists())


if __name__ == "__main__":
    unittest.main()
