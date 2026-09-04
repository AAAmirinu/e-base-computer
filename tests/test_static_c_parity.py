"""Cross-runtime corpus for Python and static-browser C-like compilation."""

import json
from math import isclose
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cstyle_compiler import CStyleCompileError, CStyleCompiler
from emulator import EPUEmulator
from epu_scoring import score_timeline


CORPUS_PATH = ROOT / "tests" / "data" / "cstyle_cross_runtime_corpus.json"
RUNNER_PATH = ROOT / "scripts" / "static_c_parity_runner.cjs"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for static C parity")
class StaticCParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        cases = cls.corpus["success"] + cls.corpus["errors"]
        completed = subprocess.run(
            ["node", str(RUNNER_PATH)],
            input=json.dumps({"cases": cases}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
            cwd=ROOT,
        )
        cls.js_results = {
            result["name"]: result for result in json.loads(completed.stdout)["results"]
        }

    def test_success_corpus_matches_assembly_symbols_execution_and_score(self) -> None:
        for case in self.corpus["success"]:
            with self.subTest(case=case["name"]):
                precision = case.get("precision", 8)
                max_steps = case.get("max_steps", 10_000)
                compiler = CStyleCompiler(precision=precision)
                compiled = compiler.compile(case["source"])
                emulator = EPUEmulator(max_steps=max_steps)
                result = emulator.run(compiled.assembly)
                score = score_timeline(emulator.epu.timeline()).to_dict()
                js = self.js_results[case["name"]]

                self.assertTrue(js["ok"], js)
                self.assertEqual(js["assembly"], compiled.assembly)
                self.assertEqual(js["symbols"], compiled.symbols)
                self.assertEqual(list(js["output"]), list(result.output))
                for name, expected in result.output.items():
                    self.assertTrue(isclose(js["output"][name], expected, abs_tol=1e-9))
                self.assertEqual(js["halted"], result.halted)
                self.assertEqual(js["steps"], result.steps)
                self.assertEqual(js["pc"], result.pc)
                self.assertEqual(
                    js["operations"], [event["op"] for event in emulator.epu.timeline()]
                )
                self.assertEqual(js["score"], score)

    def test_error_corpus_matches_python_diagnostic_exactly(self) -> None:
        for case in self.corpus["errors"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(CStyleCompileError) as captured:
                    CStyleCompiler(precision=case.get("precision", 8)).compile(case["source"])
                js = self.js_results[case["name"]]
                self.assertFalse(js["ok"], js)
                self.assertEqual(js["error_name"], "CStyleCompileError")
                self.assertEqual(js["error"], str(captured.exception))


if __name__ == "__main__":
    unittest.main()
