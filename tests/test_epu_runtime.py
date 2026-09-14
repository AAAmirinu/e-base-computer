import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu import FIELD_CAPABILITIES
from epu_runtime import EPURuntime, RunRequest, RuntimeRequestError


class EPURuntimeTests(unittest.TestCase):
    def test_cbase_request_returns_versioned_json_ready_result(self) -> None:
        result = EPURuntime().run(
            RunRequest(source="let x = 2 * 3; print(x);", language="c")
        )
        payload = result.to_dict()

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["language"], "cbase")
        self.assertEqual(payload["output"], {"OUT0": 6.0})
        self.assertIn("timeline", payload)
        self.assertIn("snapshot", payload)
        self.assertIn("score", payload)
        self.assertEqual(payload["analysis"]["schema_version"], 1)
        self.assertEqual(payload["analysis"]["event_count"], result.steps)
        self.assertEqual(payload["models"]["thermal"]["model_id"], "simple-v0")
        self.assertEqual(payload["models"]["aging"]["model_id"], "simple-v0")
        self.assertEqual(
            payload["controls"],
            {"auto_refresh": False, "observer_mode": "non_destructive"},
        )
        json.dumps(payload)

    def test_high_level_model_selection_is_canonical_and_executable(self) -> None:
        result = EPURuntime().run(
            RunRequest(
                "ECONST ER0, 2\nEMUL ER0, ER0, ER0\nETEMP DIAG",
                language="asm",
                thermal_model="coupled",
                aging_model="aging",
            )
        )

        self.assertEqual(result.models["thermal"]["model_id"], "coupled-v1")
        self.assertEqual(result.models["aging"]["model_id"], "aging-v1")
        self.assertEqual(result.snapshot["temp"]["thermal_model"], "coupled-v1")
        self.assertEqual(result.snapshot["temp"]["aging_model"], "aging-v1")
        self.assertGreater(result.snapshot["er"]["ER0"]["noise"], 0.0)
        self.assertLess(result.snapshot["er"]["ER0"]["health"], 1.0)
        self.assertEqual(result.output["DIAG"]["aging_model"], "aging-v1")

    def test_fresh_run_replaces_all_machine_state(self) -> None:
        runtime = EPURuntime()
        first = runtime.run(RunRequest("ECONST ER0, 2\nEPRINT ER0", language="asm"))
        second = runtime.run(RunRequest("ECONST ER0, 5\nEPRINT ER0", language="asm"))

        self.assertEqual(first.output, {"OUT0": 2.0})
        self.assertEqual(second.output, {"OUT0": 5.0})
        self.assertEqual(second.snapshot["tick"], 2)
        self.assertEqual(len(second.timeline), 2)

    def test_high_level_observation_and_maintenance_controls_execute(self) -> None:
        source = (
            "ECONST ER0, 3\n"
            + "\n".join(["ETRIT TR0, 0"] * 65)
            + "\nEOBS OUT0, ER0"
        )
        result = EPURuntime().run(
            RunRequest(
                source,
                language="asm",
                aging_model="aging-v1",
                observer_mode="destructive",
                auto_refresh=True,
            )
        )

        self.assertEqual(
            result.controls,
            {"auto_refresh": True, "observer_mode": "destructive"},
        )
        self.assertEqual(result.output, {"OUT0": 3.0})
        self.assertEqual(result.analysis["maintenance_counts"], {"auto_refresh": 16})
        self.assertEqual(result.analysis["refresh_events"], 16)
        self.assertEqual(result.snapshot["er"]["ER0"]["last_refresh"], 64)
        self.assertGreater(result.snapshot["er"]["ER0"]["noise"], 0.0)
        self.assertLess(result.snapshot["er"]["ER0"]["health"], 1.0)

    def test_session_continuation_explicitly_reuses_state(self) -> None:
        runtime = EPURuntime()
        runtime.run(RunRequest("ECONST ER0, 2\nEPRINT ER0", language="asm"))
        continued = runtime.run(
            RunRequest(
                "ECONST ER1, 3\nEADD ER2, ER0, ER1\nEPRINT ER2",
                language="asm",
                fresh=False,
            )
        )

        self.assertEqual(continued.output, {"OUT0": 2.0, "OUT1": 5.0})
        self.assertEqual(continued.snapshot["tick"], 5)
        self.assertEqual(len(continued.timeline), 5)

    def test_principal_and_capabilities_cross_runtime_boundary(self) -> None:
        runtime = EPURuntime()
        runtime.run(
            RunRequest(
                "ECONST ER0, 7.5\nEALLOC EP0, COLD, 4\nESTORE EP0, ER0",
                language="asm",
                principal="alice",
                capabilities=FIELD_CAPABILITIES,
            )
        )
        observed = runtime.run(
            RunRequest(
                "ELOAD ER1, EP0\nEOBS OUT0, ER1",
                language="asm",
                principal="bob",
                capabilities=frozenset({"read", "observe_continuous"}),
                fresh=False,
            )
        )

        self.assertEqual(observed.output["OUT0"], 7.5)
        self.assertEqual(observed.snapshot["context"]["principal"], "bob")

    def test_invalid_requests_fail_before_execution(self) -> None:
        invalid = (
            {"source": "", "language": "python"},
            {"source": "", "max_steps": 0},
            {"source": "", "precision": 16},
            {"source": "", "capabilities": ["superuser"]},
            {"source": "", "fresh": "false"},
            {"source": "", "schema_version": 2},
            {"source": "", "thermal_model": "future"},
            {"source": "", "aging_model": "random-v9"},
            {"source": "", "aging_model": 1},
            {"source": "", "auto_refresh": "true"},
            {"source": "", "observer_mode": "passive"},
            {"source": "", "observer_mode": 1},
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(RuntimeRequestError):
                RunRequest.from_dict(payload)

        with self.assertRaises(RuntimeRequestError):
            EPURuntime().run(RunRequest("EHALT", language="asm", fresh=False))


if __name__ == "__main__":
    unittest.main()
