"""Versioned 38-opcode parity contract for Python and static-browser ASM."""

import json
from math import isclose
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emulator import EPUEmulator
from epu import EPUError
from epu_spec import INSTRUCTIONS


CORPUS_PATH = ROOT / "tests" / "data" / "asm38_cross_runtime_corpus.json"
RUNNER_PATH = ROOT / "scripts" / "static_asm38_parity_runner.cjs"
THERMAL_KEYS = {
    "temperature",
    "noise",
    "health",
    "max_temperature",
    "mean_temperature",
    "total_thermal_load",
    "register_max",
    "field_max",
    "min_health",
    "max_noise",
}


@unittest.skipUnless(shutil.which("node"), "Node.js is required for static ASM parity")
class StaticAsm38ParityTests(unittest.TestCase):
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
        decoded = json.loads(completed.stdout)
        cls.js_public_opcodes = decoded["public_opcodes"]
        cls.js_results = {item["name"]: item for item in decoded["results"]}
        cls.thermal_abs_tol = float(cls.corpus["thermal_abs_tol"])
        cls.real_abs_tol = float(cls.corpus["real_abs_tol"])

    def test_versioned_corpus_covers_public_38_opcode_contract_exactly(self) -> None:
        expected = sorted(item.opcode for item in INSTRUCTIONS)
        corpus = sorted(item["opcode"] for item in self.corpus["success"])
        self.assertEqual(self.corpus["schema_version"], 1)
        self.assertEqual(len(expected), 38)
        self.assertEqual(corpus, expected)
        self.assertEqual(self.js_public_opcodes, expected)

    def test_success_cases_match_discrete_state_output_and_control_flow(self) -> None:
        for case in self.corpus["success"]:
            with self.subTest(case=case["name"]):
                emulator = EPUEmulator(max_steps=case.get("max_steps", 10_000))
                result = emulator.run(case["source"])
                expected_snapshot = emulator.epu.visual_snapshot()
                actual = self.js_results[case["name"]]

                self.assertTrue(actual["ok"], actual)
                self.assertEqual(actual["halted"], result.halted)
                self.assertEqual(actual["steps"], result.steps)
                self.assertEqual(actual["pc"], result.pc)
                self.assertEqual(
                    actual["operations"],
                    [event["op"] for event in emulator.epu.timeline()],
                )
                self._assert_output(actual["output"], result.output)
                self._assert_snapshot(actual["snapshot"], expected_snapshot)

    def test_error_cases_match_python_code_and_message_exactly(self) -> None:
        for case in self.corpus["errors"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(EPUError) as captured:
                    EPUEmulator(max_steps=case.get("max_steps", 10_000)).run(
                        case["source"]
                    )
                actual = self.js_results[case["name"]]
                self.assertFalse(actual["ok"], actual)
                self.assertEqual(actual["error_name"], "EPUError")
                self.assertEqual(actual["error_code"], case["code"])
                self.assertEqual(actual["error"], str(captured.exception))

    def _assert_output(self, actual: object, expected: object, key: str = "") -> None:
        if isinstance(expected, dict):
            self.assertIsInstance(actual, dict)
            self.assertEqual(list(actual), list(expected))
            for child_key, child_value in expected.items():
                self._assert_output(actual[child_key], child_value, child_key)
            return
        if isinstance(expected, list):
            self.assertEqual(actual, expected)
            return
        if isinstance(expected, float) and key in THERMAL_KEYS:
            self.assertTrue(
                isclose(actual, expected, rel_tol=0.0, abs_tol=self.thermal_abs_tol),
                (key, actual, expected),
            )
            return
        self.assertEqual(actual, expected)

    def _assert_snapshot(self, actual: dict, expected: dict) -> None:
        self.assertEqual(actual["tick"], expected["tick"])
        self.assertEqual(actual["sr"], expected["sr"])
        self.assertEqual(actual["tr"], expected["tr"])
        self.assertEqual(actual["ep"], expected["ep"])
        self._assert_output(actual["temp"], expected["temp"])
        self._assert_output(actual["output"], expected["output"])

        exact_register_keys = (
            "mode",
            "min_partition",
            "current_partition",
            "allow_degrade",
            "guard_band",
            "q_max",
            "quantized_state",
            "partition",
            "last_refresh",
        )
        self.assertEqual(list(actual["er"]), list(expected["er"]))
        for name, expected_value in expected["er"].items():
            actual_value = actual["er"][name]
            for key in exact_register_keys:
                self.assertEqual(actual_value[key], expected_value[key], (name, key))
            self.assertTrue(
                isclose(
                    actual_value["real"],
                    expected_value["real"],
                    rel_tol=0.0,
                    abs_tol=self.real_abs_tol,
                ),
                (name, actual_value["real"], expected_value["real"]),
            )
            for key in ("temperature", "noise", "health"):
                self.assertTrue(
                    isclose(
                        actual_value[key],
                        expected_value[key],
                        rel_tol=0.0,
                        abs_tol=self.thermal_abs_tol,
                    ),
                    (name, key, actual_value[key], expected_value[key]),
                )

        exact_field_keys = (
            "bank_id",
            "offset",
            "length",
            "owner",
            "permissions",
            "mode",
            "exponent_offset",
            "sign",
            "min_partition",
            "current_partition",
            "allow_degrade",
            "q_max",
            "quantized_state",
            "partition",
            "refresh_deadline",
            "last_refresh",
            "refresh_due",
        )
        self.assertEqual(list(actual["fields"]), list(expected["fields"]))
        for name, expected_value in expected["fields"].items():
            actual_value = actual["fields"][name]
            for key in exact_field_keys:
                self.assertEqual(actual_value[key], expected_value[key], (name, key))
            for key in ("guard_band", "temperature", "noise", "health"):
                self.assertTrue(
                    isclose(
                        actual_value[key],
                        expected_value[key],
                        rel_tol=0.0,
                        abs_tol=self.thermal_abs_tol,
                    ),
                    (name, key, actual_value[key], expected_value[key]),
                )
            self.assertEqual(len(actual_value["cells"]), len(expected_value["cells"]))
            for actual_cell, expected_cell in zip(
                actual_value["cells"], expected_value["cells"]
            ):
                self.assertEqual(actual_cell["index"], expected_cell["index"])
                for key in ("value", "temperature", "noise", "health"):
                    tolerance = (
                        self.real_abs_tol if key == "value" else self.thermal_abs_tol
                    )
                    self.assertTrue(
                        isclose(
                            actual_cell[key],
                            expected_cell[key],
                            rel_tol=0.0,
                            abs_tol=tolerance,
                        ),
                        (name, key, actual_cell[key], expected_cell[key]),
                    )


if __name__ == "__main__":
    unittest.main()
