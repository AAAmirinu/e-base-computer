from copy import deepcopy
from math import inf, nan
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecomputer import EWord
from emulator import EPUEmulator
from epu import EPU, EPUError, FIELD_CAPABILITIES, TaskContext
from epu_scoring import score_timeline


class SharedInstructionCycleTests(unittest.TestCase):
    def test_control_instructions_advance_full_machine_cycle(self) -> None:
        epu = EPU()
        epu.er["ER0"].temperature = 0.1

        result = EPUEmulator(epu=epu).run(
            """
            EJMP first
            first: EJMP done
            done: EHALT
            """
        )

        self.assertEqual(result.steps, 3)
        self.assertEqual(epu.tick, 3)
        self.assertAlmostEqual(epu.er["ER0"].temperature, 0.085)
        self.assertEqual([event["tick"] for event in epu.timeline()], [0, 1, 2])
        self.assertEqual(
            [event["after"]["tick"] for event in epu.timeline()],
            [1, 2, 3],
        )

    def test_eprint_uses_same_observation_heat_as_eobs(self) -> None:
        low = EPUEmulator()
        low.run("ECONST ER0, 1\nEOBS OUT0, ER0")
        high = EPUEmulator()
        high.run("ECONST ER0, 1\nEPRINT ER0")

        self.assertAlmostEqual(
            low.epu.er["ER0"].temperature,
            high.epu.er["ER0"].temperature,
        )

    def test_destructive_observer_mode_changes_health_and_noise_deterministically(self) -> None:
        epu = EPU()
        epu.step("ECONST ER0, 1")
        before_health = epu.er["ER0"].health
        before_noise = epu.er["ER0"].noise
        epu.cr["observer_mode"] = "destructive"

        epu.step("EOBS OUT0, ER0")

        self.assertEqual(epu.er["ER0"].health, before_health - 0.001)
        self.assertGreater(epu.er["ER0"].noise, before_noise)

    def test_auto_refresh_runs_inside_cycle_and_is_scored(self) -> None:
        epu = EPU()
        epu.step("ECONST ER0, 1")
        epu.tick = 64
        epu.er["ER0"].temperature = 1.0
        epu.cr["auto_refresh"] = True

        EPUEmulator(epu=epu).run("EHALT")

        event = epu.timeline()[-1]
        self.assertIn("auto_refresh:ER0", event["maintenance"])
        self.assertNotIn("REFRESH_DUE", event["flags"])
        self.assertLess(epu.er["ER0"].temperature, 1.0)
        self.assertGreater(score_timeline([event]).refresh_events, 0)


class TaskContextTests(unittest.TestCase):
    def _owned_field(self) -> EPU:
        epu = EPU(TaskContext("alice", FIELD_CAPABILITIES))
        epu.run(
            """
            ECONST ER0, 7.5
            EALLOC EP0, COLD, 4 ; mode=EWORD
            ESTORE EP0, ER0
            """
        )
        return epu

    def test_owner_is_recorded_and_read_only_principal_can_observe(self) -> None:
        epu = self._owned_field()
        pointer = epu.ep["EP0"]
        assert pointer is not None
        self.assertEqual(epu.fields[pointer.field_id].owner, "alice")

        epu.set_context(TaskContext("bob", frozenset({"read", "observe_continuous"})))
        epu.run("ELOAD ER1, EP0\nEOBS OUT0, ER1 ; precision=8")

        self.assertEqual(epu.output["OUT0"], 7.5)
        self.assertEqual(epu.timeline()[-1]["principal"], "bob")

    def test_permission_denial_is_fail_closed_and_auditable(self) -> None:
        epu = self._owned_field()
        pointer = epu.ep["EP0"]
        assert pointer is not None
        before_cells = deepcopy(epu.banks[pointer.bank_id])
        before_field = deepcopy(epu.fields[pointer.field_id])
        before_tick = epu.tick
        epu.set_context(TaskContext("bob", frozenset({"read"})))

        with self.assertRaises(EPUError) as captured:
            epu.step("ESTORE EP0, ER0")

        self.assertEqual(captured.exception.code, "PERMISSION_ERROR")
        self.assertEqual(epu.banks[pointer.bank_id], before_cells)
        self.assertEqual(epu.fields[pointer.field_id], before_field)
        self.assertEqual(epu.tick, before_tick)
        event = epu.timeline()[-1]
        self.assertEqual(event["exception"], "PERMISSION_ERROR")
        self.assertEqual(event["principal"], "bob")
        self.assertEqual(event["required_capability"], "write")

    def test_qos_degrade_policy_is_target_local(self) -> None:
        epu = EPU()
        epu.run("ECONST ER0, 1\nECONST ER1, 1")
        epu.step("EQOS ER0 ; min_partition=27 degrade=deny")
        epu.step("EQOS ER1 ; min_partition=27 degrade=allow")

        self.assertFalse(epu.er["ER0"].allow_degrade)
        self.assertTrue(epu.er["ER1"].allow_degrade)
        self.assertTrue(epu.cr["allow_degrade"])


class InputDomainTests(unittest.TestCase):
    def test_non_finite_and_negative_digits_are_rejected(self) -> None:
        for value in (nan, inf, -inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EWord.from_real(value)
        with self.assertRaises(ValueError):
            EWord.from_digits({0: -1.0})

    def test_epu_reports_numeric_error_for_non_finite_input(self) -> None:
        for literal in ("nan", "1e999"):
            with self.subTest(literal=literal), self.assertRaises(EPUError) as captured:
                EPU().step(f"ECONST ER0, {literal}")
            self.assertEqual(captured.exception.code, "NUMERIC_ERROR")

    def test_allocation_reports_bad_operand_for_non_numeric_length(self) -> None:
        with self.assertRaises(EPUError) as captured:
            EPU().step("EALLOC EP0, COLD, not-a-number")

        self.assertEqual(captured.exception.code, "BAD_OPERAND")

    def test_partition_domain_is_enforced(self) -> None:
        epu = EPU()
        epu.step("ECONST ER0, 1")
        with self.assertRaises(EPUError) as captured:
            epu.step("EQUANT ER1, ER0, 5")
        self.assertEqual(captured.exception.code, "BAD_OPERAND")

    def test_store_overflow_is_rejected_without_partial_write(self) -> None:
        epu = EPU()
        epu.run("EALLOC EP0, COLD, 1\nECONST ER0, 1")
        pointer = epu.ep["EP0"]
        assert pointer is not None
        before = deepcopy(epu.banks[pointer.bank_id])
        epu.step("ECONST ER0, 100")

        with self.assertRaises(EPUError) as captured:
            epu.step("ESTORE EP0, ER0")

        self.assertEqual(captured.exception.code, "MEMORY_ERROR")
        self.assertEqual(epu.banks[pointer.bank_id], before)

    def test_quantized_metadata_survives_memory_round_trip(self) -> None:
        epu = EPU()
        epu.run(
            """
            ECONST ER0, 1.2
            EQUANT ER1, ER0, 27
            EALLOC EP0, COLD, 2
            ESTORE EP0, ER1
            ELOAD ER2, EP0
            """
        )

        self.assertEqual(epu.er["ER2"].quantized_state, epu.er["ER1"].quantized_state)
        self.assertEqual(epu.er["ER2"].partition, 27)
        self.assertEqual(epu.er["ER2"].mode, "PACKED_TRIT")


if __name__ == "__main__":
    unittest.main()
