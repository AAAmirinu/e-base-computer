from pathlib import Path
import json
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu_runtime import EPURuntime, RunRequest
from web_playground import run_payload


CORPUS_PATH = ROOT / "conformance" / "runtime-v1.json"


def assert_projected_result(test: unittest.TestCase, payload: dict, expected: dict, tolerance: float) -> None:
    test.assertEqual(payload["steps"], expected["steps"])
    test.assertEqual(payload["halted"], expected["halted"])
    test.assertEqual(payload["snapshot"]["tick"], expected["steps"])
    test.assertEqual([event["op"] for event in payload["timeline"]], expected["ops"])
    test.assertEqual([event["tick"] for event in payload["timeline"]], expected["ticks"])
    flags = [sorted(set(event["flags"]) - {"OK"}) for event in payload["timeline"]]
    test.assertEqual(flags, expected["flags"])
    assert_float_tree(test, payload["output"], expected["output"], tolerance)
    for name, register_expected in expected["registers"].items():
        assert_float_tree(test, payload["snapshot"]["er"][name], register_expected, tolerance)
    fields = payload["snapshot"]["fields"]
    test.assertEqual(set(fields), set(expected["fields"]))
    for name, field_expected in expected["fields"].items():
        field = fields[name]
        test.assertEqual({
            "bank_id": field["bank_id"],
            "length": len(field["cells"]),
            "current_partition": field["current_partition"],
        }, field_expected)


def assert_float_tree(test: unittest.TestCase, actual: object, expected: object, tolerance: float) -> None:
    if isinstance(expected, dict):
        test.assertIsInstance(actual, dict)
        for key, value in expected.items():
            test.assertIn(key, actual)
            assert_float_tree(test, actual[key], value, tolerance)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        test.assertIsInstance(actual, (int, float))
        test.assertTrue(math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance), f"{actual!r} != {expected!r}")
    else:
        test.assertEqual(actual, expected)


class CrossRuntimeCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))

    def test_corpus_version_matches_runtime(self) -> None:
        self.assertEqual(self.corpus["corpus_version"], 1)
        self.assertEqual(self.corpus["runtime_schema_version"], 1)

    def test_python_runtime_and_server_payload_match_corpus(self) -> None:
        tolerance = self.corpus["float_tolerance"]
        for case in self.corpus["cases"]:
            request = {"source": case["source"], "language": "asm", "schema_version": self.corpus["runtime_schema_version"]}
            with self.subTest(case=case["id"], runtime="python"):
                result = EPURuntime().run(RunRequest.from_dict(request)).to_dict()
                assert_projected_result(self, result, case["expected"], tolerance)
            with self.subTest(case=case["id"], runtime="server"):
                result, status = run_payload(request)
                self.assertEqual(status, 200)
                self.assertTrue(result["ok"])
                assert_projected_result(self, result, case["expected"], tolerance)


if __name__ == "__main__":
    unittest.main()
