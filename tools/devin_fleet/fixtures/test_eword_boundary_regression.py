"""Baseline reproduction; execute only in the credential-free validation container."""
from math import e, isclose
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ecomputer import EWord


class EWordBoundaryRegression(unittest.TestCase):
    @unittest.expectedFailure
    def test_digit_below_base_preserves_value(self):
        # Already canonical, well outside the documented absolute EPSILON.
        value = e - 1e-9
        actual = EWord.from_digits({0: value}).to_real()
        self.assertTrue(isclose(actual, value, rel_tol=1e-12, abs_tol=0.0),
                        f'input={value!r}, actual={actual!r}')

    def test_values_further_from_base_preserve_value(self):
        for value in (e - 1e-7, e + 1e-7, e + 0.5):
            with self.subTest(value=value):
                word = EWord.from_digits({0: value})
                self.assertTrue(all(0 <= digit < e for digit in word.digits.values()))
                self.assertTrue(isclose(word.to_real(), value, rel_tol=1e-12))


if __name__ == '__main__':
    unittest.main()
