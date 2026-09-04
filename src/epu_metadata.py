"""Versioned metadata propagation contract for the public EPU ISA.

The contract describes the semantic effect before the common instruction
lifecycle applies heat, global cooling, and target-local aging.  Keeping those
two phases separate makes diagnostic reads auditable without pretending that
an executed cycle is thermodynamically free.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple


METADATA_CONTRACT_SCHEMA_VERSION = 1
METADATA_FIELDS: Tuple[str, ...] = (
    "mode",
    "temperature",
    "noise",
    "health",
    "min_partition",
    "current_partition",
    "allow_degrade",
    "guard_band",
    "quantized_state",
    "partition",
    "last_refresh",
)
PROPAGATION_CLASSES = frozenset({"preserve", "copy", "reset", "derive", "aggregate"})
FIELD_ACTIONS = frozenset(
    {
        "preserve",
        "copy_source",
        "copy_field",
        "copy_selected",
        "reset_default",
        "reset_none",
        "set_eword",
        "set_continuous",
        "set_quantized_mode",
        "set_operand",
        "set_tick",
        "derive_bank_default",
        "derive_max",
        "derive_min",
        "derive_and",
        "derive_requested",
        "derive_allowed",
        "derive_quantized_state",
        "observer_conditional",
        "refresh_transform",
        "restore_snapshot",
    }
)


@dataclass(frozen=True)
class MetadataRule:
    opcode: str
    classification: str
    semantic_scope: str
    fields: Mapping[str, str]
    cycle_effects: Tuple[str, ...]
    note: str

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["fields"] = dict(self.fields)
        payload["cycle_effects"] = list(self.cycle_effects)
        return payload


def _fields(**overrides: str) -> Dict[str, str]:
    result = {name: "preserve" for name in METADATA_FIELDS}
    unknown = set(overrides).difference(METADATA_FIELDS)
    if unknown:
        raise ValueError(f"unknown metadata fields: {', '.join(sorted(unknown))}")
    result.update(overrides)
    return result


def _all(action: str) -> Dict[str, str]:
    return {name: action for name in METADATA_FIELDS}


GLOBAL_CYCLE = ("global_ambient_cooling", "global_temperature_aging")
TARGET_CYCLE = (
    "target_heat",
    "global_ambient_cooling",
    "global_temperature_aging",
    "returned_e_target_stress_aging",
)
AGING_TARGET_CYCLE = (
    "global_ambient_cooling",
    "global_temperature_aging",
    "returned_e_target_stress_aging",
)


def _rule(
    opcode: str,
    classification: str,
    semantic_scope: str,
    fields: Mapping[str, str],
    cycle_effects: Sequence[str],
    note: str,
) -> MetadataRule:
    return MetadataRule(
        opcode,
        classification,
        semantic_scope,
        dict(fields),
        tuple(cycle_effects),
        note,
    )


_reset_word = _all("reset_default")
_reset_word["mode"] = "set_eword"
_reset_word["quantized_state"] = "reset_none"
_reset_word["partition"] = "reset_none"
_reset_word["last_refresh"] = "set_tick"

_arithmetic = _fields(
    mode="set_eword",
    temperature="derive_max",
    noise="derive_max",
    health="derive_min",
    min_partition="derive_max",
    current_partition="derive_min",
    allow_degrade="derive_and",
    guard_band="derive_max",
    quantized_state="reset_none",
    partition="reset_none",
    last_refresh="set_tick",
)

_unary_transform = _all("copy_source")
_unary_transform["quantized_state"] = "reset_none"
_unary_transform["partition"] = "reset_none"
_unary_transform["last_refresh"] = "set_tick"

_quantize = _all("copy_source")
_quantize.update(
    mode="set_quantized_mode",
    min_partition="derive_requested",
    current_partition="derive_allowed",
    quantized_state="derive_quantized_state",
    partition="derive_allowed",
    last_refresh="set_tick",
)

_dequantize = _all("copy_source")
_dequantize.update(
    mode="set_continuous",
    quantized_state="reset_none",
    partition="reset_none",
    last_refresh="set_tick",
)

_allocate = _all("reset_default")
_allocate.update(
    mode="set_operand",
    temperature="derive_bank_default",
    current_partition="derive_bank_default",
    guard_band="derive_bank_default",
    quantized_state="reset_none",
    partition="reset_none",
    last_refresh="set_tick",
)

_qos = _fields(
    min_partition="derive_requested",
    current_partition="derive_allowed",
    allow_degrade="derive_requested",
)

_refresh = _fields(
    temperature="refresh_transform",
    noise="refresh_transform",
    health="refresh_transform",
    current_partition="refresh_transform",
    last_refresh="set_tick",
)


METADATA_RULES: Mapping[str, MetadataRule] = {
    "ECONST": _rule("ECONST", "reset", "ER destination", _reset_word, TARGET_CYCLE, "Fresh E-word metadata; prior destination state is intentionally replaced."),
    "EDIGITS": _rule("EDIGITS", "reset", "ER destination", _reset_word, TARGET_CYCLE, "Fresh E-word metadata; prior destination state is intentionally replaced."),
    "EMOV": _rule("EMOV", "copy", "ER source to ER destination, or EP alias", _all("copy_source"), AGING_TARGET_CYCLE, "ER copies all value metadata. EP copies only pointer identity; field metadata is shared, not duplicated."),
    "EADD": _rule("EADD", "aggregate", "two ER sources to ER destination", _arithmetic, TARGET_CYCLE, "Worst-case environmental/QoS metadata is combined and discrete state is invalidated."),
    "ESUB": _rule("ESUB", "aggregate", "two ER sources to ER destination", _arithmetic, TARGET_CYCLE, "Worst-case environmental/QoS metadata is combined and discrete state is invalidated."),
    "EMUL": _rule("EMUL", "aggregate", "two ER sources to ER destination", _arithmetic, TARGET_CYCLE, "Worst-case environmental/QoS metadata is combined and discrete state is invalidated."),
    "ECONV": _rule("ECONV", "aggregate", "two ER sources to ER destination", _arithmetic, TARGET_CYCLE, "Same metadata reducer as EMUL."),
    "ESHIFT": _rule("ESHIFT", "derive", "ER source to ER destination", _unary_transform, TARGET_CYCLE, "Environmental metadata is copied; the changed value invalidates discrete state."),
    "ESCALE": _rule("ESCALE", "derive", "ER source to ER destination", _unary_transform, TARGET_CYCLE, "Environmental metadata is copied; the changed value invalidates discrete state."),
    "ENORM": _rule("ENORM", "preserve", "ER target", _fields(), AGING_TARGET_CYCLE, "Normalization is not refresh and therefore preserves last_refresh."),
    "EALLOC": _rule("EALLOC", "derive", "new field and EP destination", _allocate, TARGET_CYCLE, "Mode comes from the operand option; physical defaults come from the bank; security identity and geometry are outside value metadata."),
    "ELOAD": _rule("ELOAD", "copy", "field source to ER destination", _all("copy_field"), TARGET_CYCLE, "Copies all field value metadata into the register."),
    "ESTORE": _rule("ESTORE", "copy", "ER source to field destination", {**_all("copy_source"), "last_refresh": "set_tick"}, TARGET_CYCLE, "Copies value metadata; a successful physical write establishes a new field refresh timestamp."),
    "EMODE": _rule("EMODE", "derive", "ER or field target", _fields(mode="set_operand"), AGING_TARGET_CYCLE, "Only interpretive mode changes; stored quantization metadata is retained."),
    "ETRIT": _rule("ETRIT", "reset", "TR destination only", _fields(), GLOBAL_CYCLE, "No E-value metadata is written."),
    "ETCMP": _rule("ETCMP", "aggregate", "two ER reads to TR destination", _fields(), AGING_TARGET_CYCLE, "Semantic read is non-destructive; selected read targets can age in aging-v1."),
    "ETSEL": _rule("ETSEL", "copy", "selected ER source to ER destination", _all("copy_selected"), TARGET_CYCLE, "Copies the complete selected register including discrete and refresh metadata."),
    "ETEMP": _rule("ETEMP", "aggregate", "all ER and fields to output", _fields(), GLOBAL_CYCLE, "Read-only mass-weighted diagnostic; output is derived and E metadata is not directly written."),
    "EQOS": _rule("EQOS", "derive", "ER or field target", _qos, AGING_TARGET_CYCLE, "Only requested/allowed QoS state changes; physical/discrete metadata is preserved."),
    "EQUANT": _rule("EQUANT", "derive", "ER source to ER destination", _quantize, TARGET_CYCLE, "Derives the finite partition and representative while preserving environmental metadata."),
    "EDEQ": _rule("EDEQ", "derive", "quantized ER source to ER destination", _dequantize, TARGET_CYCLE, "Produces a fresh continuous value and clears discrete state."),
    "ECLAMP": _rule("ECLAMP", "preserve", "quantized ER target", _fields(), AGING_TARGET_CYCLE, "Only the word representation is clamped; metadata remains intact."),
    "EOBS": _rule("EOBS", "derive", "ER source and named output", _fields(noise="observer_conditional", health="observer_conditional"), TARGET_CYCLE, "Only destructive observer mode directly changes noise/health; invalid modes fail before output mutation."),
    "EPRINT": _rule("EPRINT", "derive", "ER source and next OUT slot", _fields(noise="observer_conditional", health="observer_conditional"), TARGET_CYCLE, "Same observer contract as EOBS."),
    "ETRACE": _rule("ETRACE", "aggregate", "ER or field read to TRACE output", _fields(), TARGET_CYCLE, "No direct metadata write; the traced target still participates in the normal cycle."),
    "ETHERM": _rule("ETHERM", "aggregate", "ER or field read to named output", _fields(), TARGET_CYCLE, "No direct metadata write; the measured target still participates in the normal cycle."),
    "EREFRESH": _rule("EREFRESH", "derive", "ER or field target", _refresh, GLOBAL_CYCLE, "Refresh transforms physical wear state while preserving mode, QoS request, guard, and discrete identity; instruction stress is zero."),
    "ESCRUB": _rule("ESCRUB", "aggregate", "all fields in selected bank", _refresh, GLOBAL_CYCLE, "Applies the EREFRESH transform atomically after all capabilities are checked."),
    "ESNAP": _rule("ESNAP", "copy", "ER or field to snapshot", _fields(), AGING_TARGET_CYCLE, "Snapshot captures all metadata before lifecycle aging; source metadata is not directly changed."),
    "ERESTORE": _rule("ERESTORE", "copy", "snapshot to compatible ER or field", _all("restore_snapshot"), AGING_TARGET_CYCLE, "Restores value metadata exactly; field authority and geometry are deliberately preserved."),
    "EJMP": _rule("EJMP", "preserve", "control flow only", _fields(), GLOBAL_CYCLE, "No E-value operand."),
    "EJZ": _rule("EJZ", "preserve", "ER condition read", _fields(), AGING_TARGET_CYCLE, "Branch reads do not directly rewrite metadata."),
    "EJNZ": _rule("EJNZ", "preserve", "ER condition read", _fields(), AGING_TARGET_CYCLE, "Branch reads do not directly rewrite metadata."),
    "EJGTZ": _rule("EJGTZ", "preserve", "ER condition read", _fields(), AGING_TARGET_CYCLE, "Branch reads do not directly rewrite metadata."),
    "EJLTZ": _rule("EJLTZ", "preserve", "ER condition read", _fields(), AGING_TARGET_CYCLE, "Branch reads do not directly rewrite metadata."),
    "EJGEZ": _rule("EJGEZ", "preserve", "ER condition read", _fields(), AGING_TARGET_CYCLE, "Branch reads do not directly rewrite metadata."),
    "EJLEZ": _rule("EJLEZ", "preserve", "ER condition read", _fields(), AGING_TARGET_CYCLE, "Branch reads do not directly rewrite metadata."),
    "EHALT": _rule("EHALT", "preserve", "control flow only", _fields(), GLOBAL_CYCLE, "No E-value operand."),
}


def validate_metadata_contract(public_opcodes: Iterable[str]) -> None:
    """Fail closed when the public ISA and metadata contract drift apart."""

    expected = set(public_opcodes)
    actual = set(METADATA_RULES)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"metadata contract opcode mismatch: missing={missing}, extra={extra}")
    for opcode, rule in METADATA_RULES.items():
        if rule.opcode != opcode:
            raise ValueError(f"metadata rule key/opcode mismatch: {opcode}/{rule.opcode}")
        if rule.classification not in PROPAGATION_CLASSES:
            raise ValueError(f"invalid metadata class for {opcode}: {rule.classification}")
        if set(rule.fields) != set(METADATA_FIELDS):
            raise ValueError(f"metadata field coverage mismatch for {opcode}")
        invalid = set(rule.fields.values()).difference(FIELD_ACTIONS)
        if invalid:
            raise ValueError(f"invalid metadata actions for {opcode}: {sorted(invalid)}")


def metadata_contract_payload(public_opcodes: Iterable[str]) -> Dict[str, object]:
    opcodes = tuple(public_opcodes)
    validate_metadata_contract(opcodes)
    return {
        "schema_version": METADATA_CONTRACT_SCHEMA_VERSION,
        "phase": "semantic_effect_before_common_cycle",
        "metadata_fields": list(METADATA_FIELDS),
        "runtime_snapshot_surfaces": {
            "ER": list(METADATA_FIELDS),
            "field": [*METADATA_FIELDS, "refresh_deadline"],
        },
        "propagation_classes": sorted(PROPAGATION_CLASSES),
        "field_actions": sorted(FIELD_ACTIONS),
        "common_cycle_order": [
            "semantic_effect",
            "returned_e_target_heat",
            "thermal_exchange_and_global_ambient_cooling",
            "global_temperature_and_returned_e_target_stress_aging",
            "due_flags",
            "tick",
            "event",
        ],
        "rules": {
            opcode: METADATA_RULES[opcode].to_dict() for opcode in sorted(opcodes)
        },
    }
