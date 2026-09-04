from dataclasses import dataclass
from pathlib import Path
import math
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emulator import EPUEmulator
from epu import EPU, EPUError
from epu_diagnostics import TRegisterValue, compare_trit, temperature_report


@dataclass
class Node:
    temperature: float = 0.0
    noise: float = 0.0
    health: float = 1.0
    last_refresh: int = 0
    length: int = 1
    refresh_deadline: int = 64


class DiagnosticValueTests(unittest.TestCase):
    def test_trit_lanes_are_strict_and_bounded(self) -> None:
        self.assertEqual(TRegisterValue((-1, 0, 1)).scalar, -1)
        for lanes in [(), (2,), (True,), tuple(0 for _ in range(28))]:
            with self.subTest(lanes=lanes):
                with self.assertRaises(ValueError):
                    TRegisterValue(lanes)

    def test_compare_trit_pins_epsilon_boundary(self) -> None:
        epsilon = 1e-6
        self.assertEqual(compare_trit(1.0, 1.0 + epsilon, epsilon).scalar, 0)
        self.assertEqual(compare_trit(1.0, 1.0 + epsilon * 2, epsilon).scalar, -1)
        self.assertEqual(compare_trit(1.0 + epsilon * 2, 1.0, epsilon).scalar, 1)
        for invalid in [-1.0, math.inf, math.nan]:
            with self.assertRaises(ValueError):
                compare_trit(0.0, 0.0, invalid)

    def test_temp_is_mass_weighted_and_deterministic(self) -> None:
        report = temperature_report(
            er={"ER0": Node(temperature=1.0), "ER1": Node(temperature=0.0)},
            fields={"F0": Node(temperature=0.5, length=4)},
            tick=64,
            thermal_model="coupled-v1",
            aging_model="aging-v1",
        )
        self.assertAlmostEqual(report.total_thermal_load, 3.0)
        self.assertAlmostEqual(report.mean_temperature, 0.5)
        self.assertEqual(report.max_temperature, 1.0)
        self.assertEqual(report.hottest_target, "ER0")
        self.assertEqual(report.refresh_due_count, 3)


class ExecutableDiagnosticLayerTests(unittest.TestCase):
    def test_trit_compare_and_select_preserve_register_metadata(self) -> None:
        epu = EPU()
        result = EPUEmulator(epu=epu).run(
            """
            ECONST ER0, 2
            ECONST ER1, 3
            ECONST ER2, -10
            ECONST ER3, 0
            ECONST ER4, 10
            ETCMP TR0, ER0, ER1
            ETSEL ER5, TR0, ER2, ER3, ER4
            EOBS OUT0, ER5
            """
        )
        self.assertEqual(epu.tr["TR0"].lanes, (-1,))
        self.assertEqual(result.output["OUT0"], -10.0)
        self.assertEqual(epu.er["ER5"].word.to_real(), epu.er["ER2"].word.to_real())
        self.assertEqual(epu.er["ER5"].health, epu.er["ER2"].health)

    def test_explicit_trit_vector_and_temp_output_are_in_snapshot(self) -> None:
        epu = EPU()
        result = EPUEmulator(epu=epu).run(
            "ETRIT TR7, -1, 0, 1\nECONST ER0, 2\nETEMP DIAG"
        )
        snapshot = epu.visual_snapshot()
        self.assertEqual(snapshot["tr"]["TR7"]["lanes"], [-1, 0, 1])
        self.assertEqual(snapshot["temp"]["tick"], 3)
        self.assertEqual(result.output["DIAG"]["tick"], 2)
        self.assertIn("max_temperature", result.output["DIAG"])

    def test_diagnostic_failures_are_atomic_and_audited(self) -> None:
        cases = [
            ("ETRIT TR0, 2", "BAD_OPERAND"),
            ("ETCMP TR0, ER0, ER1 ; epsilon=-1", "BAD_OPERAND"),
            ("ETSEL ER0, TR8, ER1, ER2, ER3", "BAD_OPERAND"),
            ("ETEMP OUT0, TEMP", "BAD_OPERAND"),
        ]
        for source, code in cases:
            with self.subTest(source=source):
                epu = EPU()
                before = epu.visual_snapshot()
                with self.assertRaises(EPUError) as captured:
                    EPUEmulator(epu=epu).run(source)
                self.assertEqual(captured.exception.code, code)
                self.assertEqual(epu.tick, 0)
                self.assertEqual(epu.visual_snapshot()["er"], before["er"])
                self.assertEqual(epu.event_log[-1]["exception"], code)


if __name__ == "__main__":
    unittest.main()
