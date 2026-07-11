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
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from ecomputer import EWord, EWordError


PARTITION_STEPS = (3, 9, 27, 81, 243)
REGISTER_RE = re.compile(r"^ER(?:[0-9]|1[0-5])$")
POINTER_RE = re.compile(r"^EP[0-7]$")


class EPUError(Exception):
    """Raised when the prototype EPU cannot execute an instruction."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


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
    guard_band: float = 0.002
    temperature: float = 0.0
    refresh_deadline: int = 64
    last_refresh: int = 0
    permissions: Set[str] = field(
        default_factory=lambda: {
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


@dataclass
class ERegisterValue:
    word: EWord = field(default_factory=EWord.zero)
    mode: str = "EWORD"
    temperature: float = 0.0
    noise: float = 0.0
    health: float = 1.0
    min_partition: int = 3
    current_partition: int = 3
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


class EPU:
    """Executable prototype of the E Processing Unit."""

    def __init__(self) -> None:
        self.er: Dict[str, ERegisterValue] = {
            f"ER{i}": ERegisterValue() for i in range(16)
        }
        self.ep: Dict[str, Optional[EPointer]] = {f"EP{i}": None for i in range(8)}
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
            "exception_policy": "HALT",
        }
        self.tick = 0
        self.next_field_id = 0
        self.last_exception: Optional[EPUError] = None

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
        parsed = parse_instruction(instruction) if isinstance(instruction, str) else instruction
        if parsed is None:
            return

        before = self.visual_snapshot()
        self.sr = {"OK"}
        targets: List[Union[str, EPointer]] = []
        exception_code: Optional[str] = None

        try:
            targets = self._execute(parsed)
        except (EPUError, EWordError, OverflowError) as caught:
            exc = (
                caught
                if isinstance(caught, EPUError)
                else EPUError("NUMERIC_ERROR", str(caught))
            )
            self.last_exception = exc
            exception_code = exc.code
            self.sr.discard("OK")
            self.sr.add("EXCEPTION")
            if self.cr.get("exception_policy") == "WARN":
                self.trace.append(str(exc))
            else:
                self._record_event(parsed, before, self.visual_snapshot(), targets, exception_code)
                raise exc

        self._apply_heat(parsed.op, targets)
        self._cool_all()
        self._update_due_flags()
        self.tick += 1
        self._record_event(parsed, before, self.visual_snapshot(), targets, exception_code)

    def visual_snapshot(self) -> Dict[str, object]:
        """Return a JSON-like snapshot for visualizers and teaching tools."""

        return {
            "tick": self.tick,
            "sr": sorted(self.sr),
            "er": {name: self._visual_register(value) for name, value in self.er.items()},
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
            exponent_offset = int(instruction.options.get("exponent_offset", "0"))
            pointer = self._allocate(bank_id, length, mode, exponent_offset)
            self.ep[dst] = pointer
            return [pointer]

        if op == "ELOAD":
            self._expect_args(op, args, 2)
            dst = self._er_name(args[0])
            pointer = self._ptr(args[1])
            self.er[dst] = self._load(pointer)
            return [dst]

        if op == "ESTORE":
            self._expect_args(op, args, 2)
            pointer = self._ptr(args[0])
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
                last_refresh=self.tick,
            )
            self.sr.add("NORMALIZED")
            return [dst]

        if op == "ENORM":
            self._expect_args(op, args, 1)
            target = self._er_name(args[0])
            value = self.er[target]
            value.word = value.word.normalize()
            value.last_refresh = self.tick
            self.sr.add("NORMALIZED")
            return [target]

        if op == "EMODE":
            self._expect_args(op, args, 2)
            mode = args[1].upper()
            target = args[0]
            if REGISTER_RE.match(target):
                self.er[self._er_name(target)].mode = mode
                return [target]
            pointer = self._ptr(target)
            self.fields[pointer.field_id].mode = mode
            pointer.mode_hint = mode
            return [pointer]

        if op == "EQUANT":
            self._expect_args(op, args, 3)
            dst = self._er_name(args[0])
            source = self._reg(args[1])
            requested = int(args[2])
            actual = self._allowed_partition(
                requested,
                source.temperature,
                source.guard_band,
                bool(self.cr.get("allow_degrade")),
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
                last_refresh=self.tick,
            )
            return [dst]

        if op == "ECLAMP":
            self._expect_args(op, args, 1)
            target = self._er_name(args[0])
            value = self.er[target]
            if value.quantized_state is not None and value.partition is not None:
                representative = ((value.quantized_state + 0.5) / value.partition) * e
                value.word = EWord.from_real(representative)
            self.sr.add("QUANTIZED")
            return [target]

        if op == "EOBS":
            self._expect_args(op, args, 2)
            dst = args[0]
            source = self._reg(args[1])
            precision = int(instruction.options.get("precision", "12"))
            observed = round(source.word.to_real(), precision)
            self.output[dst] = observed
            self.sr.add("OBSERVATION_DIRTY")
            return [args[1]]

        if op == "ETRACE":
            self._expect_args(op, args, 1)
            line = self.describe(args[0])
            self.trace.append(line)
            self.output.setdefault("TRACE", [])
            assert isinstance(self.output["TRACE"], list)
            self.output["TRACE"].append(line)
            return [args[0]]

        if op == "ETHERM":
            self._expect_args(op, args, 2)
            dst = args[0]
            info = self.thermal_info(args[1])
            self.output[dst] = info
            return [args[1]]

        if op == "EQOS":
            if not args:
                self._fail("BAD_OPERAND", "EQOS requires a target")
            min_partition = int(instruction.options.get("min_partition", "3"))
            degrade = instruction.options.get("degrade")
            target = args[0]
            if degrade is not None:
                self.cr["allow_degrade"] = degrade.lower() != "deny"
            if REGISTER_RE.match(target):
                value = self.er[self._er_name(target)]
                value.min_partition = min_partition
                value.current_partition = self._allowed_partition(
                    min_partition,
                    value.temperature,
                    value.guard_band,
                    bool(self.cr.get("allow_degrade")),
                )
                return [target]
            pointer = self._ptr(target)
            field_value = self.fields[pointer.field_id]
            field_value.min_partition = min_partition
            field_value.current_partition = self._allowed_partition(
                min_partition,
                field_value.temperature,
                field_value.guard_band,
                bool(self.cr.get("allow_degrade")),
            )
            return [pointer]

        if op == "EREFRESH":
            self._expect_args(op, args, 1)
            return [self._refresh(args[0])]

        if op == "ESCRUB":
            self._expect_args(op, args, 1)
            bank_id = args[0].upper()
            for field_value in self.fields.values():
                if field_value.bank_id == bank_id:
                    self._refresh_field(field_value)
            return []

        if op == "ESNAP":
            self._expect_args(op, args, 2)
            name = args[0]
            target = args[1]
            self.snapshots[name] = self._snapshot(target)
            return [target]

        if op == "ERESTORE":
            self._expect_args(op, args, 2)
            target = args[0]
            name = args[1]
            if name not in self.snapshots:
                self._fail("RESTORE_ERROR", f"unknown snapshot: {name}")
            self._restore(target, self.snapshots[name])
            return [target]

        self._fail("BAD_OPCODE", f"unknown opcode: {op}")

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
            "mode": field_value.mode,
            "exponent_offset": field_value.exponent_offset,
            "sign": field_value.sign,
            "min_partition": field_value.min_partition,
            "current_partition": field_value.current_partition,
            "q_max": self._max_partition(field_value.temperature, field_value.guard_band),
            "guard_band": field_value.guard_band,
            "temperature": field_value.temperature,
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
        self._ensure_bank(bank_id)
        bank = self.banks[bank_id]
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
            guard_band=field_value.guard_band,
            last_refresh=field_value.last_refresh,
        )

    def _store(self, pointer: EPointer, value: ERegisterValue) -> None:
        field_value = self.fields[pointer.field_id]
        bank = self.banks[pointer.bank_id]
        for index in range(pointer.length):
            bank[pointer.offset + index].value = 0.0
            bank[pointer.offset + index].temperature = value.temperature

        for exponent, digit in value.word.normalize().digits.items():
            index = exponent - pointer.exponent_offset
            if 0 <= index < pointer.length:
                bank[pointer.offset + index].value = digit
        field_value.sign = value.word.sign
        field_value.mode = value.mode
        field_value.temperature = value.temperature
        field_value.min_partition = value.min_partition
        field_value.current_partition = value.current_partition
        field_value.last_refresh = self.tick
        pointer.mode_hint = value.mode

    def _refresh(self, target: str) -> Union[str, EPointer]:
        if REGISTER_RE.match(target):
            name = self._er_name(target)
            value = self.er[name]
            value.word = value.word.normalize()
            value.temperature = max(0.0, value.temperature * 0.45 - 0.02)
            value.noise = value.guard_band * (1 + value.temperature)
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
        self._store(pointer, loaded)
        field_value.temperature = loaded.temperature
        field_value.current_partition = min(
            field_value.current_partition,
            self._max_partition(field_value.temperature, field_value.guard_band),
        )
        field_value.last_refresh = self.tick
        for index in range(field_value.length):
            cell = self.banks[field_value.bank_id][field_value.offset + index]
            cell.temperature = field_value.temperature
            cell.noise = field_value.guard_band * (1 + field_value.temperature)
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
            self.er[self._er_name(target)] = deepcopy(snapshot["value"])  # type: ignore[index]
            return
        if POINTER_RE.match(target) and kind == "field":
            pointer = self._ptr(target)
            cells: Sequence[ECell] = snapshot["cells"]  # type: ignore[index,assignment]
            if len(cells) != pointer.length:
                self._fail("RESTORE_ERROR", "snapshot length does not match target field")
            self.banks[pointer.bank_id][pointer.offset : pointer.offset + pointer.length] = deepcopy(
                list(cells)
            )
            saved_field: EField = snapshot["field"]  # type: ignore[index,assignment]
            field_value = self.fields[pointer.field_id]
            field_value.mode = saved_field.mode
            field_value.sign = saved_field.sign
            field_value.min_partition = saved_field.min_partition
            field_value.current_partition = saved_field.current_partition
            field_value.guard_band = saved_field.guard_band
            field_value.temperature = saved_field.temperature
            field_value.last_refresh = self.tick
            return
        self._fail("RESTORE_ERROR", f"cannot restore {kind} snapshot into {target}")

    def _apply_heat(self, op: str, targets: Sequence[Union[str, EPointer]]) -> None:
        heat = {
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
            "EALLOC": 0.01,
            "ELOAD": 0.02,
            "ESTORE": 0.02,
            "ETRACE": 0.01,
            "ETHERM": 0.01,
        }.get(op, 0.0)

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

    def _cool_all(self) -> None:
        for name, value in self.er.items():
            if name == "ER0" or value.temperature > 0.0:
                value.temperature = max(0.0, value.temperature - 0.005)
        for bank_id, cells in self.banks.items():
            meta = self.bank_meta[bank_id]
            for cell in cells:
                cell.temperature = max(meta.base_temperature, cell.temperature - meta.cooling_rate)
        for field_value in self.fields.values():
            meta = self.bank_meta[field_value.bank_id]
            field_value.temperature = max(
                meta.base_temperature, field_value.temperature - meta.cooling_rate
            )

    def _update_due_flags(self) -> None:
        for value in self.er.values():
            if self.tick - value.last_refresh >= 64:
                self.sr.add("REFRESH_DUE")
            if value.temperature > 1.0:
                self.sr.add("THERMAL_WARN")
        for field_value in self.fields.values():
            if self.tick - field_value.last_refresh >= field_value.refresh_deadline:
                self.sr.add("REFRESH_DUE")
            if field_value.temperature > 1.0:
                self.sr.add("THERMAL_WARN")

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

    def _expect_args(self, op: str, args: Sequence[str], count: int) -> None:
        if len(args) != count:
            self._fail("BAD_OPERAND", f"{op} expects {count} operands, got {len(args)}")

    def _fail(self, code: str, message: str) -> None:
        raise EPUError(code, message)
