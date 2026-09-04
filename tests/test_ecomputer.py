from math import isclose
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecomputer import MAX_EXPONENT, EComputer, EWord, EWordError, e


class EWordTests(unittest.TestCase):
    def test_normalize_carries_value(self) -> None:
        word = EWord.from_digits({0: e + 0.5})

        self.assertTrue(all(0 <= digit < e for digit in word.digits.values()))
        self.assertTrue(isclose(word.to_real(), e + 0.5, rel_tol=1e-12))

    def test_add_same_sign(self) -> None:
        left = EWord.from_real(12.5)
        right = EWord.from_real(4.25)

        self.assertTrue(isclose(left.add_same_sign(right).to_real(), 16.75, rel_tol=1e-12))

    def test_multiply(self) -> None:
        left = EWord.from_real(12.5)
        right = EWord.from_real(4.25)

        self.assertTrue(isclose(left.multiply(right).to_real(), 53.125, rel_tol=1e-12))

    def test_vm_prints(self) -> None:
        computer = EComputer()
        output = computer.run(
            [
                ("CONST", "A", "2"),
                ("SHIFT", "EA", "A", "1"),
                ("PRINT", "EA"),
            ]
        )

        self.assertIn("EA =", output[0])

    def test_invalid_or_unrepresentable_values_raise_specific_error(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(EWordError):
                EWord.from_real(value)
        with self.assertRaises(EWordError):
            EWord.from_digits({0: -1.0})
        with self.assertRaises(EWordError):
            EWord.from_digits({0: float("inf")})
        with self.assertRaises(EWordError):
            EWord.from_digits({MAX_EXPONENT + 1: 1.0})
        with self.assertRaises(EWordError):
            EWord.from_digits({MAX_EXPONENT: e - 0.1}).to_real()


if __name__ == "__main__":
    unittest.main()
