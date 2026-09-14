"""Prototype emulator for the fictional E Processing Unit.

This module intentionally keeps the physics simple.  It gives the setting a
working execution model: E-registers, E-memory, assembly-like instructions,
thermal degradation, quantization, refresh, and snapshots.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import e, floor
import re
from typing import Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from ecomputer import EWord, EWordError
from epu_diagnostics import TRegisterValue, compare_trit, temperature_report


PARTITION_STEPS = (3, 9, 27, 81, 243)
MAX_FIELD_CELLS = 4_096
MAX_BANK_CELLS = 4_096
THERMAL_MODEL_SCHEMA_VERSION = 1
AGING_MODEL_SCHEMA_VERSION = 1
E_MODES = frozenset(
    {"CONTINUOUS", "EWORD", "TRIT", "PACKED_TRIT", "COEFFICIENT", "OBSERVED"}
)
NATIVE_OPS = frozenset(
    {
        "ECONST",
        "EDIGITS",
        "EMOV",
        "EALLOC",
        "ELOAD",
        "ESTORE",
        "EADD",
        "ESUB",
        "EMUL",
        "ECONV",
        "ESHIFT",
        "ESCALE",
        "ENORM",
        "EMODE",
        "ETRIT",
        "ETCMP",
        "ETSEL",
        "ETEMP",
        "EQUANT",
        "EDEQ",
        "ECLAMP",
        "EOBS",
        "ETRACE",
        "ETHERM",
        "EQOS",
        "EREFRESH",
        "ESCRUB",
        "ESNAP",
        "ERESTORE",
    }
)
REGISTER_RE = re.compile(r"^ER(?:[0-9]|1[0-5])$")
POINTER_RE = re.compile(r"^EP[0-7]$")
TR_REGISTER_RE = re.compile(r"^TR[0-7]$")

FIELD_CAPABILITIES: FrozenSet[str] = frozenset(
    {
        "read",
        "write",
        "observe_continuous",
        "observe_discrete",
        "change_mode",
        "refresh",
        "snapshot",
        "thermal_control",
    }
)


class EPUError(Exception):
    """Raised when the prototype EPU cannot execute an instruction."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TaskContext:
    """Identity and capabilities for one EPU task.

    The default ``kernel`` context preserves the original unrestricted emulator
    behavior.  Callers that opt into another principal get fail-closed checks at
    E-field and observation boundaries.
    """

    principal: str = "kernel"
    capabilities: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        principal = str(self.principal).strip()
        if not principal:
            raise ValueError("TaskContext principal must not be empty")
        object.__setattr__(self, "principal", principal)
        capabilities = frozenset(self.capabilities)
        if principal == "kernel":
            capabilities = FIELD_CAPABILITIES
        object.__setattr__(self, "capabilities", capabilities)

    @classmethod
    def kernel(cls) -> "TaskContext":
        return cls("kernel", FIELD_CAPABILITIES)

    def allows(self, capability: str) -> bool:
        return self.principal == "kernel" or capability in self.capabilities


@dataclass
class ParsedInstruction:
    op: str
    args: List[str]
    options: Dict[str, str] = field(default_factory=dict)
    source: str = ""


@dataclass
class ECell:
    value: float = 0.0
    temperature: float = 0.0
    noise: float = 0.0
    health: float = 1.0
    last_refresh: int = 0

    def __post_init__(self) -> None:
        self.value = self.value % e


@dataclass
class BankMeta:
    bank_id: str
    kind: str
    cooling_rate: float
    base_guard: float
    base_temperature: float


@dataclass(frozen=True)
class ThermalModelSpec:
    """Versioned coefficients for one deterministic thermal transition model.

    Field thermal mass is measured in cells.  Coupling coefficients are the
    fraction of the distance to a mass-weighted equilibrium traversed in one
    instruction cycle, so values in ``[0, 1]`` cannot overshoot equilibrium.
    """

    model_id: str
    model_version: int
    register_cooling_rate: float
    field_coupling: float
    bank_coupling: float
    ambient_cooling_scale: float
    cell_thermal_mass: float = 1.0

    def __post_init__(self) -> None:
        if self.model_version < 0:
            raise ValueError("thermal model version must be non-negative")
        if self.register_cooling_rate < 0 or self.ambient_cooling_scale < 0:
            raise ValueError("thermal cooling coefficients must be non-negative")
        if not 0 <= self.field_coupling <= 1:
            raise ValueError("field coupling must be between zero and one")
        if not 0 <= self.bank_coupling <= 1:
            raise ValueError("bank coupling must be between zero and one")
        if self.cell_thermal_mass <= 0:
            raise ValueError("cell thermal mass must be positive")

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": THERMAL_MODEL_SCHEMA_VERSION,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "coefficients": {
                "register_cooling_rate": self.register_cooling_rate,
                "field_coupling": self.field_coupling,
                "bank_coupling": self.bank_coupling,
                "ambient_cooling_scale": self.ambient_cooling_scale,
                "cell_thermal_mass": self.cell_thermal_mass,
            },
        }


THERMAL_MODELS: Mapping[str, ThermalModelSpec] = {
    # Exact compatibility model for the original per-node cooling behavior.
    "simple-v0": ThermalModelSpec("simple-v0", 0, 0.005, 0.0, 0.0, 1.0),
    # Deterministic lumped-capacitance model with conservative heat exchange.
    "coupled-v1": ThermalModelSpec("coupled-v1", 1, 0.005, 0.125, 0.025, 1.0),
}
THERMAL_MODEL_ALIASES: Mapping[str, str] = {
    "simple": "simple-v0",
    "coupled": "coupled-v1",
}


@dataclass(frozen=True)
class AgingModelSpec:
    """Versioned coefficients for deterministic noise and health evolution."""

    model_id: str
    model_version: int
    temperature_noise_rate: float
    stress_noise_rate: float
    temperature_health_rate: float
    stress_health_rate: float
    observation_noise_scale: float
    observation_health_loss: float
    refresh_noise_retention: float
    refresh_health_recovery: float
    refresh_health_ceiling: float

    def __post_init__(self) -> None:
        rates = (
            self.temperature_noise_rate,
            self.stress_noise_rate,
            self.temperature_health_rate,
            self.stress_health_rate,
            self.observation_noise_scale,
            self.observation_health_loss,
            self.refresh_health_recovery,
        )
        if self.model_version < 0:
            raise ValueError("aging model version must be non-negative")
        if any(value < 0 for value in rates):
            raise ValueError("aging model rates must be non-negative")
        if not 0 <= self.refresh_noise_retention <= 1:
            raise ValueError("refresh noise retention must be between zero and one")
        if not 0 <= self.refresh_health_ceiling <= 1:
            raise ValueError("refresh health ceiling must be between zero and one")

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": AGING_MODEL_SCHEMA_VERSION,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "deterministic": True,
            "requires_seed": False,
            "coefficients": {
                "temperature_noise_rate": self.temperature_noise_rate,
                "stress_noise_rate": self.stress_noise_rate,
                "temperature_health_rate": self.temperature_health_rate,
                "stress_health_rate": self.stress_health_rate,
                "observation_noise_scale": self.observation_noise_scale,
                "observation_health_loss": self.observation_health_loss,
                "refresh_noise_retention": self.refresh_noise_retention,
                "refresh_health_recovery": self.refresh_health_recovery,
                "refresh_health_ceiling": self.refresh_health_ceiling,
            },
        }


