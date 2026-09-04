"""Table-driven conformance checks for every public EPU opcode.

The tables in this module are intentionally exhaustive.  Adding an opcode to
``epu_spec.INSTRUCTIONS`` without adding both a successful dispatch case and a
representative fail-closed case makes this suite fail immediately.
"""

from copy import deepcopy
from dataclasses import dataclass
from math import e
from pathlib import Path
import sys
import unittest
from typing import Any, Dict, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emulator import CONTROL_OPS, EPUEmulator
from epu import EPU, EPUError, NATIVE_OPS
from epu_spec import INSTRUCTIONS


Probe = Tuple[str, str, Any]


@dataclass(frozen=True)
class SuccessCase:
    opcode: str
    source: str
    probe: Optional[Probe] = None


@dataclass(frozen=True)
class FailureCase:
    opcode: str
    failing_source: str
    error_code: str
    setup_source: str = ""


SUCCESS_CASES = (
    SuccessCase("ECONST", "ECONST ER0, 2.5", ("real", "ER0", 2.5)),
    SuccessCase("EDIGITS", "EDIGITS ER0, 0:1.5", ("real", "ER0", 1.5)),
    SuccessCase("EMOV", "ECONST ER0, 2.5\nEMOV ER1, ER0", ("real", "ER1", 2.5)),
    SuccessCase("EADD", "ECONST ER0, 2\nECONST ER1, 3\nEADD ER2, ER0, ER1", ("real", "ER2", 5.0)),
    SuccessCase("ESUB", "ECONST ER0, 5\nECONST ER1, 2\nESUB ER2, ER0, ER1", ("real", "ER2", 3.0)),
    SuccessCase("EMUL", "ECONST ER0, 2\nECONST ER1, 3\nEMUL ER2, ER0, ER1", ("real", "ER2", 6.0)),
    SuccessCase("ECONV", "ECONST ER0, 2\nECONST ER1, 3\nECONV ER2, ER0, ER1", ("real", "ER2", 6.0)),
    SuccessCase("ESHIFT", "ECONST ER0, 1\nESHIFT ER1, ER0, 1", ("real", "ER1", e)),
    SuccessCase("ESCALE", "ECONST ER0, 2\nESCALE ER1, ER0, 0.5", ("real", "ER1", 1.0)),
    SuccessCase("ENORM", "EDIGITS ER0, 0:1\nENORM ER0", ("event_flag", "NORMALIZED", True)),
    SuccessCase("EALLOC", "EALLOC EP0, COLD, 4", ("pointer", "EP0", True)),
    SuccessCase(
        "ELOAD",
        "ECONST ER0, 1.25\nEALLOC EP0, COLD, 4\nESTORE EP0, ER0\nELOAD ER1, EP0",
        ("real", "ER1", 1.25),
    ),
    SuccessCase(
        "ESTORE",
        "ECONST ER0, 1.25\nEALLOC EP0, COLD, 4\nESTORE EP0, ER0\nELOAD ER1, EP0",
        ("real", "ER1", 1.25),
    ),
    SuccessCase("EMODE", "ECONST ER0, 1\nEMODE ER0, CONTINUOUS", ("mode", "ER0", "CONTINUOUS")),
    SuccessCase("ETRIT", "ETRIT TR0, -1, 0, 1", ("trit", "TR0", (-1, 0, 1))),
    SuccessCase(
        "ETCMP",
        "ECONST ER0, 1\nECONST ER1, 2\nETCMP TR0, ER0, ER1",
        ("trit", "TR0", (-1,)),
    ),
    SuccessCase(
        "ETSEL",
        "ECONST ER0, -1\nECONST ER1, 0\nECONST ER2, 1\nETRIT TR0, 1\nETSEL ER3, TR0, ER0, ER1, ER2",
        ("real", "ER3", 1.0),
    ),
    SuccessCase("ETEMP", "ETEMP DIAGNOSTICS", ("temp", "DIAGNOSTICS", True)),
    SuccessCase("EQOS", "EQOS ER0 ; min_partition=27 degrade=allow", ("partition", "ER0", 27)),
    SuccessCase("EQUANT", "ECONST ER0, 1\nEQUANT ER1, ER0, 27", ("quantized", "ER1", 27)),
    SuccessCase("EDEQ", "ECONST ER0, 1\nEQUANT ER1, ER0, 27\nEDEQ ER2, ER1", ("mode", "ER2", "CONTINUOUS")),
    SuccessCase("ECLAMP", "ECONST ER0, 1\nEQUANT ER1, ER0, 27\nECLAMP ER1", ("quantized", "ER1", 27)),
    SuccessCase("EOBS", "ECONST ER0, 1.23456\nEOBS SAMPLE, ER0 ; precision=4", ("output", "SAMPLE", 1.2346)),
    SuccessCase("EPRINT", "ECONST ER0, 1.23456\nEPRINT ER0 ; precision=4", ("output", "OUT0", 1.2346)),
    SuccessCase("ETRACE", "ECONST ER0, 1\nETRACE ER0", ("trace", "ER0", True)),
    SuccessCase("ETHERM", "ECONST ER0, 1\nETHERM THERMAL, ER0", ("thermal", "THERMAL", True)),
    SuccessCase("EREFRESH", "ECONST ER0, 1\nEREFRESH ER0", ("event_flag", "NORMALIZED", True)),
    SuccessCase("ESCRUB", "EALLOC EP0, COLD, 4\nESCRUB COLD", ("event_flag", "NORMALIZED", True)),
    SuccessCase("ESNAP", "ECONST ER0, 2\nESNAP safe, ER0", ("snapshot", "safe", True)),
    SuccessCase(
        "ERESTORE",
        "ECONST ER0, 2\nESNAP safe, ER0\nECONST ER0, 9\nERESTORE ER0, safe",
        ("real", "ER0", 2.0),
    ),
    SuccessCase("EJMP", "EJMP hit\nECONST ER0, 0\nhit: ECONST ER0, 1\nEOBS OUT0, ER0", ("output", "OUT0", 1.0)),
    SuccessCase("EJZ", "ECONST ER0, 0\nEJZ ER0, hit\nECONST ER1, 0\nhit: ECONST ER1, 1\nEOBS OUT0, ER1", ("output", "OUT0", 1.0)),
    SuccessCase("EJNZ", "ECONST ER0, 1\nEJNZ ER0, hit\nECONST ER1, 0\nhit: ECONST ER1, 1\nEOBS OUT0, ER1", ("output", "OUT0", 1.0)),
    SuccessCase("EJGTZ", "ECONST ER0, 1\nEJGTZ ER0, hit\nECONST ER1, 0\nhit: ECONST ER1, 1\nEOBS OUT0, ER1", ("output", "OUT0", 1.0)),
    SuccessCase("EJLTZ", "ECONST ER0, -1\nEJLTZ ER0, hit\nECONST ER1, 0\nhit: ECONST ER1, 1\nEOBS OUT0, ER1", ("output", "OUT0", 1.0)),
    SuccessCase("EJGEZ", "ECONST ER0, 0\nEJGEZ ER0, hit\nECONST ER1, 0\nhit: ECONST ER1, 1\nEOBS OUT0, ER1", ("output", "OUT0", 1.0)),
    SuccessCase("EJLEZ", "ECONST ER0, 0\nEJLEZ ER0, hit\nECONST ER1, 0\nhit: ECONST ER1, 1\nEOBS OUT0, ER1", ("output", "OUT0", 1.0)),
    SuccessCase("EHALT", "EHALT\nECONST ER0, 99", ("halted", "", True)),
)


