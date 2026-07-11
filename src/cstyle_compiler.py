"""A tiny C-like compiler that targets the EPU assembly language."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from emulator import EPUEmulator, ExecutionResult
from epu import EPUError


Token = Tuple[str, str]


@dataclass(frozen=True)
class CompiledProgram:
    source: str
    assembly: str
    symbols: Dict[str, str]


class CStyleCompileError(ValueError):
    """Raised when the C-like source cannot be compiled."""


class CStyleCompiler:
    """Compile a deliberately small C-like language into EPU assembly.

    Supported statements:

    - ``let x = expr;`` plus ``float``/``double``/``e`` aliases.
    - ``x = expr;``
    - ``print(expr);`` or ``observe(expr);``
    - ``if (condition) { ... } else { ... }``
    - ``while (condition) { ... }``

    Expressions support numeric literals, variables, parentheses, unary minus,
    addition, subtraction, and multiplication.
    """

    def __init__(self, precision: int = 8) -> None:
        self.precision = precision
        self._tokens: List[Token] = []
        self._pos = 0
        self._assembly: List[str] = []
        self._symbols: Dict[str, str] = {}
        self._free_registers: List[str] = []
        self._temp_registers: set[str] = set()
        self._label_counter = 0
        self._output_counter = 0

    def compile(self, source: str) -> CompiledProgram:
        self._tokens = _tokenize(source)
        self._pos = 0
        self._assembly = []
        self._symbols = {}
        self._free_registers = [f"ER{i}" for i in range(15, -1, -1)]
        self._temp_registers = set()
        self._label_counter = 0
        self._output_counter = 0

        while not self._at_end():
            self._statement()

        return CompiledProgram(source, "\n".join(self._assembly) + "\n", dict(self._symbols))

    def compile_and_run(self, source: str, max_steps: int = 10_000) -> ExecutionResult:
        compiled = self.compile(source)
        return EPUEmulator(max_steps=max_steps).run(compiled.assembly)

    def _statement(self) -> None:
        if self._match_value("let") or self._match_value("float") or self._match_value("double") or self._match_value("e"):
            self._declaration()
            return
        if self._match_value("print") or self._match_value("observe"):
            self._print_statement()
            return
        if self._match_value("while"):
            self._while_statement()
            return
        if self._match_value("if"):
            self._if_statement()
            return
        if self._peek_kind() == "ID":
            self._assignment()
            return
        raise self._error(f"expected statement, got {self._peek_value()!r}")

    def _declaration(self) -> None:
        name = self._consume("ID", "expected variable name")[1]
        if name in self._symbols:
            raise self._error(f"variable already declared: {name}")
        self._consume_value("=")
        value_reg, value_temp = self._expression()
        target = self._reserve_variable(name)
        self._emit(f"EMOV {target}, {value_reg}")
        self._free_temp(value_reg, value_temp)
        self._consume_value(";")

    def _assignment(self) -> None:
        name = self._consume("ID", "expected assignment target")[1]
        if name not in self._symbols:
            raise self._error(f"unknown variable: {name}")
        self._consume_value("=")
        value_reg, value_temp = self._expression()
        self._emit(f"EMOV {self._symbols[name]}, {value_reg}")
        self._free_temp(value_reg, value_temp)
        self._consume_value(";")

    def _print_statement(self) -> None:
        self._consume_value("(")
        value_reg, value_temp = self._expression()
        self._consume_value(")")
        self._consume_value(";")
        self._emit(f"EPRINT {value_reg} ; precision={self.precision}")
        self._free_temp(value_reg, value_temp)

    def _while_statement(self) -> None:
        start_label = self._new_label("while_start")
        body_label = self._new_label("while_body")
        end_label = self._new_label("while_end")
        self._emit(f"{start_label}:")
        branch_op, cond_reg, cond_temp = self._condition()
        self._emit(f"{branch_op} {cond_reg}, {body_label}")
        self._emit(f"EJMP {end_label}")
        self._free_temp(cond_reg, cond_temp)
        self._emit(f"{body_label}:")
        self._block()
        self._emit(f"EJMP {start_label}")
        self._emit(f"{end_label}:")

    def _if_statement(self) -> None:
        then_label = self._new_label("if_then")
        else_label = self._new_label("if_else")
        end_label = self._new_label("if_end")
        branch_op, cond_reg, cond_temp = self._condition()
        self._emit(f"{branch_op} {cond_reg}, {then_label}")
        self._emit(f"EJMP {else_label}")
        self._free_temp(cond_reg, cond_temp)
        self._emit(f"{then_label}:")
        self._block()
        self._emit(f"EJMP {end_label}")
        self._emit(f"{else_label}:")
        if self._match_value("else"):
            self._block()
        self._emit(f"{end_label}:")

    def _block(self) -> None:
        self._consume_value("{")
        while not self._check_value("}") and not self._at_end():
            self._statement()
        self._consume_value("}")

    def _condition(self) -> Tuple[str, str, bool]:
        self._consume_value("(")
        left_reg, left_temp = self._expression()
        if self._peek_value() in {">", "<", ">=", "<=", "==", "!="}:
            operator = self._advance()[1]
            right_reg, right_temp = self._expression()
            cond_reg = self._alloc_temp()
            self._emit(f"ESUB {cond_reg}, {left_reg}, {right_reg}")
            self._emit(f"ENORM {cond_reg}")
            self._free_temp(left_reg, left_temp)
            self._free_temp(right_reg, right_temp)
            self._consume_value(")")
            return _branch_for_comparison(operator), cond_reg, True
        self._consume_value(")")
        return "EJNZ", left_reg, left_temp

    def _expression(self) -> Tuple[str, bool]:
        return self._addition()

    def _addition(self) -> Tuple[str, bool]:
        left_reg, left_temp = self._multiplication()
        while self._peek_value() in {"+", "-"}:
            operator = self._advance()[1]
            right_reg, right_temp = self._multiplication()
            target = self._alloc_temp()
            op = "EADD" if operator == "+" else "ESUB"
            self._emit(f"{op} {target}, {left_reg}, {right_reg}")
            self._emit(f"ENORM {target}")
            self._free_temp(left_reg, left_temp)
            self._free_temp(right_reg, right_temp)
            left_reg, left_temp = target, True
        return left_reg, left_temp

    def _multiplication(self) -> Tuple[str, bool]:
        left_reg, left_temp = self._unary()
        while self._peek_value() == "*":
            self._advance()
            right_reg, right_temp = self._unary()
            target = self._alloc_temp()
            self._emit(f"EMUL {target}, {left_reg}, {right_reg}")
            self._emit(f"ENORM {target}")
            self._free_temp(left_reg, left_temp)
            self._free_temp(right_reg, right_temp)
            left_reg, left_temp = target, True
        if self._peek_value() == "/":
            raise self._error("division is not supported by the current EPU instruction set")
        return left_reg, left_temp

    def _unary(self) -> Tuple[str, bool]:
        if self._match_value("-"):
            value_reg, value_temp = self._unary()
            zero_reg = self._alloc_temp()
            target = self._alloc_temp()
            self._emit(f"ECONST {zero_reg}, 0")
            self._emit(f"ESUB {target}, {zero_reg}, {value_reg}")
            self._emit(f"ENORM {target}")
            self._free_temp(zero_reg, True)
            self._free_temp(value_reg, value_temp)
            return target, True
        return self._primary()

    def _primary(self) -> Tuple[str, bool]:
        if self._match_value("("):
            reg, is_temp = self._expression()
            self._consume_value(")")
            return reg, is_temp
        if self._peek_kind() == "NUMBER":
            number = self._advance()[1]
            reg = self._alloc_temp()
            self._emit(f"ECONST {reg}, {number}")
            return reg, True
        if self._peek_kind() == "ID":
            name = self._advance()[1]
            if name not in self._symbols:
                raise self._error(f"unknown variable: {name}")
            return self._symbols[name], False
        raise self._error(f"expected expression, got {self._peek_value()!r}")

    def _reserve_variable(self, name: str) -> str:
        if not self._free_registers:
            raise self._error("out of E registers")
        register = self._free_registers.pop()
        self._symbols[name] = register
        return register

    def _alloc_temp(self) -> str:
        if not self._free_registers:
            raise self._error("out of E registers")
        register = self._free_registers.pop()
        self._temp_registers.add(register)
        return register

    def _free_temp(self, register: str, is_temp: bool) -> None:
        if not is_temp:
            return
        if register not in self._temp_registers:
            return
        self._temp_registers.remove(register)
        self._free_registers.append(register)

    def _new_label(self, prefix: str) -> str:
        label = f"_{prefix}_{self._label_counter}"
        self._label_counter += 1
        return label

    def _emit(self, line: str) -> None:
        self._assembly.append(line)

    def _consume(self, kind: str, message: str) -> Token:
        if self._peek_kind() != kind:
            raise self._error(message)
        return self._advance()

    def _consume_value(self, value: str) -> None:
        if not self._match_value(value):
            raise self._error(f"expected {value!r}, got {self._peek_value()!r}")

    def _match_value(self, value: str) -> bool:
        if self._check_value(value):
            self._advance()
            return True
        return False

    def _check_value(self, value: str) -> bool:
        return not self._at_end() and self._peek_value() == value

    def _peek_kind(self) -> str:
        return self._tokens[self._pos][0] if not self._at_end() else "EOF"

    def _peek_value(self) -> str:
        return self._tokens[self._pos][1] if not self._at_end() else ""

    def _advance(self) -> Token:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    def _error(self, message: str) -> CStyleCompileError:
        return CStyleCompileError(f"{message} near token {self._pos}")


def compile_source(source: str, precision: int = 8) -> CompiledProgram:
    return CStyleCompiler(precision=precision).compile(source)


def run_source(source: str, precision: int = 8, max_steps: int = 10_000) -> ExecutionResult:
    return CStyleCompiler(precision=precision).compile_and_run(source, max_steps=max_steps)


def _tokenize(source: str) -> List[Token]:
    cleaned = _strip_comments(source)
    pattern = re.compile(
        r"""
        (?P<NUMBER>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
        |(?P<ID>[A-Za-z_][A-Za-z0-9_]*)
        |(?P<OP>==|!=|>=|<=|[+\-*/<>=(){},;])
        |(?P<WS>\s+)
        |(?P<MISMATCH>.)
        """,
        re.VERBOSE,
    )
    tokens: List[Token] = []
    for match in pattern.finditer(cleaned):
        kind = match.lastgroup or "MISMATCH"
        value = match.group()
        if kind == "WS":
            continue
        if kind == "MISMATCH":
            raise CStyleCompileError(f"unexpected character: {value!r}")
        tokens.append((kind, value))
    return tokens


def _strip_comments(source: str) -> str:
    lines: List[str] = []
    for line in source.splitlines():
        if "//" in line:
            line = line.split("//", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _branch_for_comparison(operator: str) -> str:
    mapping = {
        ">": "EJGTZ",
        "<": "EJLTZ",
        ">=": "EJGEZ",
        "<=": "EJLEZ",
        "==": "EJZ",
        "!=": "EJNZ",
    }
    try:
        return mapping[operator]
    except KeyError as exc:
        raise EPUError("BAD_OPERAND", f"unsupported comparison: {operator}") from exc
