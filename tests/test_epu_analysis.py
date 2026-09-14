import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu_analysis import ANALYSIS_SCHEMA_VERSION, analyze_timeline
from epu_runtime import EPURuntime, RunRequest


class EPUAnalysisTests(unittest.TestCase):
    def test_runtime_exposes_deterministic_semantic_summary(self) -> None:
        result = EPURuntime().run(
            RunRequest(
                "ECONST ER0, 2\nEMUL ER0, ER0, ER0\nEPRINT ER0\nEHALT",
                language="asm",
                aging_model="aging-v1",
            )
        )
        analysis = result.analysis

        self.assertEqual(analysis["schema_version"], ANALYSIS_SCHEMA_VERSION)
        self.assertEqual(analysis["event_count"], 4)
        self.assertEqual(
            analysis["opcode_counts"],
            {"ECONST": 1, "EHALT": 1, "EMUL": 1, "EPRINT": 1},
        )
        self.assertEqual(analysis["group_counts"]["arithmetic"], 1)
        self.assertEqual(analysis["group_counts"]["control"], 2)
        self.assertEqual(analysis["observation_events"], 1)
        self.assertEqual(analysis["exception_events"], 0)
        self.assertEqual(analysis["model_counts"]["aging"], {"aging-v1": 4})
        self.assertTrue(analysis["tick_sequence_valid"])
        self.assertGreater(analysis["max_temperature"], 0.0)
        self.assertEqual(analysis["hottest_target"], "ER0")
        self.assertGreater(analysis["max_noise"], 0.0)
        self.assertLess(analysis["min_health"], 1.0)
        json.dumps(result.to_dict())

    def test_synthetic_error_and_maintenance_projection(self) -> None:
        timeline = [
            {
                "tick": 4,
                "op": "EJZ",
                "flags": ["DEGRADED"],
                "exception": "MODE_ERROR",
                "aging_model": "simple-v0",
                "maintenance": ["auto_refresh:ER0", "refresh_due:ER1"],
                "after": {
                    "temp": {
                        "thermal_model": "coupled-v1",
                        "refresh_due_count": 2,
                    },
                    "er": {
                        "ER0": {"temperature": 0.25, "noise": 0.1, "health": 0.8}
                    },
                    "fields": {},
                },
            },
            {"tick": 6, "op": "EHALT", "flags": [], "after": {}},
        ]

        result = analyze_timeline(timeline).to_dict()

        self.assertEqual(result["branch_events"], 1)
        self.assertEqual(result["refresh_events"], 1)
        self.assertEqual(result["maintenance_counts"], {"auto_refresh": 1, "refresh_due": 1})
        self.assertEqual(
            result["first_exception"],
            {"tick": 4, "op": "EJZ", "code": "MODE_ERROR"},
        )
        self.assertEqual(result["peak_refresh_due_count"], 2)
        self.assertFalse(result["tick_sequence_valid"])

    def test_continuation_analysis_covers_retained_session(self) -> None:
        runtime = EPURuntime()
        runtime.run(RunRequest("ECONST ER0, 1", language="asm"))
        result = runtime.run(
            RunRequest("EPRINT ER0", language="asm", fresh=False)
        )

        self.assertEqual(result.steps, 1)
        self.assertEqual(result.analysis["event_count"], 2)
        self.assertEqual(
            result.analysis["opcode_counts"], {"ECONST": 1, "EPRINT": 1}
        )

    def test_empty_timeline_has_neutral_json_ready_values(self) -> None:
        result = analyze_timeline([]).to_dict()

        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["opcode_counts"], {})
        self.assertEqual(result["max_temperature"], 0.0)
        self.assertEqual(result["min_health"], 1.0)
        self.assertIsNone(result["hottest_target"])
        self.assertTrue(result["tick_sequence_valid"])
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