FAILURE_CASES = (
    FailureCase("ECONST", "ECONST ER0", "BAD_OPERAND"),
    FailureCase("EDIGITS", "EDIGITS ER0, invalid", "BAD_OPERAND"),
    FailureCase("EMOV", "EMOV INVALID, ER0", "BAD_OPERAND"),
    FailureCase("EADD", "EADD ER2, ER0", "BAD_OPERAND"),
    FailureCase("ESUB", "ESUB ER2, ER0", "BAD_OPERAND"),
    FailureCase("EMUL", "EMUL ER2, ER0", "BAD_OPERAND"),
    FailureCase("ECONV", "ECONV ER2, ER0", "BAD_OPERAND"),
    FailureCase("ESHIFT", "ESHIFT ER1, ER0, invalid", "BAD_OPERAND"),
    FailureCase("ESCALE", "ESCALE ER1, ER0, nan", "NUMERIC_ERROR"),
    FailureCase("ENORM", "ENORM ER16", "BAD_OPERAND"),
    FailureCase("EALLOC", "EALLOC EP0, COLD, 4 ; mode=INVALID", "MODE_ERROR"),
    FailureCase("ELOAD", "ELOAD ER0, EP0", "MEMORY_ERROR"),
    FailureCase("ESTORE", "ESTORE EP0, ER0", "MEMORY_ERROR"),
    FailureCase("EMODE", "EMODE ER0, INVALID", "MODE_ERROR"),
    FailureCase("ETRIT", "ETRIT TR0, 2", "BAD_OPERAND"),
    FailureCase("ETCMP", "ETCMP TR0, ER0, ER1 ; epsilon=-1", "BAD_OPERAND"),
    FailureCase("ETSEL", "ETSEL ER0, TR8, ER1, ER2, ER3", "BAD_OPERAND"),
    FailureCase("ETEMP", "ETEMP OUT0, TEMP", "BAD_OPERAND"),
    FailureCase("EQOS", "EQOS ER0, ER1", "BAD_OPERAND"),
    FailureCase("EQUANT", "EQUANT ER1, ER0, 4", "BAD_OPERAND"),
    FailureCase("EDEQ", "EDEQ ER1, ER0", "MODE_ERROR"),
    FailureCase("ECLAMP", "ECLAMP ER0", "MODE_ERROR"),
    FailureCase("EOBS", "EOBS OUT0, ER16", "BAD_OPERAND"),
    FailureCase("EPRINT", "EPRINT ER16", "BAD_OPERAND"),
    FailureCase("ETRACE", "ETRACE EP0", "MEMORY_ERROR"),
    FailureCase("ETHERM", "ETHERM THERMAL, EP0", "MEMORY_ERROR"),
    FailureCase("EREFRESH", "EREFRESH EP0", "MEMORY_ERROR"),
    FailureCase("ESCRUB", "ESCRUB COLD, ARCHIVE", "BAD_OPERAND"),
    FailureCase("ESNAP", "ESNAP safe, EP0", "MEMORY_ERROR"),
    FailureCase("ERESTORE", "ERESTORE ER0, missing", "RESTORE_ERROR"),
    FailureCase("EJMP", "EJMP missing", "BAD_OPERAND"),
    FailureCase("EJZ", "EJZ ER0, missing", "BAD_OPERAND"),
    FailureCase("EJNZ", "EJNZ ER0, missing", "BAD_OPERAND", "ECONST ER0, 1"),
    FailureCase("EJGTZ", "EJGTZ ER0, missing", "BAD_OPERAND", "ECONST ER0, 1"),
    FailureCase("EJLTZ", "EJLTZ ER0, missing", "BAD_OPERAND", "ECONST ER0, -1"),
    FailureCase("EJGEZ", "EJGEZ ER0, missing", "BAD_OPERAND"),
    FailureCase("EJLEZ", "EJLEZ ER0, missing", "BAD_OPERAND"),
    FailureCase("EHALT", "EHALT ER0", "BAD_OPERAND"),
)


