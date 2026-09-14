from math import e, isclose
from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecomputer import EWord
from emulator import EPUEmulator
from epu import EPU, EPUError, PARTITION_STEPS


class EWordPropertyTests(unittest.TestCase):
    def test_fixed_seed_normalization_preserves_value_and_digit_domain(self) -> None:
        rng = random.Random(20260813)
        for _ in range(200):
            digits = {power: rng.random() * 20 for power in range(-5, 6)}
            expected = sum(digit * (e**power) for power, digit in digits.items())
            word = EWord.from_digits(digits)
            self.assertTrue(all(0 <= digit < e for digit in word.digits.values()))
            self.assertTrue(isclose(word.to_real(), expected, rel_tol=1e-12, abs_tol=1e-12))

    def test_fixed_seed_real_and_arithmetic_round_trips(self) -> None:
        rng = random.Random(271828)
        for _ in range(200):
            left_real = (1 if rng.random() < 0.5 else -1) * 10 ** rng.uniform(-9, 9)
            right_real = (1 if left_real > 0 else -1) * 10 ** rng.uniform(-9, 9)
            left = EWord.from_real(left_real)
            right = EWord.from_real(right_real)
            self.assertTrue(isclose(left.to_real(), left_real, rel_tol=1e-12, abs_tol=1e-12))
            self.assertTrue(
                isclose(
                    left.add_same_sign(right).to_real(),
                    left_real + right_real,
                    rel_tol=1e-11,
                    abs_tol=1e-11,
                )
            )
            self.assertTrue(
                isclose(
                    left.multiply(right).to_real(),
                    left_real * right_real,
                    rel_tol=1e-11,
                    abs_tol=1e-11,
                )
            )


class ThermalQuantizationProperties(unittest.TestCase):
    def test_qmax_is_monotone_in_temperature_and_guard_band(self) -> None:
        epu = EPU()
        by_temperature = [epu._max_partition(value, 0.006) for value in (0, 1, 5, 20, 100)]
        by_guard = [epu._max_partition(1, value) for value in (0.001, 0.003, 0.01, 0.03)]
        self.assertEqual(by_temperature, sorted(by_temperature, reverse=True))
        self.assertEqual(by_guard, sorted(by_guard, reverse=True))

    def test_quantization_uses_supported_partition_and_respects_error_bound(self) -> None:
        value = 1.23456789
        for partition in PARTITION_STEPS:
            epu = EPU()
            epu.step(f"ECONST ER0, {value}")
            epu.step(f"EQUANT ER1, ER0, {partition}")
            quantized = epu.er["ER1"]
            self.assertIn(quantized.partition, PARTITION_STEPS)
            assert quantized.partition is not None
            self.assertLessEqual(
                abs(quantized.word.to_real() - value),
                e / (2 * quantized.partition) + 1e-12,
            )

    def test_invalid_modes_and_qos_policy_fail_before_mutation(self) -> None:
        epu = EPU()
        epu.step("ECONST ER0, 1")
        before = epu.er["ER0"].copy()
        for instruction, code in (
            ("EMODE ER0, UNKNOWN", "MODE_ERROR"),
            ("EQOS ER0 ; min_partition=27 degrade=maybe", "BAD_OPERAND"),
        ):
            with self.subTest(instruction=instruction), self.assertRaises(EPUError) as captured:
                epu.step(instruction)
            self.assertEqual(captured.exception.code, code)
            self.assertEqual(epu.er["ER0"], before)


class ControlPredicateProperties(unittest.TestCase):
    def test_all_branch_predicates_at_epsilon_boundaries(self) -> None:
        emulator = EPUEmulator()
        epsilon = 1e-12
        expected = {
            "EJZ": (False, True, False),
            "EJNZ": (True, False, True),
            "EJGTZ": (False, False, True),
            "EJLTZ": (True, False, False),
            "EJGEZ": (False, True, True),
            "EJLEZ": (True, True, False),
        }
        values = (-2 * epsilon, 0.0, 2 * epsilon)
        for op, decisions in expected.items():
            self.assertEqual(
                tuple(emulator._branch_taken(op, value) for value in values),
                decisions,
                op,
            )


if __name__ == "__main__":
    unittest.main()
