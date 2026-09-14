"""Exercise the published example entry points, including field round trips."""
import math
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from epu import EPU


class DemoProgramTests(unittest.TestCase):
    def test_published_demo_entry_points(self):
        for name in ("demo.py", "epu_demo.py", "cstyle_demo.py", "runtime_permission_demo.py"):
            with self.subTest(name=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "examples" / name)],
                    cwd=ROOT, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.strip())

    def test_epu_demo_preserves_shifted_product_through_memory(self):
        program = runpy.run_path(str(ROOT / "examples" / "epu_demo.py"))["program"]
        epu = EPU()
        output = epu.run(program + "\nEOBS ROUNDTRIP, ER4 ; precision=8\n")
        expected = 12.5 * 4.25 * math.e
        self.assertAlmostEqual(output["OUT_PRODUCT_E"], expected, places=7)
        self.assertAlmostEqual(output["ROUNDTRIP"], expected, places=7)