class OpcodeConformanceTests(unittest.TestCase):
    def test_spec_dispatch_and_case_tables_are_exactly_the_same_38_opcodes(self) -> None:
        spec_ops = [instruction.opcode for instruction in INSTRUCTIONS]
        dispatch_ops = set(NATIVE_OPS) | set(CONTROL_OPS)

        self.assertEqual(len(spec_ops), 38)
        self.assertEqual(len(spec_ops), len(set(spec_ops)), "spec opcodes must be unique")
        self.assertEqual(set(spec_ops), dispatch_ops)
        self.assertEqual(set(spec_ops), {case.opcode for case in SUCCESS_CASES})
        self.assertEqual(set(spec_ops), {case.opcode for case in FAILURE_CASES})
        self.assertEqual(len(SUCCESS_CASES), 38)
        self.assertEqual(len(FAILURE_CASES), 38)

    def test_every_opcode_has_a_successful_semantic_dispatch(self) -> None:
        for case in SUCCESS_CASES:
            with self.subTest(opcode=case.opcode):
                emulator = EPUEmulator()
                result = emulator.run(case.source)
                matching_events = [
                    event for event in emulator.epu.timeline() if event["op"] == case.opcode
                ]
                self.assertTrue(matching_events, f"no dispatch event for {case.opcode}")
                self.assertIsNone(matching_events[-1]["exception"])
                self._assert_probe(case, emulator, result, matching_events[-1])

    def test_every_opcode_failure_is_coded_audited_and_semantically_atomic(self) -> None:
        for case in FAILURE_CASES:
            with self.subTest(opcode=case.opcode):
                epu = EPU()
                if case.setup_source:
                    EPUEmulator(epu=epu).run(case.setup_source)
                before = self._semantic_state(epu)
                prior_events = len(epu.event_log)

                with self.assertRaises(EPUError) as captured:
                    EPUEmulator(epu=epu).run(case.failing_source)

                self.assertEqual(captured.exception.code, case.error_code)
                self.assertEqual(self._semantic_state(epu), before)
                self.assertEqual(epu.tick, before["tick"])
                self.assertEqual(len(epu.event_log), prior_events + 1)
                failure_event = epu.event_log[-1]
                self.assertEqual(failure_event["op"], case.opcode)
                self.assertEqual(failure_event["exception"], case.error_code)
                self.assertIn("EXCEPTION", failure_event["flags"])

    def _assert_probe(self, case: SuccessCase, emulator: EPUEmulator, result: Any, event: Dict[str, Any]) -> None:
        if case.probe is None:
            return
        kind, key, expected = case.probe
        if kind == "real":
            self.assertAlmostEqual(emulator.epu.er[key].word.to_real(), expected, places=10)
        elif kind == "mode":
            self.assertEqual(emulator.epu.er[key].mode, expected)
        elif kind == "pointer":
            self.assertEqual(emulator.epu.ep[key] is not None, expected)
        elif kind == "partition":
            self.assertEqual(emulator.epu.er[key].current_partition, expected)
        elif kind == "quantized":
            value = emulator.epu.er[key]
            self.assertIsNotNone(value.quantized_state)
            self.assertEqual(value.partition, expected)
        elif kind == "output":
            self.assertAlmostEqual(result.output[key], expected, places=10)
        elif kind == "trace":
            self.assertTrue(any(key in line for line in emulator.epu.trace), expected)
        elif kind == "thermal":
            self.assertIn("temperature", result.output[key])
            self.assertIn("q_max", result.output[key])
        elif kind == "trit":
            self.assertEqual(emulator.epu.tr[key].lanes, expected)
        elif kind == "temp":
            self.assertEqual(key in result.output, expected)
            self.assertIn("max_temperature", result.output[key])
        elif kind == "event_flag":
            self.assertIn(key, event["flags"])
        elif kind == "snapshot":
            self.assertEqual(key in emulator.epu.snapshots, expected)
        elif kind == "halted":
            self.assertEqual(result.halted, expected)
            self.assertNotIn("OUT0", result.output)
        else:  # pragma: no cover - table authoring guard
            self.fail(f"unknown success probe {kind!r} for {case.opcode}")

    @staticmethod
    def _semantic_state(epu: EPU) -> Dict[str, Any]:
        """State that must not change when a trapping instruction fails.

        Status/exception/event records are intentionally excluded: they are the
        required audit evidence of the failure, not part of its semantic effect.
        """

        return deepcopy(
            {
                "er": epu.er,
                "ep": epu.ep,
                "tr": epu.tr,
                "banks": epu.banks,
                "bank_meta": epu.bank_meta,
                "fields": epu.fields,
                "snapshots": epu.snapshots,
                "output": epu.output,
                "trace": epu.trace,
                "tick": epu.tick,
                "next_field_id": epu.next_field_id,
            }
        )


if __name__ == "__main__":
    unittest.main()