AGING_MODELS: Mapping[str, AgingModelSpec] = {
    # Exact compatibility model: only the pre-existing destructive observation
    # and refresh effects update noise/health.
    "simple-v0": AgingModelSpec(
        "simple-v0", 0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.001, 0.0, 0.0, 1.0
    ),
    # Deterministic, seed-free wear model.  Coefficients are emulator constants,
    # not claims about physical hardware.
    "aging-v1": AgingModelSpec(
        "aging-v1",
        1,
        0.0004,
        0.0002,
        0.00004,
        0.00002,
        1.0,
        0.001,
        0.25,
        0.002,
        0.995,
    ),
}
AGING_MODEL_ALIASES: Mapping[str, str] = {
    "simple": "simple-v0",
    "aging": "aging-v1",
}


# Dimensionless work applied to instruction targets.  Temperature exposure is
# accounted for separately after thermal exchange and cooling.
INSTRUCTION_STRESS: Mapping[str, float] = {
    "ECONST": 0.25,
    "EDIGITS": 0.25,
    "EMOV": 0.1,
    "EALLOC": 0.125,
    "ELOAD": 0.25,
    "ESTORE": 0.25,
    "EADD": 0.5,
    "ESUB": 0.5,
    "EMUL": 1.0,
    "ECONV": 1.0,
    "ESHIFT": 0.375,
    "ESCALE": 0.5,
    "ENORM": 0.25,
    "EMODE": 0.125,
    "ETRIT": 0.125,
    "ETCMP": 0.125,
    "ETSEL": 0.25,
    "ETEMP": 0.125,
    "EQUANT": 0.625,
    "EDEQ": 0.375,
    "ECLAMP": 0.25,
    "EOBS": 0.375,
    "EPRINT": 0.375,
    "ETRACE": 0.125,
    "ETHERM": 0.125,
    "EQOS": 0.125,
    "EREFRESH": 0.0,
    "ESCRUB": 0.0,
    "ESNAP": 0.125,
    "ERESTORE": 0.25,
    "EJMP": 0.0,
    "EJZ": 0.05,
    "EJNZ": 0.05,
    "EJGTZ": 0.05,
    "EJLTZ": 0.05,
    "EJGEZ": 0.05,
    "EJLEZ": 0.05,
    "EHALT": 0.0,
}

# Temperature increment applied to every returned E target before cooling.
# Keeping this table public lets the metadata contract and conformance tests
# detect drift between declared lifecycle effects and executable behavior.
INSTRUCTION_HEAT: Mapping[str, float] = {
    "ECONST": 0.02,
    "EDIGITS": 0.02,
    "EADD": 0.04,
    "ESUB": 0.04,
    "EMUL": 0.08,
    "ECONV": 0.08,
    "ESHIFT": 0.03,
    "ESCALE": 0.04,
    "EQUANT": 0.05,
    "EDEQ": 0.03,
    "EOBS": 0.03,
    "EPRINT": 0.03,
    "EALLOC": 0.01,
    "ELOAD": 0.02,
    "ESTORE": 0.02,
    "ETRACE": 0.01,
    "ETHERM": 0.01,
    "ETSEL": 0.02,
}


@dataclass
class EPointer:
    bank_id: str
    offset: int
    length: int
    field_id: str
    exponent_offset: int = 0
    mode_hint: str = "EWORD"


@dataclass
class EField:
    field_id: str
    bank_id: str
    offset: int
    length: int
    owner: str = "kernel"
    mode: str = "EWORD"
    exponent_offset: int = 0
    sign: int = 1
    min_partition: int = 3
    current_partition: int = 3
    allow_degrade: bool = True
    guard_band: float = 0.002
    temperature: float = 0.0
    noise: float = 0.0
    health: float = 1.0
    quantized_state: Optional[int] = None
    partition: Optional[int] = None
    refresh_deadline: int = 64
    last_refresh: int = 0
    permissions: Set[str] = field(default_factory=lambda: set(FIELD_CAPABILITIES))


@dataclass
class ERegisterValue:
    word: EWord = field(default_factory=EWord.zero)
    mode: str = "EWORD"
    temperature: float = 0.0
    noise: float = 0.0
    health: float = 1.0
    min_partition: int = 3
    current_partition: int = 3
    allow_degrade: bool = True
    guard_band: float = 0.002
    quantized_state: Optional[int] = None
    partition: Optional[int] = None
    last_refresh: int = 0

    def copy(self) -> "ERegisterValue":
        return deepcopy(self)


RegisterOrPointer = Union[ERegisterValue, EPointer]


def parse_instruction(line: str) -> Optional[ParsedInstruction]:
    """Parse one assembly-like instruction line."""

    source = line.rstrip()
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    instruction_part = line
    option_part = ""
    if ";" in line:
        instruction_part, option_part = line.split(";", 1)

    instruction_part = instruction_part.strip()
    if not instruction_part:
        return None

    if " " in instruction_part:
        op, rest = instruction_part.split(None, 1)
        args = [arg.strip() for arg in rest.split(",") if arg.strip()]
    else:
        op = instruction_part
        args = []

    options: Dict[str, str] = {}
    for token in option_part.replace(",", " ").split():
        if "=" in token:
            key, value = token.split("=", 1)
            options[key.strip().lower()] = value.strip()

    return ParsedInstruction(op.upper(), args, options, source)


def parse_program(program: Union[str, Iterable[str]]) -> List[ParsedInstruction]:
    if isinstance(program, str):
        lines = program.splitlines()
    else:
        lines = list(program)

    parsed: List[ParsedInstruction] = []
    for line in lines:
        instruction = parse_instruction(line)
        if instruction is not None:
            parsed.append(instruction)
    return parsed


CycleExecutor = Callable[[ParsedInstruction], Sequence[Union[str, EPointer]]]


