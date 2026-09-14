"""Behavioral checks for metadata propagation contract schema v1."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecomputer import EWord
from emulator import EPUEmulator
from epu import (
    INSTRUCTION_HEAT,
    INSTRUCTION_STRESS,
    ECell,
    EField,
    EPU,
    EPUError,
    ERegisterValue,
    parse_instruction,
)
from epu_metadata import (
    METADATA_CONTRACT_SCHEMA_VERSION,
    METADATA_FIELDS,
    METADATA_RULES,
    PROPAGATION_CLASSES,
    metadata_contract_payload,
    validate_metadata_contract,
)
from epu_spec import INSTRUCTIONS, spec_payload
from tests.test_opcode_conformance import SUCCESS_CASES


def rich_value(real: float = 1.25) -> ERegisterValue:
    return ERegisterValue(
        word=EWord.from_real(real),
        mode="COEFFICIENT",
        temperature=0.75,
        noise=0.031,
        health=0.82,
        min_partition=81,
        current_partition=27,
        allow_degrade=False,
        guard_band=0.009,
        quantized_state=11,
        partition=27,
        last_refresh=17,
    )


def metadata(value: ERegisterValue) -> dict:
    return {name: getattr(value, name) for name in METADATA_FIELDS}


class MetadataContractSchemaTests(unittest.TestCase):
    def test_contract_is_versioned_exhaustive_and_embedded_in_spec(self) -> None:
        opcodes = [instruction.opcode for instruction in INSTRUCTIONS]
        payload = metadata_contract_payload(opcodes)

        self.assertEqual(payload["schema_version"], METADATA_CONTRACT_SCHEMA_VERSION)
        self.assertEqual(set(payload["rules"]), set(opcodes))
        self.assertEqual(len(payload["rules"]), 38)
        self.assertEqual(
            {rule.classification for rule in METADATA_RULES.values()},
            set(PROPAGATION_CLASSES),
        )
        for rule in payload["rules"].values():
            self.assertEqual(set(rule["fields"]), set(METADATA_FIELDS))
        self.assertEqual(spec_payload()["metadata_contract"], payload)

    def test_runtime_snapshot_exposes_every_contracted_freshness_field(self) -> None:
        epu = EPU()
        epu.step("EALLOC EP0, COLD, 2")
        pointer = epu.ep["EP0"]
        assert pointer is not None
        snapshot = epu.visual_snapshot()
        surfaces = spec_payload()["metadata_contract"]["runtime_snapshot_surfaces"]

        self.assertTrue(set(surfaces["ER"]).issubset(snapshot["er"]["ER0"]))
        self.assertTrue(
            set(surfaces["field"]).issubset(snapshot["fields"][pointer.field_id])
        )

    def test_contract_validation_fails_closed_on_opcode_drift(self) -> None:
        opcodes = [instruction.opcode for instruction in INSTRUCTIONS]
        with self.assertRaisesRegex(ValueError, "opcode mismatch"):
            validate_metadata_contract(opcodes + ["ENEW"])
        with self.assertRaisesRegex(ValueError, "opcode mismatch"):
            validate_metadata_contract(opcodes[:-1])

    def test_declared_cycle_effects_match_runtime_returned_e_targets(self) -> None:
        """Tie lifecycle declarations to real dispatch, not a hand-written subset."""

        for case in SUCCESS_CASES:
            with self.subTest(opcode=case.opcode):
                emulator = EPUEmulator()
                emulator.run(case.source)
                event = next(
                    item
                    for item in reversed(emulator.epu.event_log)
                    if item["op"] == case.opcode
                )
                has_e_target = any(
                    str(target).startswith("ER") or "@" in str(target)
                    for target in event["targets"]
                )
                effects = set(METADATA_RULES[case.opcode].cycle_effects)
                self.assertEqual(
                    "target_heat" in effects,
                    has_e_target and INSTRUCTION_HEAT.get(case.opcode, 0.0) > 0,
                )
                self.assertEqual(
                    "returned_e_target_stress_aging" in effects,
                    has_e_target and INSTRUCTION_STRESS[case.opcode] > 0,
                )
                self.assertIn("global_ambient_cooling", effects)
                self.assertIn("global_temperature_aging", effects)


class MetadataPropagationBehaviorTests(unittest.TestCase):
    @staticmethod
    def semantic_step(epu: EPU, source: str) -> None:
        instruction = parse_instruction(source)
        assert instruction is not None
        epu._execute(instruction)

    def test_reset_copy_and_selected_copy_are_complete(self) -> None:
        epu = EPU()
        epu.tick = 23
        epu.er["ER0"] = rich_value()

        self.semantic_step(epu, "EMOV ER1, ER0")
        self.assertEqual(metadata(epu.er["ER1"]), metadata(epu.er["ER0"]))
        self.assertIsNot(epu.er["ER1"], epu.er["ER0"])

        self.semantic_step(epu, "ETRIT TR0, 1")
        self.semantic_step(epu, "ETSEL ER2, TR0, ER3, ER4, ER0")
        self.assertEqual(metadata(epu.er["ER2"]), metadata(epu.er["ER0"]))

        self.semantic_step(epu, "ECONST ER0, 9")
        reset = epu.er["ER0"]
        self.assertEqual(reset.mode, "EWORD")
        self.assertEqual(reset.temperature, 0.0)
        self.assertEqual(reset.noise, 0.0)
        self.assertEqual(reset.health, 1.0)
        self.assertEqual(reset.min_partition, 3)
        self.assertEqual(reset.current_partition, 3)
        self.assertTrue(reset.allow_degrade)
        self.assertIsNone(reset.quantized_state)
        self.assertIsNone(reset.partition)
        self.assertEqual(reset.last_refresh, 23)

    def test_arithmetic_uses_pinned_worst_case_reducer(self) -> None:
        epu = EPU()
        epu.tick = 31
        left = rich_value(2.0)
        right = rich_value(3.0)
        right.temperature = 0.25
        right.noise = 0.09
        right.health = 0.93
        right.min_partition = 243
        right.current_partition = 9
        right.allow_degrade = True
        right.guard_band = 0.004
        epu.er["ER0"] = left
        epu.er["ER1"] = right

        for opcode in ("EADD", "ESUB", "EMUL", "ECONV"):
            with self.subTest(opcode=opcode):
                self.semantic_step(epu, f"{opcode} ER2, ER0, ER1")
                result = epu.er["ER2"]
                self.assertEqual(result.mode, "EWORD")
                self.assertEqual(result.temperature, 0.75)
                self.assertEqual(result.noise, 0.09)
                self.assertEqual(result.health, 0.82)
                self.assertEqual(result.min_partition, 243)
                self.assertEqual(result.current_partition, 9)
                self.assertFalse(result.allow_degrade)
                self.assertEqual(result.guard_band, 0.009)
                self.assertIsNone(result.quantized_state)
                self.assertIsNone(result.partition)
                self.assertEqual(result.last_refresh, 31)

    def test_unary_value_transforms_invalidate_discrete_state_without_losing_wear(self) -> None:
        for source in ("ESHIFT ER1, ER0, 1", "ESCALE ER1, ER0, 0.5"):
            with self.subTest(source=source):
                epu = EPU()
                epu.tick = 29
                original = rich_value()
                epu.er["ER0"] = original
                self.semantic_step(epu, source)
                result = epu.er["ER1"]
                for name in (
                    "mode", "temperature", "noise", "health", "min_partition",
                    "current_partition", "allow_degrade", "guard_band",
                ):
                    self.assertEqual(getattr(result, name), getattr(original, name))
                self.assertIsNone(result.quantized_state)
                self.assertIsNone(result.partition)
                self.assertEqual(result.last_refresh, 29)

    def test_normalize_and_mode_change_do_not_refresh_or_reset_metadata(self) -> None:
        epu = EPU()
        epu.tick = 90
        epu.er["ER0"] = rich_value()
        before = metadata(epu.er["ER0"])

        self.semantic_step(epu, "ENORM ER0")
        self.assertEqual(metadata(epu.er["ER0"]), before)
        self.semantic_step(epu, "EMODE ER0, CONTINUOUS")
        expected = dict(before)
        expected["mode"] = "CONTINUOUS"
        self.assertEqual(metadata(epu.er["ER0"]), expected)

    def test_quantize_and_dequantize_preserve_wear_and_explicitly_clear_state(self) -> None:
        epu = EPU()
        epu.tick = 41
        source = rich_value()
        source.allow_degrade = True
        epu.er["ER0"] = source

        self.semantic_step(epu, "EQUANT ER1, ER0, 27")
        quantized = epu.er["ER1"]
        for name in ("temperature", "noise", "health", "allow_degrade", "guard_band"):
            self.assertEqual(getattr(quantized, name), getattr(source, name))
        self.assertIsNotNone(quantized.quantized_state)
        self.assertEqual(quantized.partition, 27)

        epu.tick = 42
        self.semantic_step(epu, "EDEQ ER2, ER1")
        continuous = epu.er["ER2"]
        self.assertEqual(continuous.mode, "CONTINUOUS")
        self.assertEqual(continuous.noise, source.noise)
        self.assertEqual(continuous.health, source.health)
        self.assertIsNone(continuous.quantized_state)
        self.assertIsNone(continuous.partition)
        self.assertEqual(continuous.last_refresh, 42)

    def test_non_destructive_observation_preserves_wear_and_invalid_mode_is_atomic(self) -> None:
        epu = EPU()
        epu.er["ER0"] = rich_value()
        before = metadata(epu.er["ER0"])
        epu.observe_register("OUT0", "ER0", 8)
        self.assertEqual(metadata(epu.er["ER0"]), before)

        failing = EPU()
        failing.er["ER0"] = rich_value()
        failing.cr["observer_mode"] = "unknown"
        before_state = deepcopy((failing.er, failing.output, failing.tick))
        with self.assertRaises(EPUError) as captured:
            failing.step("EOBS OUT0, ER0")
        self.assertEqual(captured.exception.code, "MODE_ERROR")
        self.assertEqual((failing.er, failing.output, failing.tick), before_state)

    def test_restore_is_type_checked_before_mutation_and_preserves_saved_freshness(self) -> None:
        epu = EPU()
        epu.step("EALLOC EP0, COLD, 2")
        pointer = epu.ep["EP0"]
        assert pointer is not None
        field = epu.fields[pointer.field_id]
        field.last_refresh = 7
        epu.snapshots["valid"] = epu._snapshot("EP0")
        field.last_refresh = 99
        epu._restore("EP0", epu.snapshots["valid"])
        self.assertEqual(field.last_refresh, 7)
        visible = epu.visual_snapshot()["fields"][pointer.field_id]
        self.assertEqual(visible["last_refresh"], 7)
        self.assertEqual(visible["refresh_deadline"], field.refresh_deadline)

        epu.snapshots["broken"] = {
            "kind": "field",
            "field": "not-an-EField",
            "cells": [ECell(value=1.0), ECell(value=2.0)],
        }
        before_cells = deepcopy(epu.banks[pointer.bank_id])
        before_field = deepcopy(field)
        with self.assertRaises(EPUError) as captured:
            epu.step("ERESTORE EP0, broken")
        self.assertEqual(captured.exception.code, "RESTORE_ERROR")
        self.assertEqual(epu.banks[pointer.bank_id], before_cells)
        self.assertEqual(field, before_field)


if __name__ == "__main__":
    unittest.main()
