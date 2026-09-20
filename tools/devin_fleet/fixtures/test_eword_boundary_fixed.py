"""Acceptance regressions; run only in credential-free validation container."""
from math import e, isclose
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ecomputer import EWord


class EWordBoundaryRegression(unittest.TestCase):
    def test_digit_below_base_preserves_value(self):
        value = e - 1e-9
        self.assertTrue(isclose(EWord.from_digits({0: value}).to_real(), value,
                                rel_tol=1e-12, abs_tol=0.0))

    def test_values_further_from_base_preserve_value(self):
        for value in (e - 1e-7, e + 1e-7, e + 0.5):
            with self.subTest(value=value):
                word = EWord.from_digits({0: value})
                self.assertTrue(all(0 <= digit < e for digit in word.digits.values()))
                self.assertTrue(isclose(word.to_real(), value, rel_tol=1e-12))

    def test_near_base_across_signs_and_powers(self):
        for sign in (-1, 1):
            for power in (-4, 0, 4):
                for offset in (1e-11, 1e-9, 1e-8):
                    with self.subTest(sign=sign, power=power, offset=offset):
                        value = e - offset
                        word = EWord.from_digits({power: value}, sign=sign)
                        self.assertTrue(isclose(word.to_real(), sign * value * e**power,
                                                rel_tol=1e-12, abs_tol=0.0))
                        self.assertTrue(all(0 <= digit < e for digit in word.digits.values()))

    def test_repeated_normalization_keeps_canonical_boundary(self):
        word = EWord.from_digits({0: e - 1e-9})
        again = word.normalize()
        self.assertEqual(word.digits, again.digits)
        self.assertEqual(word.sign, again.sign)
        self.assertTrue(isclose(again.to_real(), e - 1e-9, rel_tol=1e-12, abs_tol=0.0))


if __name__ == '__main__':
    unittest.main()
