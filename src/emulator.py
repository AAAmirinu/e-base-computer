"""Higher-level EPU emulator with labels, branches, and run limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Union

from epu import EPU, EPUError, ParsedInstruction, parse_instruction


@dataclass(frozen=True)
class ExecutableProgram:
    instructions: List[ParsedInstruction]
    labels: Dict[str, int]


@dataclass(frozen=True)
class ExecutionResult:
    output: Dict[str, object]
    halted: bool
    steps: int
    pc: int
    trace: List[str]


CONTROL_OPS = {
    "EJMP",
    "EJZ",
    "EJNZ",
    "EJGTZ",
    "EJLTZ",
    "EJGEZ",
    "EJLEZ",
    "EHALT",
    "EPRINT",
}


def assemble(program: Union[str, Iterable[str], Iterable[ParsedInstruction]]) -> ExecutableProgram:
    """Parse an assembly program and collect labels for the high-level emulator."""

    if isinstance(program, str):
        raw_lines = program.splitlines()
    else:
        items = list(program)
        if not items:
            return ExecutableProgram([], {})
        if isinstance(items[0], ParsedInstruction):
            return ExecutableProgram(list(items), {})  # type: ignore[arg-type]
        raw_lines = [str(item) for item in items]

    instructions: List[ParsedInstruction] = []
    labels: Dict[str, int] = {}

    for raw_line in raw_lines:
        line = _strip_inline_comment(raw_line).strip()
        if not line:
            continue

        while ":" in line:
            maybe_label, rest = line.split(":", 1)
            label = maybe_label.strip()
            if not label or not label.replace("_", "").isalnum() or label[0].isdigit():
                break
            if label in labels:
                raise EPUError("BAD_OPERAND", f"duplicate label: {label}")
            labels[label] = len(instructions)
            line = rest.strip()
            if not line:
                break

        if not line:
            continue

        parsed = parse_instruction(line)
        if parsed is not None:
            instructions.append(parsed)

    return ExecutableProgram(instructions, labels)


class EPUEmulator:
    """Program runner layered on top of :class:`epu.EPU`.

    The lower-level EPU intentionally executes one decoded instruction at a time.
    This wrapper adds the pieces expected from a fuller emulator: labels,
    conditional branches, halting, a program counter, and an instruction budget.
    """

    def __init__(self, epu: Optional[EPU] = None, max_steps: int = 10_000) -> None:
        self.epu = epu or EPU()
        self.max_steps = max_steps
        self.pc = 0
        self.halted = False

    def run(self, program: Union[str, Iterable[str], Iterable[ParsedInstruction]]) -> ExecutionResult:
        executable = assemble(program)
        self.pc = 0
        self.halted = False
        steps = 0

        while not self.halted and 0 <= self.pc < len(executable.instructions):
            if steps >= self.max_steps:
                raise EPUError("EXECUTION_LIMIT", f"execution exceeded {self.max_steps} steps")

            instruction = executable.instructions[self.pc]
            self._step_control(instruction, executable.labels)
            steps += 1

        return ExecutionResult(
            output=dict(self.epu.output),
            halted=self.halted,
            steps=steps,
            pc=self.pc,
            trace=list(self.epu.trace),
        )

    def _step_control(self, instruction: ParsedInstruction, labels: Dict[str, int]) -> None:
        op = instruction.op
        if op not in CONTROL_OPS:
            self.epu.step(instruction)
            self.pc += 1
            return

        before = self.epu.visual_snapshot()
        self.epu.sr = {"OK"}
        exception_code = None
        target_labels: List[str] = []

        try:
            if op == "EHALT":
                self.halted = True
                self.pc += 1
            elif op == "EPRINT":
                self._expect_args(op, instruction.args, 1)
                source = instruction.args[0]
                target_labels = [source]
                precision = int(instruction.options.get("precision", "8"))
                self.epu.output[self._next_output_name()] = round(
                    self.epu._reg(source).word.to_real(),
                    precision,
                )
                self.epu.sr.add("OBSERVATION_DIRTY")
                self.pc += 1
            elif op == "EJMP":
                self._expect_args(op, instruction.args, 1)
                target_labels = [instruction.args[0]]
                self.pc = self._label_pc(instruction.args[0], labels)
            else:
                self._expect_args(op, instruction.args, 2)
                register, label = instruction.args
                target_labels = [register, label]
                if self._branch_taken(op, self.epu._reg(register).word.to_real()):
                    self.pc = self._label_pc(label, labels)
                else:
                    self.pc += 1
        except EPUError as exc:
            exception_code = exc.code
            self.epu.last_exception = exc
            self.epu.sr.discard("OK")
            self.epu.sr.add("EXCEPTION")
            if self.epu.cr.get("exception_policy") != "WARN":
                self.epu._record_event(
                    instruction,
                    before,
                    self.epu.visual_snapshot(),
                    target_labels,
                    exception_code,
                )
                raise
            self.epu.trace.append(str(exc))
            self.pc += 1

        self.epu.tick += 1
        self.epu._record_event(
            instruction,
            before,
            self.epu.visual_snapshot(),
            target_labels,
            exception_code,
        )

    def _branch_taken(self, op: str, value: float) -> bool:
        epsilon = 1e-12
        if op == "EJZ":
            return abs(value) <= epsilon
        if op == "EJNZ":
            return abs(value) > epsilon
        if op == "EJGTZ":
            return value > epsilon
        if op == "EJLTZ":
            return value < -epsilon
        if op == "EJGEZ":
            return value >= -epsilon
        if op == "EJLEZ":
            return value <= epsilon
        raise EPUError("BAD_OPCODE", f"unknown control opcode: {op}")

    def _label_pc(self, label: str, labels: Dict[str, int]) -> int:
        if label not in labels:
            raise EPUError("BAD_OPERAND", f"unknown label: {label}")
        return labels[label]

    def _expect_args(self, op: str, args: List[str], count: int) -> None:
        if len(args) != count:
            raise EPUError("BAD_OPERAND", f"{op} expects {count} operands, got {len(args)}")

    def _next_output_name(self) -> str:
        index = 0
        while f"OUT{index}" in self.epu.output:
            index += 1
        return f"OUT{index}"


def _strip_inline_comment(line: str) -> str:
    in_string = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            in_string = not in_string
        if not in_string and char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return line[:index]
        if not in_string and char == "#":
            return line[:index]
        index += 1
    return line
