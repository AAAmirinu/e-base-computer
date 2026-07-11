from math import isclose
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cstyle_compiler import CStyleCompileError, CStyleCompiler
from emulator import EPUEmulator, assemble
from epu import EPUError


class EPUEmulatorTests(unittest.TestCase):
    def test_labels_and_branches_run_loop(self) -> None:
        result = EPUEmulator().run(
            """
            ECONST ER0, 3
            ECONST ER1, 0
            ECONST ER2, 1
            loop:
            EADD ER1, ER1, ER0
            ESUB ER0, ER0, ER2
            EJGTZ ER0, loop
            EOBS OUT0, ER1 ; precision=8
            EHALT
            ECONST ER1, 999
            """
        )

        self.assertTrue(result.halted)
        self.assertTrue(isclose(result.output["OUT0"], 6.0))

    def test_execution_limit_stops_infinite_loop(self) -> None:
        with self.assertRaises(EPUError) as captured:
            EPUEmulator(max_steps=5).run("loop:\nEJMP loop")

        self.assertEqual(captured.exception.code, "EXECUTION_LIMIT")

    def test_existing_memory_program_runs_through_emulator(self) -> None:
        result = EPUEmulator().run(
            """
            ECONST ER0, 7.5
            EALLOC EP0, COLD, 4 ; mode=EWORD
            ESTORE EP0, ER0
            ELOAD ER1, EP0
            EOBS OUT0, ER1 ; precision=8
            """
        )

        self.assertTrue(isclose(result.output["OUT0"], 7.5))

    def test_assemble_collects_inline_labels(self) -> None:
        executable = assemble("start: ECONST ER0, 1\nEHALT")

        self.assertEqual(executable.labels["start"], 0)
        self.assertEqual(executable.instructions[0].op, "ECONST")


class CStyleCompilerTests(unittest.TestCase):
    def test_arithmetic_print(self) -> None:
        result = CStyleCompiler(precision=8).compile_and_run(
            """
            let a = 12.5;
            let b = 4.25;
            let c = a * b + 2;
            print(c);
            """
        )

        self.assertTrue(isclose(result.output["OUT0"], 55.125))

    def test_expression_precedence_unary_and_left_association(self) -> None:
        result = CStyleCompiler(precision=8).compile_and_run(
            """
            print(1 + 2 * 3);
            print((1 + 2) * 3);
            print(10 - 3 - 2);
            print(-2 * (3 + 4));
            """
        )

        self.assertEqual(result.output["OUT0"], 7.0)
        self.assertEqual(result.output["OUT1"], 9.0)
        self.assertEqual(result.output["OUT2"], 5.0)
        self.assertEqual(result.output["OUT3"], -14.0)

    def test_utf8_bom_source_compiles(self) -> None:
        result = CStyleCompiler(precision=8).compile_and_run("\ufefflet x = 2; print(x);")

        self.assertEqual(result.output["OUT0"], 2.0)

    def test_while_factorial(self) -> None:
        result = CStyleCompiler(precision=8).compile_and_run(
            """
            let n = 5;
            let acc = 1;
            while (n > 1) {
                acc = acc * n;
                n = n - 1;
            }
            print(acc);
            """
        )

        self.assertTrue(isclose(result.output["OUT0"], 120.0))

    def test_while_false_does_not_skip_later_output_number(self) -> None:
        result = CStyleCompiler(precision=8).compile_and_run(
            """
            let x = 0;
            while (x) {
                print(999);
            }
            print(2);
            """
        )

        self.assertEqual(result.output, {"OUT0": 2.0})

    def test_if_else_selects_branch(self) -> None:
        result = CStyleCompiler(precision=8).compile_and_run(
            """
            let signal = -2;
            if (signal >= 0) {
                print(1);
            } else {
                print(0);
            }
            """
        )

        self.assertEqual(result.output["OUT0"], 0.0)

    def test_observe_alias_and_precision(self) -> None:
        compiler = CStyleCompiler(precision=3)
        compiled = compiler.compile("let x = 1.23456; observe(x);")
        result = EPUEmulator().run(compiled.assembly)

        self.assertIn("EPRINT", compiled.assembly)
        self.assertIn("precision=3", compiled.assembly)
        self.assertEqual(result.output["OUT0"], 1.235)

    def test_division_is_compile_error(self) -> None:
        with self.assertRaises(CStyleCompileError):
            CStyleCompiler().compile("print(1 / 2);")

    def test_unknown_variable_is_compile_error(self) -> None:
        with self.assertRaises(CStyleCompileError):
            CStyleCompiler().compile("x = 1;")


if __name__ == "__main__":
    unittest.main()