class EPU:
    """Executable prototype of the E Processing Unit."""

    def __init__(self, context: Optional[TaskContext] = None) -> None:
        self.er: Dict[str, ERegisterValue] = {
            f"ER{i}": ERegisterValue() for i in range(16)
        }
        self.ep: Dict[str, Optional[EPointer]] = {f"EP{i}": None for i in range(8)}
        self.tr: Dict[str, TRegisterValue] = {
            f"TR{i}": TRegisterValue() for i in range(8)
        }
        self.banks: Dict[str, List[ECell]] = {}
        self.bank_meta: Dict[str, BankMeta] = {}
        self.fields: Dict[str, EField] = {}
        self.snapshots: Dict[str, object] = {}
        self.output: Dict[str, object] = {}
        self.trace: List[str] = []
        self.event_log: List[Dict[str, object]] = []
        self.sr: Set[str] = {"OK"}
        self.cr: Dict[str, object] = {
            "auto_normalize": True,
            "auto_refresh": False,
            "allow_degrade": True,
            "observer_mode": "non_destructive",
            "thermal_model": "simple",
            "aging_model": "simple-v0",
            "exception_policy": "HALT",
        }
        self.tick = 0
        self.next_field_id = 0
        self.last_exception: Optional[EPUError] = None
        self.context = context or TaskContext.kernel()
        self._event_required_capability: Optional[str] = None
        self._event_aging_model: Optional[str] = None
        self._cycle_maintenance: List[str] = []

    def set_context(self, context: TaskContext) -> None:
        """Switch the active task identity without resetting machine state."""

        self.context = context

    def run(
        self, program: Union[str, Iterable[str], Iterable[ParsedInstruction]]
    ) -> Dict[str, object]:
        instructions: Iterable[ParsedInstruction]
        if isinstance(program, str):
            instructions = parse_program(program)
        else:
            items = list(program)
            if not items:
                instructions = []
            elif isinstance(items[0], ParsedInstruction):
                instructions = items  # type: ignore[assignment]
            else:
                instructions = parse_program(items)  # type: ignore[arg-type]

        for instruction in instructions:
            self.step(instruction)
        return dict(self.output)

    def step(self, instruction: Union[str, ParsedInstruction]) -> None:
        self.execute_cycle(instruction)

    def execute_cycle(
        self,
        instruction: Union[str, ParsedInstruction],
        executor: Optional[CycleExecutor] = None,
    ) -> Optional[EPUError]:
        """Execute exactly one instruction through the shared machine cycle.

        Higher-level control instructions use ``executor`` for their semantic
        effect while retaining the same heat, cooling, due-flag, tick, and
        event ordering as native EPU instructions.  A caught warning-policy
        exception is returned so a program runner can advance its PC.
        """

        parsed = parse_instruction(instruction) if isinstance(instruction, str) else instruction
        if parsed is None:
            return None

        before = self.visual_snapshot()
        self.sr = {"OK"}
        targets: List[Union[str, EPointer]] = []
        exception_code: Optional[str] = None
        caught_exception: Optional[EPUError] = None
        thermal_model: Optional[ThermalModelSpec] = None
        aging_model: Optional[AgingModelSpec] = None
        self._event_required_capability = None
        self._event_aging_model = str(self.cr.get("aging_model", "simple-v0"))
        self._cycle_maintenance = []

        try:
            thermal_model = self._thermal_model_spec()
            aging_model = self._aging_model_spec()
            self._event_aging_model = aging_model.model_id
            targets = list(executor(parsed) if executor is not None else self._execute(parsed))
        except (EPUError, EWordError, ValueError, OverflowError) as raw_exc:
            exc = (
                raw_exc
                if isinstance(raw_exc, EPUError)
                else EPUError(
                    "NUMERIC_ERROR"
                    if isinstance(raw_exc, (EWordError, OverflowError))
                    else "BAD_OPERAND",
                    str(raw_exc),
                )
            )
            self.last_exception = exc
            exception_code = exc.code
            caught_exception = exc
            self.sr.discard("OK")
            self.sr.add("EXCEPTION")
            if self.cr.get("exception_policy") == "WARN" and exc.code not in {
                "THERMAL_MODEL_ERROR",
                "AGING_MODEL_ERROR",
            }:
                self.trace.append(str(exc))
            else:
                self._record_event(parsed, before, self.visual_snapshot(), targets, exception_code)
                raise exc from (None if isinstance(raw_exc, EPUError) else raw_exc)

        assert thermal_model is not None
        assert aging_model is not None
        self._apply_heat(parsed.op, targets)
        self._cool_all(thermal_model)
        self._apply_aging(parsed.op, targets, aging_model)
        self._update_due_flags()
        self.tick += 1
        self._record_event(parsed, before, self.visual_snapshot(), targets, exception_code)
        return caught_exception

    def visual_snapshot(self) -> Dict[str, object]:
        """Return a JSON-like snapshot for visualizers and teaching tools."""

        return {
            "tick": self.tick,
            "context": {
                "principal": self.context.principal,
                "capabilities": sorted(self.context.capabilities),
            },
            "sr": sorted(self.sr),
            "er": {name: self._visual_register(value) for name, value in self.er.items()},
            "tr": {name: value.to_dict() for name, value in self.tr.items()},
            "temp": self.temperature_register(),
            "ep": {
                name: self._visual_pointer(pointer)
                for name, pointer in self.ep.items()
                if pointer is not None
            },
            "fields": {
                field_id: self._visual_field(field_value)
                for field_id, field_value in self.fields.items()
            },
            "output": deepcopy(self.output),
        }

    def timeline(self) -> List[Dict[str, object]]:
        """Return a copy of the structured execution event log."""

        return deepcopy(self.event_log)

    def thermal_model_info(self) -> Dict[str, object]:
        """Return the resolved, versioned model and its public coefficients."""

        configured = str(self.cr.get("thermal_model", "simple"))
        spec = self._thermal_model_spec()
        info = spec.to_dict()
        info["configured_as"] = configured
        return info

    def aging_model_info(self) -> Dict[str, object]:
        """Return the resolved, versioned aging model and public coefficients."""

        configured = str(self.cr.get("aging_model", "simple-v0"))
        spec = self._aging_model_spec()
        info = spec.to_dict()
        info["configured_as"] = configured
        return info

    def temperature_register(self) -> Dict[str, object]:
        """Return the derived, read-only TEMP diagnostic register."""

        thermal_configured = str(self.cr.get("thermal_model", "simple")).strip().lower()
        thermal_model = THERMAL_MODEL_ALIASES.get(
            thermal_configured, thermal_configured
        )
        aging_configured = str(self.cr.get("aging_model", "simple-v0")).strip().lower()
        aging_model = AGING_MODEL_ALIASES.get(aging_configured, aging_configured)
        return temperature_report(
            er=self.er,
            fields=self.fields,
            tick=self.tick,
            thermal_model=thermal_model,
            aging_model=aging_model,
        ).to_dict()

    def _execute(self, instruction: ParsedInstruction) -> List[Union[str, EPointer]]:
        op = instruction.op
        args = instruction.args

        if op == "ECONST":
            self._expect_args(op, args, 2)
            self.er[self._er_name(args[0])] = ERegisterValue(
                word=EWord.from_real(float(args[1])),
                mode="EWORD",
                last_refresh=self.tick,
            )
            self.sr.add("NORMALIZED")
            return [args[0]]

        if op == "EDIGITS":
            if len(args) < 2:
                self._fail("BAD_OPERAND", "EDIGITS requires a destination and digits")
            digits: Dict[int, float] = {}
            for pair in args[1:]:
                if ":" not in pair:
                    self._fail("BAD_OPERAND", f"invalid digit pair: {pair}")
                power, digit = pair.split(":", 1)
                digits[int(power)] = float(digit)
            self.er[self._er_name(args[0])] = ERegisterValue(
                word=EWord.from_digits(digits),
                mode="EWORD",
                last_refresh=self.tick,
            )
            self.sr.add("NORMALIZED")
            return [args[0]]

        if op == "EMOV":
            self._expect_args(op, args, 2)
            dst, src = args
            if REGISTER_RE.match(dst):
                self.er[self._er_name(dst)] = self._reg(src).copy()
                return [dst]
            if POINTER_RE.match(dst):
                self.ep[self._ep_name(dst)] = deepcopy(self._ptr(src))
                return [dst]
            self._fail("BAD_OPERAND", f"invalid EMOV destination: {dst}")

        if op == "EALLOC":
            self._expect_args(op, args, 3)
            dst = self._ep_name(args[0])
            bank_id = args[1].upper()
            length = int(args[2])
            mode = instruction.options.get("mode", "EWORD").upper()
            if mode not in E_MODES:
                self._fail("MODE_ERROR", f"unknown E mode: {mode}")
            exponent_offset = int(instruction.options.get("exponent_offset", "0"))
            pointer = self._allocate(bank_id, length, mode, exponent_offset)
            self.ep[dst] = pointer
            return [pointer]

        if op == "ELOAD":
            self._expect_args(op, args, 2)
            dst = self._er_name(args[0])
            pointer = self._ptr(args[1])
            self._require_field_capability(pointer, "read")
            self.er[dst] = self._load(pointer)
            return [dst]

        if op == "ESTORE":
            self._expect_args(op, args, 2)
            pointer = self._ptr(args[0])
            self._require_field_capability(pointer, "write")
            source = self._reg(args[1])
            self._store(pointer, source)
            return [pointer]

        if op in {"EADD", "ESUB", "EMUL", "ECONV"}:
            self._expect_args(op, args, 3)
            dst = self._er_name(args[0])
            left = self._reg(args[1])
            right = self._reg(args[2])
            if op == "EADD":
                word = self._add_words(left.word, right.word)
            elif op == "ESUB":
                word = EWord.from_real(left.word.to_real() - right.word.to_real())
            else:
                word = left.word.multiply(right.word)
            self.er[dst] = ERegisterValue(
                word=word.normalize() if self.cr.get("auto_normalize") else word,
                mode="EWORD",
                temperature=max(left.temperature, right.temperature),
                min_partition=max(left.min_partition, right.min_partition),
                current_partition=min(left.current_partition, right.current_partition),
                allow_degrade=left.allow_degrade and right.allow_degrade,
                guard_band=max(left.guard_band, right.guard_band),
                noise=max(left.noise, right.noise),
                health=min(left.health, right.health),
                last_refresh=self.tick,
            )
            self.sr.add("NORMALIZED")
            return [dst]

        if op == "ESHIFT":
            self._expect_args(op, args, 3)
            dst = self._er_name(args[0])
            source = self._reg(args[1])
            self.er[dst] = ERegisterValue(
                word=source.word.shift(int(args[2])),
                mode=source.mode,
                temperature=source.temperature,
                min_partition=source.min_partition,
                current_partition=source.current_partition,
                allow_degrade=source.allow_degrade,
                guard_band=source.guard_band,
                noise=source.noise,
                health=source.health,
                last_refresh=self.tick,
            )
            return [dst]

        if op == "ESCALE":
            self._expect_args(op, args, 3)
            dst = self._er_name(args[0])
            source = self._reg(args[1])
            self.er[dst] = ERegisterValue(
                word=EWord.from_real(source.word.to_real() * float(args[2])),
                mode=source.mode,
                temperature=source.temperature,
                min_partition=source.min_partition,
                current_partition=source.current_partition,
                allow_degrade=source.allow_degrade,
                guard_band=source.guard_band,
                noise=source.noise,
                health=source.health,
                last_refresh=self.tick,
            )
            self.sr.add("NORMALIZED")
            return [dst]

        if op == "ENORM":
            self._expect_args(op, args, 1)
            target = self._er_name(args[0])
            value = self.er[target]
            value.word = value.word.normalize()
            self.sr.add("NORMALIZED")
            return [target]

        if op == "EMODE":
            self._expect_args(op, args, 2)
            mode = args[1].upper()
            if mode not in E_MODES:
                self._fail("MODE_ERROR", f"unknown E mode: {mode}")
            target = args[0]
            if REGISTER_RE.match(target):
                self._require_capability("change_mode", target)
                self.er[self._er_name(target)].mode = mode
                return [target]
            pointer = self._ptr(target)
            self._require_field_capability(pointer, "change_mode")
            self.fields[pointer.field_id].mode = mode
            pointer.mode_hint = mode
            return [pointer]

        if op == "ETRIT":
            if len(args) < 2:
                self._fail("BAD_OPERAND", "ETRIT requires a destination and lanes")
            destination = self._tr_name(args[0])
            lanes = tuple(int(item) for item in args[1:])
            self.tr[destination] = TRegisterValue(lanes)
            return [destination]

        if op == "ETCMP":
            self._expect_args(op, args, 3)
            destination = self._tr_name(args[0])
            left_name = self._er_name(args[1])
            right_name = self._er_name(args[2])
            epsilon = float(instruction.options.get("epsilon", "1e-12"))
            self._require_capability(
                "observe_discrete", f"{left_name},{right_name}"
            )
            compared = compare_trit(
                self.er[left_name].word.to_real(),
                self.er[right_name].word.to_real(),
                epsilon,
            )
            self.tr[destination] = compared
            return [destination, left_name, right_name]

        if op == "ETSEL":
            self._expect_args(op, args, 5)
            destination = self._er_name(args[0])
            condition = self._tr_name(args[1])
            source_names = tuple(self._er_name(item) for item in args[2:])
            self._require_capability("observe_discrete", condition)
            source = source_names[self.tr[condition].scalar + 1]
            self.er[destination] = self.er[source].copy()
            return [destination, condition, source]

        if op == "ETEMP":
            self._expect_args(op, args, 1)
            self._require_capability("read", "TEMP")
            self.output[args[0]] = self.temperature_register()
            return ["TEMP"]

        if op == "EQUANT":
            self._expect_args(op, args, 3)
            dst = self._er_name(args[0])
            source = self._reg(args[1])
            requested = int(args[2])
            actual = self._allowed_partition(
                requested,
                source.temperature,
                source.guard_band,
                source.allow_degrade,
            )
            cell_value = source.word.to_real() % e
            state = min(actual - 1, int(floor((cell_value / e) * actual)))
            representative = ((state + 0.5) / actual) * e
            self.er[dst] = ERegisterValue(
                word=EWord.from_real(representative),
                mode="TRIT" if actual == 3 else "PACKED_TRIT",
                temperature=source.temperature,
                min_partition=min(requested, actual),
                current_partition=actual,
                allow_degrade=source.allow_degrade,
                guard_band=source.guard_band,
                noise=source.noise,
                health=source.health,
                quantized_state=state,
                partition=actual,
                last_refresh=self.tick,
            )
            self.sr.add("QUANTIZED")
            return [dst]

        if op == "EDEQ":
            self._expect_args(op, args, 2)
            dst = self._er_name(args[0])
            source = self._reg(args[1])
            if source.quantized_state is None or source.partition is None:
                self._fail("MODE_ERROR", "EDEQ requires a quantized register")
            representative = ((source.quantized_state + 0.5) / source.partition) * e
            self.er[dst] = ERegisterValue(
                word=EWord.from_real(representative),
                mode="CONTINUOUS",
                temperature=source.temperature,
                min_partition=source.min_partition,
                current_partition=source.current_partition,
                allow_degrade=source.allow_degrade,
                guard_band=source.guard_band,
                noise=source.noise,
                health=source.health,
                last_refresh=self.tick,
            )
            return [dst]

        if op == "ECLAMP":
            self._expect_args(op, args, 1)
            target = self._er_name(args[0])
            value = self.er[target]
            if value.quantized_state is None or value.partition is None:
                self._fail("MODE_ERROR", "ECLAMP requires a quantized register")
            representative = ((value.quantized_state + 0.5) / value.partition) * e
            value.word = EWord.from_real(representative)
            self.sr.add("QUANTIZED")
            return [target]

        if op == "EOBS":
            self._expect_args(op, args, 2)
            dst = args[0]
            precision = int(instruction.options.get("precision", "12"))
            return self.observe_register(dst, args[1], precision)

        if op == "ETRACE":
            self._expect_args(op, args, 1)
            if REGISTER_RE.match(args[0]):
                self._require_capability("observe_continuous", args[0])
            else:
                self._require_field_capability(self._ptr(args[0]), "observe_continuous")
            line = self.describe(args[0])
            self.trace.append(line)
            self.output.setdefault("TRACE", [])
            assert isinstance(self.output["TRACE"], list)
            self.output["TRACE"].append(line)
            return [args[0]]

        if op == "ETHERM":
            self._expect_args(op, args, 2)
            dst = args[0]
            if REGISTER_RE.match(args[1]):
                self._require_capability("read", args[1])
            else:
                self._require_field_capability(self._ptr(args[1]), "read")
            info = self.thermal_info(args[1])
            self.output[dst] = info
            return [args[1]]

        if op == "EQOS":
            self._expect_args(op, args, 1)
            min_partition = int(instruction.options.get("min_partition", "3"))
            degrade = instruction.options.get("degrade")
            if degrade is not None and degrade.lower() not in {"allow", "deny"}:
                self._fail("BAD_OPERAND", "EQOS degrade must be allow or deny")
            target = args[0]
            if REGISTER_RE.match(target):
                self._require_capability("thermal_control", target)
                value = self.er[self._er_name(target)]
                allow_degrade = (
                    value.allow_degrade if degrade is None else degrade.lower() != "deny"
                )
                current_partition = self._allowed_partition(
                    min_partition,
                    value.temperature,
                    value.guard_band,
                    allow_degrade,
                )
                value.min_partition = min_partition
                value.current_partition = current_partition
                value.allow_degrade = allow_degrade
                return [target]
            pointer = self._ptr(target)
            self._require_field_capability(pointer, "thermal_control")
            field_value = self.fields[pointer.field_id]
            allow_degrade = (
                field_value.allow_degrade if degrade is None else degrade.lower() != "deny"
            )
            current_partition = self._allowed_partition(
                min_partition,
                field_value.temperature,
                field_value.guard_band,
                allow_degrade,
            )
            field_value.min_partition = min_partition
            field_value.current_partition = current_partition
            field_value.allow_degrade = allow_degrade
            return [pointer]

        if op == "EREFRESH":
            self._expect_args(op, args, 1)
            if REGISTER_RE.match(args[0]):
                self._require_capability("refresh", args[0])
            else:
                self._require_field_capability(self._ptr(args[0]), "refresh")
            return [self._refresh(args[0])]

        if op == "ESCRUB":
            self._expect_args(op, args, 1)
            bank_id = args[0].upper()
            self._require_capability("thermal_control", bank_id)
            matching_fields = [
                field_value
                for field_value in self.fields.values()
                if field_value.bank_id == bank_id
            ]
            for field_value in matching_fields:
                pointer = EPointer(
                    field_value.bank_id,
                    field_value.offset,
                    field_value.length,
                    field_value.field_id,
                    field_value.exponent_offset,
                    field_value.mode,
                )
                self._require_field_capability(pointer, "refresh")
            for field_value in matching_fields:
                self._refresh_field(field_value)
            return []

        if op == "ESNAP":
            self._expect_args(op, args, 2)
            name = args[0]
            target = args[1]
            if REGISTER_RE.match(target):
                self._require_capability("snapshot", target)
            else:
                self._require_field_capability(self._ptr(target), "snapshot")
            self.snapshots[name] = self._snapshot(target)
            return [target]

        if op == "ERESTORE":
            self._expect_args(op, args, 2)
            target = args[0]
            name = args[1]
            if name not in self.snapshots:
                self._fail("RESTORE_ERROR", f"unknown snapshot: {name}")
            if REGISTER_RE.match(target):
                self._require_capability("write", target)
            else:
                self._require_field_capability(self._ptr(target), "write")
            self._restore(target, self.snapshots[name])
            return [target]

        self._fail("BAD_OPCODE", f"unknown opcode: {op}")

    def observe_register(self, destination: str, source: str, precision: int = 12) -> List[str]:
        """Observe one register through the task capability boundary."""

        self._require_capability("observe_continuous", source)
        value = self._reg(source)
        observer_mode = str(self.cr.get("observer_mode", "non_destructive"))
        if observer_mode not in {"non_destructive", "destructive"}:
            self._fail("MODE_ERROR", f"unknown observer mode: {observer_mode}")
        self.output[destination] = round(value.word.to_real(), precision)
        if observer_mode == "destructive":
            model = self._aging_model_spec()
            value.noise += (
                value.guard_band
                * (1 + value.temperature)
                * model.observation_noise_scale
            )
            value.health = max(
                0.0, value.health - model.observation_health_loss
            )
        self.sr.add("OBSERVATION_DIRTY")
        return [source]

    def describe(self, target: str) -> str:
        if REGISTER_RE.match(target):
            value = self.er[self._er_name(target)]
            return (
                f"{target} mode={value.mode} value={value.word.format()} "
                f"real={value.word.to_real():.12g} temp={value.temperature:.3f} "
                f"partition={value.current_partition}"
            )
        pointer = self._ptr(target)
        field_value = self.fields[pointer.field_id]
        return (
            f"{target} field={pointer.field_id} bank={pointer.bank_id} "
            f"offset={pointer.offset} length={pointer.length} mode={field_value.mode} "
            f"temp={field_value.temperature:.3f} partition={field_value.current_partition}"
        )

    def thermal_info(self, target: str) -> Dict[str, object]:
        if REGISTER_RE.match(target):
            value = self.er[self._er_name(target)]
            return {
                "temperature": value.temperature,
                "noise": value.noise,
                "q_max": self._max_partition(value.temperature, value.guard_band),
                "current_partition": value.current_partition,
                "health": value.health,
            }
        pointer = self._ptr(target)
        field_value = self.fields[pointer.field_id]
        return {
            "temperature": field_value.temperature,
            "noise": field_value.noise,
            "health": field_value.health,
            "q_max": self._max_partition(field_value.temperature, field_value.guard_band),
            "current_partition": field_value.current_partition,
            "refresh_due": self.tick - field_value.last_refresh >= field_value.refresh_deadline,
        }

    def _record_event(
        self,
        instruction: ParsedInstruction,
        before: Dict[str, object],
        after: Dict[str, object],
        targets: Sequence[Union[str, EPointer]],
        exception_code: Optional[str],
    ) -> None:
        self.event_log.append(
            {
                "tick": before["tick"],
                "op": instruction.op,
                "args": list(instruction.args),
                "options": dict(instruction.options),
                "source": instruction.source,
                "targets": [self._target_label(target) for target in targets],
                "flags": sorted(self.sr),
                "exception": exception_code,
                "principal": self.context.principal,
                "required_capability": self._event_required_capability,
                "aging_model": self._event_aging_model,
                "maintenance": list(self._cycle_maintenance),
                "before": before,
                "after": after,
            }
        )

    def _visual_register(self, value: ERegisterValue) -> Dict[str, object]:
        digits = [
            {"exponent": exponent, "digit": digit}
            for exponent, digit in sorted(value.word.digits.items())
        ]
        return {
            "mode": value.mode,
            "sign": value.word.sign,
            "digits": digits,
            "format": value.word.format(),
            "real": value.word.to_real(),
            "temperature": value.temperature,
            "noise": value.noise,
            "health": value.health,
            "min_partition": value.min_partition,
            "current_partition": value.current_partition,
            "allow_degrade": value.allow_degrade,
            "guard_band": value.guard_band,
            "q_max": self._max_partition(value.temperature, value.guard_band),
            "quantized_state": value.quantized_state,
            "partition": value.partition,
            "last_refresh": value.last_refresh,
        }

    def _visual_pointer(self, pointer: EPointer) -> Dict[str, object]:
        return {
            "bank_id": pointer.bank_id,
            "offset": pointer.offset,
            "length": pointer.length,
            "field_id": pointer.field_id,
            "exponent_offset": pointer.exponent_offset,
            "mode_hint": pointer.mode_hint,
        }

    def _visual_field(self, field_value: EField) -> Dict[str, object]:
        cells = self.banks.get(field_value.bank_id, [])
        cell_slice = cells[field_value.offset : field_value.offset + field_value.length]
        return {
            "bank_id": field_value.bank_id,
            "offset": field_value.offset,
            "length": field_value.length,
            "owner": field_value.owner,
            "permissions": sorted(field_value.permissions),
            "mode": field_value.mode,
            "exponent_offset": field_value.exponent_offset,
            "sign": field_value.sign,
            "min_partition": field_value.min_partition,
            "current_partition": field_value.current_partition,
            "allow_degrade": field_value.allow_degrade,
            "q_max": self._max_partition(field_value.temperature, field_value.guard_band),
            "guard_band": field_value.guard_band,
            "temperature": field_value.temperature,
            "noise": field_value.noise,
            "health": field_value.health,
            "quantized_state": field_value.quantized_state,
            "partition": field_value.partition,
            "last_refresh": field_value.last_refresh,
            "refresh_deadline": field_value.refresh_deadline,
            "refresh_due": self.tick - field_value.last_refresh >= field_value.refresh_deadline,
            "cells": [
                {
                    "index": field_value.offset + index,
                    "value": cell.value,
                    "temperature": cell.temperature,
                    "noise": cell.noise,
                    "health": cell.health,
                }
                for index, cell in enumerate(cell_slice)
            ],
        }

    def _target_label(self, target: Union[str, EPointer]) -> str:
        if isinstance(target, EPointer):
            return f"{target.field_id}@{target.bank_id}[{target.offset}:{target.offset + target.length}]"
        return str(target)

    def _allocate(
        self, bank_id: str, length: int, mode: str, exponent_offset: int
    ) -> EPointer:
        if length <= 0:
            self._fail("MEMORY_ERROR", "EALLOC length must be positive")
        if length > MAX_FIELD_CELLS:
            self._fail(
                "MEMORY_ERROR",
                f"EALLOC field length exceeds {MAX_FIELD_CELLS} cells",
            )
        self._ensure_bank(bank_id)
        bank = self.banks[bank_id]
        if len(bank) + length > MAX_BANK_CELLS:
            self._fail(
                "MEMORY_ERROR",
                f"EALLOC bank capacity exceeds {MAX_BANK_CELLS} cells",
            )
        meta = self.bank_meta[bank_id]
        offset = len(bank)
        for _ in range(length):
            bank.append(ECell(temperature=meta.base_temperature, last_refresh=self.tick))
        field_id = f"F{self.next_field_id}"
        self.next_field_id += 1
        field_value = EField(
            field_id=field_id,
            bank_id=bank_id,
            offset=offset,
            length=length,
            owner=self.context.principal,
            mode=mode,
            exponent_offset=exponent_offset,
            guard_band=meta.base_guard,
            temperature=meta.base_temperature,
            current_partition=self._max_partition(meta.base_temperature, meta.base_guard),
            last_refresh=self.tick,
        )
        self.fields[field_id] = field_value
        return EPointer(bank_id, offset, length, field_id, exponent_offset, mode)

    def _load(self, pointer: EPointer) -> ERegisterValue:
        field_value = self.fields[pointer.field_id]
        bank = self.banks[pointer.bank_id]
        digits: Dict[int, float] = {}
        for index in range(pointer.length):
            cell = bank[pointer.offset + index]
            if cell.value:
                digits[pointer.exponent_offset + index] = cell.value
        return ERegisterValue(
            word=EWord.from_digits(digits, sign=field_value.sign),
            mode=field_value.mode,
            temperature=field_value.temperature,
            min_partition=field_value.min_partition,
            current_partition=field_value.current_partition,
            allow_degrade=field_value.allow_degrade,
            guard_band=field_value.guard_band,
            noise=field_value.noise,
            health=field_value.health,
            quantized_state=field_value.quantized_state,
            partition=field_value.partition,
            last_refresh=field_value.last_refresh,
        )

    def _store(self, pointer: EPointer, value: ERegisterValue) -> None:
        field_value = self.fields[pointer.field_id]
        bank = self.banks[pointer.bank_id]
        normalized = value.word.normalize()
        out_of_range = [
            exponent
            for exponent in normalized.digits
            if not 0 <= exponent - pointer.exponent_offset < pointer.length
        ]
        if out_of_range:
            self._fail(
                "MEMORY_ERROR",
                f"E-word exponents {sorted(out_of_range)} do not fit field "
                f"{pointer.field_id} range",
            )
        for index in range(pointer.length):
            bank[pointer.offset + index].value = 0.0
            bank[pointer.offset + index].temperature = value.temperature
            bank[pointer.offset + index].noise = value.noise
            bank[pointer.offset + index].health = value.health

        for exponent, digit in normalized.digits.items():
            index = exponent - pointer.exponent_offset
            bank[pointer.offset + index].value = digit
        field_value.sign = value.word.sign
        field_value.mode = value.mode
        field_value.temperature = value.temperature
        field_value.min_partition = value.min_partition
        field_value.current_partition = value.current_partition
        field_value.allow_degrade = value.allow_degrade
        field_value.guard_band = value.guard_band
        field_value.noise = value.noise
        field_value.health = value.health
        field_value.quantized_state = value.quantized_state
        field_value.partition = value.partition
        field_value.last_refresh = self.tick
        pointer.mode_hint = value.mode

    def _refresh(self, target: str) -> Union[str, EPointer]:
        aging_model = self._aging_model_spec()
        if REGISTER_RE.match(target):
            name = self._er_name(target)
            value = self.er[name]
            value.word = value.word.normalize()
            value.temperature = max(0.0, value.temperature * 0.45 - 0.02)
            value.noise = max(
                value.guard_band * (1 + value.temperature),
                value.noise * aging_model.refresh_noise_retention,
            )
            value.health = self._refreshed_health(value.health, aging_model)
            value.current_partition = min(
                value.current_partition,
                self._max_partition(value.temperature, value.guard_band),
            )
            value.last_refresh = self.tick
            self.sr.add("NORMALIZED")
            self.sr.discard("REFRESH_DUE")
            return name

        pointer = self._ptr(target)
        self._refresh_field(self.fields[pointer.field_id])
        return pointer

    def _refresh_field(self, field_value: EField) -> None:
        aging_model = self._aging_model_spec()
        pointer = EPointer(
            field_value.bank_id,
            field_value.offset,
            field_value.length,
            field_value.field_id,
            field_value.exponent_offset,
            field_value.mode,
        )
        loaded = self._load(pointer)
        loaded.word = loaded.word.normalize()
        loaded.temperature = max(0.0, field_value.temperature * 0.45 - 0.02)
        loaded.noise = max(
            field_value.guard_band * (1 + loaded.temperature),
            field_value.noise * aging_model.refresh_noise_retention,
        )
        loaded.health = self._refreshed_health(field_value.health, aging_model)
        self._store(pointer, loaded)
        field_value.temperature = loaded.temperature
        field_value.noise = loaded.noise
        field_value.current_partition = min(
            field_value.current_partition,
            self._max_partition(field_value.temperature, field_value.guard_band),
        )
        field_value.last_refresh = self.tick
        for index in range(field_value.length):
            cell = self.banks[field_value.bank_id][field_value.offset + index]
            cell.temperature = field_value.temperature
            cell.noise = field_value.noise
            cell.health = field_value.health
            cell.last_refresh = self.tick
        self.sr.add("NORMALIZED")
        self.sr.discard("REFRESH_DUE")

    def _snapshot(self, target: str) -> object:
        if REGISTER_RE.match(target):
            return {"kind": "register", "value": self.er[self._er_name(target)].copy()}
        pointer = self._ptr(target)
        cells = deepcopy(
            self.banks[pointer.bank_id][pointer.offset : pointer.offset + pointer.length]
        )
        field_value = deepcopy(self.fields[pointer.field_id])
        return {"kind": "field", "pointer": deepcopy(pointer), "field": field_value, "cells": cells}

    def _restore(self, target: str, snapshot: object) -> None:
        if not isinstance(snapshot, Mapping):
            self._fail("RESTORE_ERROR", "invalid snapshot object")
        kind = snapshot.get("kind")
        if REGISTER_RE.match(target) and kind == "register":
            saved_value = snapshot.get("value")
            if not isinstance(saved_value, ERegisterValue):
                self._fail("RESTORE_ERROR", "invalid register snapshot value")
            self.er[self._er_name(target)] = saved_value.copy()
            return
        if POINTER_RE.match(target) and kind == "field":
            pointer = self._ptr(target)
            cells = snapshot.get("cells")
            saved_field = snapshot.get("field")
            if (
                not isinstance(cells, Sequence)
                or isinstance(cells, (str, bytes))
                or any(not isinstance(cell, ECell) for cell in cells)
                or not isinstance(saved_field, EField)
            ):
                self._fail("RESTORE_ERROR", "invalid field snapshot metadata")
            if len(cells) != pointer.length:
                self._fail("RESTORE_ERROR", "snapshot length does not match target field")
            self.banks[pointer.bank_id][pointer.offset : pointer.offset + pointer.length] = deepcopy(
                list(cells)
            )
            field_value = self.fields[pointer.field_id]
            field_value.mode = saved_field.mode
            field_value.sign = saved_field.sign
            field_value.min_partition = saved_field.min_partition
            field_value.current_partition = saved_field.current_partition
            field_value.allow_degrade = saved_field.allow_degrade
            field_value.guard_band = saved_field.guard_band
            field_value.temperature = saved_field.temperature
            field_value.noise = saved_field.noise
            field_value.health = saved_field.health
            field_value.quantized_state = saved_field.quantized_state
            field_value.partition = saved_field.partition
            field_value.last_refresh = saved_field.last_refresh
            return
        self._fail("RESTORE_ERROR", f"cannot restore {kind} snapshot into {target}")

    def _apply_heat(self, op: str, targets: Sequence[Union[str, EPointer]]) -> None:
        heat = INSTRUCTION_HEAT.get(op, 0.0)

        for target in targets:
            if isinstance(target, EPointer):
                self._heat_field(target.field_id, heat)
            elif REGISTER_RE.match(str(target)):
                self.er[self._er_name(str(target))].temperature += heat

    def _heat_field(self, field_id: str, heat: float) -> None:
        field_value = self.fields[field_id]
        field_value.temperature += heat
        for index in range(field_value.length):
            self.banks[field_value.bank_id][field_value.offset + index].temperature += heat

    def _thermal_model_spec(self) -> ThermalModelSpec:
        configured = str(self.cr.get("thermal_model", "simple")).strip().lower()
        model_id = THERMAL_MODEL_ALIASES.get(configured, configured)
        spec = THERMAL_MODELS.get(model_id)
        if spec is None:
            self._fail(
                "THERMAL_MODEL_ERROR",
                f"unknown thermal model {configured!r}; expected one of "
                f"{tuple(sorted(set(THERMAL_MODELS) | set(THERMAL_MODEL_ALIASES)))}",
            )
        return spec

    def _aging_model_spec(self) -> AgingModelSpec:
        configured = str(self.cr.get("aging_model", "simple-v0")).strip().lower()
        model_id = AGING_MODEL_ALIASES.get(configured, configured)
        spec = AGING_MODELS.get(model_id)
        if spec is None:
            self._fail(
                "AGING_MODEL_ERROR",
                f"unknown aging model {configured!r}; expected one of "
                f"{tuple(sorted(set(AGING_MODELS) | set(AGING_MODEL_ALIASES)))}",
            )
        return spec

    @staticmethod
    def _refreshed_health(health: float, model: AgingModelSpec) -> float:
        if health >= model.refresh_health_ceiling:
            return health
        return min(
            model.refresh_health_ceiling,
            health + model.refresh_health_recovery,
        )

    def _apply_aging(
        self,
        op: str,
        targets: Sequence[Union[str, EPointer]],
        model: AgingModelSpec,
    ) -> None:
        """Age all active nodes from post-cooling heat and target-local work.

        The transition is deterministic and uses simultaneous per-node values.
        Coupled thermal models therefore affect neighboring field aging through
        the post-exchange temperature, without a separate stochastic process.
        """

        if model.model_id == "simple-v0":
            return

        stress = INSTRUCTION_STRESS.get(op, 0.0)
        register_targets = {
            self._er_name(str(target))
            for target in targets
            if not isinstance(target, EPointer) and REGISTER_RE.match(str(target))
        }
        field_targets = {
            target.field_id for target in targets if isinstance(target, EPointer)
        }
        field_targets.update(
            self._ptr(str(target)).field_id
            for target in targets
            if not isinstance(target, EPointer) and POINTER_RE.match(str(target))
        )

        for name, value in self.er.items():
            target_stress = stress if name in register_targets else 0.0
            self._age_node(value, value.guard_band, target_stress, model)

        for field_id in sorted(self.fields):
            field_value = self.fields[field_id]
            target_stress = stress if field_id in field_targets else 0.0
            self._age_node(
                field_value,
                field_value.guard_band,
                target_stress,
                model,
            )
            for index in range(field_value.length):
                cell = self.banks[field_value.bank_id][field_value.offset + index]
                cell.noise = field_value.noise
                cell.health = field_value.health

    @staticmethod
    def _age_node(
        node: Union[ERegisterValue, EField],
        guard_band: float,
        stress: float,
        model: AgingModelSpec,
    ) -> None:
        temperature = max(0.0, node.temperature)
        node.noise += guard_band * (
            model.temperature_noise_rate * temperature
            + model.stress_noise_rate * stress
        )
        health_loss = (
            model.temperature_health_rate * temperature
            + model.stress_health_rate * stress
        )
        node.health = max(0.0, node.health - health_loss)

    @staticmethod
    def _field_thermal_mass(
        field_value: EField, model: ThermalModelSpec
    ) -> float:
        return field_value.length * model.cell_thermal_mass

    def _apply_thermal_coupling(self, model: ThermalModelSpec) -> None:
        """Exchange field heat without creating or destroying thermal energy.

        The field temperatures are updated from simultaneous, mass-weighted
        equilibria.  Same-bank exchange runs first and preserves each bank's
        mean; inter-bank exchange then preserves the machine-wide mean.  Cells
        mirror their field node after the exchange.
        """

        ordered_fields = [self.fields[name] for name in sorted(self.fields)]
        if not ordered_fields:
            return

        if model.field_coupling:
            by_bank: Dict[str, List[EField]] = {}
            for field_value in ordered_fields:
                by_bank.setdefault(field_value.bank_id, []).append(field_value)
            for bank_id in sorted(by_bank):
                members = by_bank[bank_id]
                total_mass = sum(self._field_thermal_mass(item, model) for item in members)
                mean = sum(
                    item.temperature * self._field_thermal_mass(item, model)
                    for item in members
                ) / total_mass
                updated = {
                    item.field_id: item.temperature
                    + model.field_coupling * (mean - item.temperature)
                    for item in members
                }
                for item in members:
                    item.temperature = updated[item.field_id]

        if model.bank_coupling:
            by_bank = {}
            for field_value in ordered_fields:
                by_bank.setdefault(field_value.bank_id, []).append(field_value)
            bank_mass: Dict[str, float] = {}
            bank_mean: Dict[str, float] = {}
            for bank_id in sorted(by_bank):
                members = by_bank[bank_id]
                mass = sum(self._field_thermal_mass(item, model) for item in members)
                bank_mass[bank_id] = mass
                bank_mean[bank_id] = sum(
                    item.temperature * self._field_thermal_mass(item, model)
                    for item in members
                ) / mass
            total_mass = sum(bank_mass.values())
            machine_mean = sum(
                bank_mean[bank_id] * bank_mass[bank_id]
                for bank_id in sorted(bank_mean)
            ) / total_mass
            bank_delta = {
                bank_id: model.bank_coupling * (machine_mean - bank_mean[bank_id])
                for bank_id in sorted(bank_mean)
            }
            for field_value in ordered_fields:
                field_value.temperature += bank_delta[field_value.bank_id]

        for field_value in ordered_fields:
            for index in range(field_value.length):
                self.banks[field_value.bank_id][
                    field_value.offset + index
                ].temperature = field_value.temperature

    def _cool_all(self, model: Optional[ThermalModelSpec] = None) -> None:
        model = model or self._thermal_model_spec()
        if model.field_coupling or model.bank_coupling:
            self._apply_thermal_coupling(model)
        for name, value in self.er.items():
            if name == "ER0" or value.temperature > 0.0:
                value.temperature = max(
                    0.0, value.temperature - model.register_cooling_rate
                )
        for bank_id, cells in self.banks.items():
            meta = self.bank_meta[bank_id]
            for cell in cells:
                cell.temperature = max(
                    meta.base_temperature,
                    cell.temperature - meta.cooling_rate * model.ambient_cooling_scale,
                )
        for field_value in self.fields.values():
            meta = self.bank_meta[field_value.bank_id]
            field_value.temperature = max(
                meta.base_temperature,
                field_value.temperature - meta.cooling_rate * model.ambient_cooling_scale,
            )

    def _update_due_flags(self) -> None:
        auto_refresh = bool(self.cr.get("auto_refresh"))
        refresh_due = False
        thermal_warn = False
        for name, value in self.er.items():
            if self.tick - value.last_refresh >= 64:
                if auto_refresh:
                    self._refresh(name)
                    self._cycle_maintenance.append(f"auto_refresh:{name}")
                else:
                    refresh_due = True
            if value.temperature > 1.0:
                thermal_warn = True
        for field_value in self.fields.values():
            if self.tick - field_value.last_refresh >= field_value.refresh_deadline:
                if auto_refresh:
                    self._refresh_field(field_value)
                    self._cycle_maintenance.append(
                        f"auto_refresh:{field_value.field_id}"
                    )
                else:
                    refresh_due = True
            if field_value.temperature > 1.0:
                thermal_warn = True
        if refresh_due:
            self.sr.add("REFRESH_DUE")
        else:
            self.sr.discard("REFRESH_DUE")
        if thermal_warn:
            self.sr.add("THERMAL_WARN")
        else:
            self.sr.discard("THERMAL_WARN")

    def _ensure_bank(self, bank_id: str) -> None:
        if bank_id in self.banks:
            return
        kind = bank_id.upper()
        if kind == "COLD":
            meta = BankMeta(bank_id, kind, cooling_rate=0.04, base_guard=0.002, base_temperature=0.05)
        elif kind == "ARCHIVE":
            meta = BankMeta(bank_id, kind, cooling_rate=0.03, base_guard=0.003, base_temperature=0.1)
        elif kind == "SACRED":
            meta = BankMeta(bank_id, kind, cooling_rate=0.05, base_guard=0.0015, base_temperature=0.02)
        else:
            meta = BankMeta(bank_id, "WORK", cooling_rate=0.015, base_guard=0.006, base_temperature=0.25)
        self.bank_meta[bank_id] = meta
        self.banks[bank_id] = []

    def _allowed_partition(
        self, requested: int, temperature: float, guard_band: float, allow_degrade: bool
    ) -> int:
        if requested not in PARTITION_STEPS:
            self._fail(
                "BAD_OPERAND",
                f"partition must be one of {PARTITION_STEPS}, got {requested}",
            )
        if guard_band <= 0:
            self._fail("GUARD_BAND_ERROR", "guard band must be positive")
        q_max = self._max_partition(temperature, guard_band)
        if requested <= q_max:
            return requested
        if not allow_degrade:
            self._fail(
                "THERMAL_PRECISION_ERROR",
                f"requested partition {requested} exceeds safe partition {q_max}",
            )
        degraded = max(step for step in PARTITION_STEPS if step <= q_max)
        self.sr.add("DEGRADED")
        return min(requested, degraded)

    def _max_partition(self, temperature: float, guard_band: float) -> int:
        raw = max(3, int(floor(e / (2 * guard_band * (1 + max(0.0, temperature))))))
        allowed = 3
        for step in PARTITION_STEPS:
            if step <= raw:
                allowed = step
        return allowed

    def _add_words(self, left: EWord, right: EWord) -> EWord:
        if left.sign == right.sign:
            return left.add_same_sign(right)
        return EWord.from_real(left.to_real() + right.to_real())

    def _reg(self, name: str) -> ERegisterValue:
        return self.er[self._er_name(name)]

    def _require_capability(self, capability: str, resource: str) -> None:
        self._event_required_capability = capability
        if self.context.allows(capability):
            return
        self._fail(
            "PERMISSION_ERROR",
            f"principal {self.context.principal!r} lacks capability "
            f"{capability!r} for {resource}",
        )

    def _require_field_capability(self, pointer: EPointer, capability: str) -> None:
        self._event_required_capability = capability
        field_value = self.fields[pointer.field_id]
        if self.context.principal == "kernel" or self.context.principal == field_value.owner:
            return
        if capability in self.context.capabilities and capability in field_value.permissions:
            return
        self._fail(
            "PERMISSION_ERROR",
            f"principal {self.context.principal!r} lacks capability "
            f"{capability!r} for field {field_value.field_id} owned by "
            f"{field_value.owner!r}",
        )

    def _ptr(self, name: str) -> EPointer:
        pointer = self.ep[self._ep_name(name)]
        if pointer is None:
            self._fail("MEMORY_ERROR", f"unallocated pointer register: {name}")
        return pointer

    def _er_name(self, name: str) -> str:
        name = name.upper()
        if not REGISTER_RE.match(name):
            self._fail("BAD_OPERAND", f"expected E register, got {name}")
        return name

    def _ep_name(self, name: str) -> str:
        name = name.upper()
        if not POINTER_RE.match(name):
            self._fail("BAD_OPERAND", f"expected E pointer register, got {name}")
        return name

    def _tr_name(self, name: str) -> str:
        name = name.upper()
        if not TR_REGISTER_RE.match(name):
            self._fail("BAD_OPERAND", f"expected T register, got {name}")
        return name

    def _expect_args(self, op: str, args: Sequence[str], count: int) -> None:
        if len(args) != count:
            self._fail("BAD_OPERAND", f"{op} expects {count} operands, got {len(args)}")

    def _fail(self, code: str, message: str) -> None:
        raise EPUError(code, message)
