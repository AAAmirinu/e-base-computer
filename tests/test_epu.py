from math import e, isclose
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu import EPU, EPUError, parse_program


class EPUTests(unittest.TestCase):
    def test_arithmetic_program_observes_value(self) -> None:
        epu = EPU()

        output = epu.run(
            """
            ECONST ER0, 12.5
            ECONST ER1, 4.25
            EMUL ER2, ER0, ER1
            ENORM ER2
            ESHIFT ER3, ER2, 1
            EOBS OUT0, ER3 ; precision=8
            """
        )

        self.assertTrue(isclose(output["OUT0"], round(12.5 * 4.25 * e, 8)))

    def test_memory_round_trip(self) -> None:
        epu = EPU()

        output = epu.run(
            """
            ECONST ER0, 7.5
            EALLOC EP0, COLD, 4 ; mode=EWORD
            ESTORE EP0, ER0
            ELOAD ER1, EP0
            EOBS OUT0, ER1 ; precision=8
            """
        )

        self.assertTrue(isclose(output["OUT0"], 7.5))

    def test_quantization_can_degrade_when_hot(self) -> None:
        epu = EPU()
        epu.run("ECONST ER0, 1.2")
        epu.er["ER0"].temperature = 40.0

        epu.step("EQUANT ER1, ER0, 81")

        self.assertIn("DEGRADED", epu.sr)
        self.assertLess(epu.er["ER1"].current_partition, 81)
        self.assertIsNotNone(epu.er["ER1"].quantized_state)

    def test_precision_error_when_degrade_is_denied(self) -> None:
        epu = EPU()
        epu.run("ECONST ER0, 1.2")
        epu.er["ER0"].temperature = 40.0

        with self.assertRaises(EPUError) as captured:
            epu.step("EQOS ER0 ; min_partition=81 degrade=deny")

        self.assertEqual(captured.exception.code, "THERMAL_PRECISION_ERROR")

    def test_refresh_reduces_temperature(self) -> None:
        epu = EPU()
        epu.run("ECONST ER0, 5.0")
        epu.er["ER0"].temperature = 2.0

        epu.step("EREFRESH ER0")

        self.assertLess(epu.er["ER0"].temperature, 2.0)
        self.assertIn("NORMALIZED", epu.sr)

    def test_snapshot_restore_register(self) -> None:
        epu = EPU()

        output = epu.run(
            """
            ECONST ER0, 3.0
            ESNAP SNAP0, ER0
            ECONST ER0, 9.0
            ERESTORE ER0, SNAP0
            EOBS OUT0, ER0 ; precision=8
            """
        )

        self.assertTrue(isclose(output["OUT0"], 3.0))

    def test_parser_reads_options(self) -> None:
        parsed = parse_program("EOBS OUT0, ER1 ; precision=8")

        self.assertEqual(parsed[0].op, "EOBS")
        self.assertEqual(parsed[0].args, ["OUT0", "ER1"])
        self.assertEqual(parsed[0].options["precision"], "8")

    def test_event_log_contains_visual_snapshots(self) -> None:
        epu = EPU()

        epu.run(
            """
            ECONST ER0, 2.0
            ESHIFT ER1, ER0, 1
            EOBS OUT0, ER1 ; precision=6
            """
        )

        timeline = epu.timeline()
        self.assertEqual([event["op"] for event in timeline], ["ECONST", "ESHIFT", "EOBS"])
        self.assertIn("before", timeline[1])
        self.assertIn("after", timeline[1])
        self.assertIn("ER1", timeline[1]["after"]["er"])
        self.assertIn("digits", timeline[1]["after"]["er"]["ER1"])
        self.assertIn("OBSERVATION_DIRTY", timeline[2]["flags"])

    def test_non_finite_literal_is_an_epu_error(self) -> None:
        epu = EPU()

        with self.assertRaises(EPUError) as captured:
            epu.step("ECONST ER0, 1e999")

        self.assertEqual(captured.exception.code, "NUMERIC_ERROR")


if __name__ == "__main__":
    unittest.main()
