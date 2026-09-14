"""Machine-readable EPU instruction reference."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List

from epu import (
    AGING_MODEL_ALIASES,
    AGING_MODELS,
    AGING_MODEL_SCHEMA_VERSION,
    INSTRUCTION_STRESS,
    THERMAL_MODEL_ALIASES,
    THERMAL_MODELS,
    THERMAL_MODEL_SCHEMA_VERSION,
)
from epu_diagnostics import DIAGNOSTIC_SCHEMA_VERSION, MAX_TRIT_LANES
from epu_metadata import metadata_contract_payload


@dataclass(frozen=True)
class InstructionSpec:
    opcode: str
    operands: List[str]
    group: str
    summary: str
    e_behavior: str
    options: Dict[str, str]
    flags: List[str]
    example: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


INSTRUCTIONS: List[InstructionSpec] = [
    InstructionSpec("ECONST", ["ERdst", "real"], "word", "Load a real value as an E-word.", "Converts the real number into continuous e^k digits and normalizes it.", {}, ["NORMALIZED"], "ECONST ER0, 12.5"),
    InstructionSpec("EDIGITS", ["ERdst", "power:digit", "..."], "word", "Load explicit E digits.", "Creates an E-word from continuous digits where each digit is interpreted at e^power.", {}, ["NORMALIZED"], "EDIGITS ER0, 0:1.5, 1:0.25"),
    InstructionSpec("EMOV", ["dst", "src"], "word", "Copy an E register or E pointer.", "Preserves E-word mode, heat, partition, and pointer field identity.", {}, [], "EMOV ER1, ER0"),
    InstructionSpec("EADD", ["ERdst", "ERa", "ERb"], "arithmetic", "Add two E-words.", "Carries are resolved in base e and the result is normalized when auto-normalize is enabled.", {}, ["NORMALIZED"], "EADD ER2, ER0, ER1"),
    InstructionSpec("ESUB", ["ERdst", "ERa", "ERb"], "arithmetic", "Subtract two E-words.", "Returns to the E-word representation after real-valued subtraction.", {}, ["NORMALIZED"], "ESUB ER2, ER0, ER1"),
    InstructionSpec("EMUL", ["ERdst", "ERa", "ERb"], "arithmetic", "Multiply two E-words.", "Convolves e^k digits, heats the destination more than addition, and normalizes.", {}, ["NORMALIZED"], "EMUL ER2, ER0, ER1"),
    InstructionSpec("ECONV", ["ERdst", "ERa", "ERb"], "arithmetic", "Convolution-style multiply alias.", "Uses the same E-digit multiplication path as EMUL for experiments that name convolution explicitly.", {}, ["NORMALIZED"], "ECONV ER2, ER0, ER1"),
    InstructionSpec("ESHIFT", ["ERdst", "ERsrc", "power"], "arithmetic", "Shift an E-word by e^power.", "Moves digit exponents without changing the digit values.", {}, [], "ESHIFT ER3, ER2, 1"),
    InstructionSpec("ESCALE", ["ERdst", "ERsrc", "factor"], "arithmetic", "Scale an E-word by a real factor.", "Re-encodes the scaled real value as normalized E digits.", {}, ["NORMALIZED"], "ESCALE ER1, ER0, 0.5"),
    InstructionSpec("ENORM", ["ERtarget"], "word", "Normalize an E register.", "Applies E-carry so digits fall back into the valid continuous range.", {}, ["NORMALIZED"], "ENORM ER0"),
    InstructionSpec("EALLOC", ["EPdst", "bank", "length"], "memory", "Allocate an E field in a memory bank.", "Bank kind controls base temperature, guard band, and cooling rate; the active task principal becomes owner.", {"mode": "EWORD by default", "exponent_offset": "0 by default"}, [], "EALLOC EP0, COLD, 4 ; mode=EWORD"),
    InstructionSpec("ELOAD", ["ERdst", "EPsrc"], "memory", "Load an E field into a register.", "Reconstructs an E-word from field cells and preserves field mode/temperature.", {}, [], "ELOAD ER1, EP0"),
    InstructionSpec("ESTORE", ["EPdst", "ERsrc"], "memory", "Store a register into an E field.", "Writes normalized E digits into continuous E cells and copies thermal/partition state.", {}, [], "ESTORE EP0, ER1"),
    InstructionSpec("EMODE", ["target", "mode"], "mode", "Set register or field mode.", "Changes interpretive mode without changing the underlying continuous digits.", {}, [], "EMODE ER0, CONTINUOUS"),
    InstructionSpec("ETRIT", ["TRdst", "lane", "..."], "ternary", "Load balanced-ternary lanes.", "Stores one to 27 exact lanes, each -1, 0, or +1.", {}, [], "ETRIT TR0, -1, 0, 1"),
    InstructionSpec("ETCMP", ["TRdst", "ERa", "ERb"], "ternary", "Compare two E registers into a trit.", "Writes -1, 0, or +1 using a finite non-negative epsilon.", {"epsilon": "1e-12 by default"}, [], "ETCMP TR0, ER0, ER1 ; epsilon=1e-12"),
    InstructionSpec("ETSEL", ["ERdst", "TRcond", "ERneg", "ERzero", "ERpos"], "ternary", "Select an E register by trit sign.", "Copies the complete negative, zero, or positive source metadata according to the first lane.", {}, [], "ETSEL ER4, TR0, ER1, ER2, ER3"),
    InstructionSpec("ETEMP", ["name"], "diagnostic", "Emit the read-only TEMP aggregate.", "Reports mass-weighted heat, hottest target, refresh pressure, health, noise, and active model identifiers.", {}, [], "ETEMP OUT_DIAGNOSTICS"),
    InstructionSpec("EQOS", ["target"], "thermal", "Set quality-of-service constraints.", "Requests a target-local minimum partition and degradation policy; high heat may degrade to the safe partition.", {"min_partition": "3 by default", "degrade": "allow or deny"}, ["DEGRADED"], "EQOS ER0 ; min_partition=243 degrade=allow"),
    InstructionSpec("EQUANT", ["ERdst", "ERsrc", "partition"], "quantization", "Quantize an E-word into a finite partition.", "Maps the value modulo e into a representative discrete state; heat can reduce the partition.", {}, ["QUANTIZED", "DEGRADED"], "EQUANT ER1, ER0, 243"),
    InstructionSpec("EDEQ", ["ERdst", "ERsrc"], "quantization", "Read a quantized representative back as continuous.", "Expands the stored quantized state into the center of its E partition.", {}, [], "EDEQ ER2, ER1"),
    InstructionSpec("ECLAMP", ["ERtarget"], "quantization", "Clamp a quantized register to its representative.", "Forces the E-word value to the current quantized partition representative.", {}, ["QUANTIZED"], "ECLAMP ER1"),
    InstructionSpec("EOBS", ["name", "ERsrc"], "observation", "Observe a register into named output.", "Observation dirties the state and records rounded real output.", {"precision": "12 by default"}, ["OBSERVATION_DIRTY"], "EOBS OUT0, ER0 ; precision=8"),
    InstructionSpec("EPRINT", ["ERsrc"], "control", "Observe into the next OUTn slot.", "Compiler-friendly observation pseudo-instruction handled by the high-level emulator.", {"precision": "8 by default"}, ["OBSERVATION_DIRTY"], "EPRINT ER0 ; precision=8"),
    InstructionSpec("ETRACE", ["target"], "observation", "Emit a textual description of a register or field.", "Reports mode, E digits/field metadata, heat, and partition for debugging.", {}, [], "ETRACE EP0"),
    InstructionSpec("ETHERM", ["name", "target"], "thermal", "Emit thermal information.", "Reports temperature, noise, current partition, and safe q_max.", {}, [], "ETHERM OUT_THERMAL, ER0"),
    InstructionSpec("EREFRESH", ["target"], "thermal", "Refresh a register or field.", "Normalizes, cools, updates noise, and clears refresh pressure.", {}, ["NORMALIZED"], "EREFRESH ER0"),
    InstructionSpec("ESCRUB", ["bank"], "thermal", "Refresh every field in a bank.", "Applies field refresh across a memory bank to reduce heat/noise pressure.", {}, ["NORMALIZED"], "ESCRUB COLD"),
    InstructionSpec("ESNAP", ["name", "target"], "snapshot", "Save a register or field snapshot.", "Captures E digits, field cells, thermal state, and partition metadata.", {}, [], "ESNAP safe0, EP0"),
    InstructionSpec("ERESTORE", ["target", "name"], "snapshot", "Restore a saved snapshot.", "Restores captured E state into a compatible register or field.", {}, [], "ERESTORE EP0, safe0"),
    InstructionSpec("EJMP", ["label"], "control", "Jump to a label.", "High-level emulator control flow; does not itself heat E state.", {}, [], "EJMP loop"),
    InstructionSpec("EJZ", ["ERsrc", "label"], "control", "Jump when value is zero.", "Branches on the real value decoded from an E-word using a small epsilon.", {}, [], "EJZ ER0, done"),
    InstructionSpec("EJNZ", ["ERsrc", "label"], "control", "Jump when value is not zero.", "Branches on non-zero decoded E-word value.", {}, [], "EJNZ ER0, loop"),
    InstructionSpec("EJGTZ", ["ERsrc", "label"], "control", "Jump when value is greater than zero.", "Branches on decoded E-word sign.", {}, [], "EJGTZ ER3, heat"),
    InstructionSpec("EJLTZ", ["ERsrc", "label"], "control", "Jump when value is less than zero.", "Branches on decoded E-word sign.", {}, [], "EJLTZ ER0, negative"),
    InstructionSpec("EJGEZ", ["ERsrc", "label"], "control", "Jump when value is greater than or equal to zero.", "Branches on decoded E-word sign.", {}, [], "EJGEZ ER0, nonnegative"),
    InstructionSpec("EJLEZ", ["ERsrc", "label"], "control", "Jump when value is less than or equal to zero.", "Branches on decoded E-word sign.", {}, [], "EJLEZ ER0, nonpositive"),
    InstructionSpec("EHALT", [], "control", "Stop execution.", "High-level emulator halt marker.", {}, [], "EHALT"),
]


def instruction_specs() -> List[InstructionSpec]:
    return list(INSTRUCTIONS)


def spec_payload() -> Dict[str, object]:
    public_opcodes = [instruction.opcode for instruction in INSTRUCTIONS]
    return {
        "runtime_schema_version": 1,
        "registers": {
            "ER": 16,
            "TR": 8,
            "TR_max_lanes": MAX_TRIT_LANES,
            "TR_encoding": "balanced",
            "EP": 8,
            "TEMP": "read-only derived aggregate",
        },
        "diagnostics": {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "snapshot_keys": ["tr", "temp"],
            "temp_thermal_mass": {"ER": 1, "field": "cell length"},
        },
        "partition_steps": [3, 9, 27, 81, 243],
        "banks": {
            "WORK": "default warmer bank",
            "COLD": "cooler work bank",
            "ARCHIVE": "stable medium-cold bank",
            "SACRED": "coldest low-guard bank",
        },
        "thermal_models": {
            "schema_version": THERMAL_MODEL_SCHEMA_VERSION,
            "default": "simple",
            "aliases": dict(THERMAL_MODEL_ALIASES),
            "models": {
                model_id: model.to_dict()
                for model_id, model in sorted(THERMAL_MODELS.items())
            },
        },
        "aging_models": {
            "schema_version": AGING_MODEL_SCHEMA_VERSION,
            "default": "simple-v0",
            "aliases": dict(AGING_MODEL_ALIASES),
            "instruction_stress": dict(sorted(INSTRUCTION_STRESS.items())),
            "models": {
                model_id: model.to_dict()
                for model_id, model in sorted(AGING_MODELS.items())
            },
        },
        "task_capabilities": [
            "read",
            "write",
            "observe_continuous",
            "observe_discrete",
            "change_mode",
            "refresh",
            "snapshot",
            "thermal_control",
        ],
        "instruction_lifecycle": [
            "semantic_effect",
            "heat",
            "thermal_exchange",
            "ambient_cooling",
            "aging",
            "due_flags",
            "tick",
            "event",
        ],
        "metadata_contract": metadata_contract_payload(public_opcodes),
        "instructions": [instruction.to_dict() for instruction in INSTRUCTIONS],
    }


def grouped_specs() -> Dict[str, List[InstructionSpec]]:
    groups: Dict[str, List[InstructionSpec]] = {}
    for instruction in INSTRUCTIONS:
        groups.setdefault(instruction.group, []).append(instruction)
    return groups
