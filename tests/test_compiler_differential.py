"""Independent differential checks for the C-like compiler.

The oracle deliberately does not execute compiler assembly or reuse compiler
parsing.  It evaluates the generated program parameters directly, then compares
that result with the EPU target execution.
"""

from math import isclose
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cstyle_compiler import CStyleCompileError, CStyleCompiler


COMPARISONS = {
    ">": lambda left, right: left > right,
    "<": lambda left, right: left < right,
    ">=": lambda left, right: left >= right,
    "<=": lambda left, right: left <= right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
}


def generated_loop_source(
    *, n: int, initial: int, factor: int, pivot: int, adjustment: int, threshold: int
) -> str:
    return f"""
        let n = {n};
        let acc = {initial};
        let i = 0;
        while (i < n) {{
            if (i != {pivot}) {{
                acc = acc + i * {factor};
            }} else {{
                acc = acc - {adjustment};
            }}
            if (acc >= {threshold}) {{
                acc = acc - 1;
            }} else {{
                acc = acc + 2;
            }}
            i = i + 1;
        }}
        print(acc);
        print(i);
    """


def generated_loop_oracle(
    *, n: int, initial: int, factor: int, pivot: int, adjustment: int, threshold: int
) -> tuple[float, float]:
    acc = initial
    i = 0
    while i < n:
        if i != pivot:
            acc = acc + i * factor
        else:
            acc = acc - adjustment
        if acc >= threshold:
            acc = acc - 1
        else:
            acc = acc + 2
        i += 1
    return float(acc), float(i)


class CompilerDifferentialTests(unittest.TestCase):
    def test_fixed_seed_nested_programs_match_independent_oracle(self) -> None:
        rng = random.Random(0xEBA5E)
        compiler = CStyleCompiler(precision=12)
        for case_index in range(40):
            parameters = {
                "n": rng.randint(1, 6),
                "initial": rng.randint(-8, 8),
                "factor": rng.randint(-3, 4),
                "pivot": rng.randint(0, 6),
                "adjustment": rng.randint(0, 5),
                "threshold": rng.randint(-6, 12),
            }
            with self.subTest(case=case_index, **parameters):
                expected = generated_loop_oracle(**parameters)
                result = compiler.compile_and_run(
                    generated_loop_source(**parameters), max_steps=2_000
                )
                self.assertEqual(list(result.output), ["OUT0", "OUT1"])
                self.assertTrue(isclose(result.output["OUT0"], expected[0], abs_tol=1e-9))
                self.assertTrue(isclose(result.output["OUT1"], expected[1], abs_tol=1e-9))

    def test_all_comparisons_match_language_level_truth_table(self) -> None:
        compiler = CStyleCompiler(precision=12)
        for operator, predicate in COMPARISONS.items():
            for left, right in [(-1, 0), (0, 0), (1, 0), (3, 5), (5, 3)]:
                source = f"""
                    if ({left} {operator} {right}) {{
                        print(1);
                    }} else {{
                        print(0);
                    }}
                """
                with self.subTest(operator=operator, left=left, right=right):
                    result = compiler.compile_and_run(source)
                    self.assertEqual(result.output["OUT0"], float(predicate(left, right)))

    def test_compilation_is_deterministic(self) -> None:
        source = generated_loop_source(
            n=5, initial=2, factor=3, pivot=1, adjustment=4, threshold=8
        )
        first = CStyleCompiler().compile(source)
        second = CStyleCompiler().compile(source)
        self.assertEqual(first.assembly, second.assembly)
        self.assertEqual(first.symbols, second.symbols)

    def test_initializer_temp_is_promoted_and_all_registers_are_usable(self) -> None:
        source = "\n".join(f"let v{index} = {index};" for index in range(16))
        compiled = CStyleCompiler().compile(source + "\nprint(v15);")
        result = CStyleCompiler().compile_and_run(source + "\nprint(v15);")

        self.assertEqual(len(compiled.symbols), 16)
        self.assertNotIn("EMOV", compiled.assembly)
        self.assertEqual(result.output["OUT0"], 15.0)

    def test_register_exhaustion_and_language_errors_are_precise(self) -> None:
        seventeen = "\n".join(f"let v{index} = {index};" for index in range(17))
        cases = [
            (seventeen, "out of E registers"),
            ("print(missing);", "unknown variable: missing"),
            ("let x = 1; let x = 2;", "variable already declared: x"),
            ("print(1 / 2);", "division is not supported"),
        ]
        for source, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(CStyleCompileError, message):
                    CStyleCompiler().compile(source)


if __name__ == "__main__":
    unittest.main()
