"""Toy implementation of a fictional E-base computer.

The primitive digit is a real value in [0, e).  The implementation uses Python
floats, so it demonstrates the rules rather than exact ideal physics.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import e, floor, isclose, log
from typing import Dict, Iterable, List, Mapping, Tuple


EPSILON = 1e-12


def _clean_digits(digits: Mapping[int, float]) -> Dict[int, float]:
    return {int(k): float(v) for k, v in digits.items() if abs(v) > EPSILON}


@dataclass(frozen=True)
class EWord:
    """Finite signed E-word with continuous digits."""

    sign: int
    digits: Mapping[int, float]

    def __post_init__(self) -> None:
        sign = -1 if self.sign < 0 else 1
        cleaned = _clean_digits(self.digits)
        object.__setattr__(self, "sign", sign)
        object.__setattr__(self, "digits", cleaned)

    @staticmethod
    def zero() -> "EWord":
        return EWord(1, {})

    @staticmethod
    def from_real(value: float) -> "EWord":
        """Encode a real number as a one-edit mantissa times e^k.

        Since continuous digits are allowed, any non-zero finite real number
        can be represented with one digit d in [1, e) at an integer exponent.
        """

        if abs(value) <= EPSILON:
            return EWord.zero()

        sign = -1 if value < 0 else 1
        magnitude = abs(float(value))
        exponent = floor(log(magnitude, e))
        digit = magnitude / (e**exponent)

        if digit >= e:
            digit /= e
            exponent += 1

        return EWord(sign, {exponent: digit}).normalize()

    @staticmethod
    def from_digits(digits: Mapping[int, float], sign: int = 1) -> "EWord":
        return EWord(sign, digits).normalize()

    def normalize(self) -> "EWord":
        """Return an equivalent E-word with every digit in [0, e)."""

        if not self.digits:
            return EWord.zero()

        work = _clean_digits(self.digits)
        low = min(work)
        high = max(work)
        k = low

        while k <= high or abs(work.get(k, 0.0)) > EPSILON:
            coefficient = work.get(k, 0.0)
            carry = floor(coefficient / e)
            digit = coefficient - carry * e

            if isclose(digit, e, abs_tol=EPSILON):
                digit = 0.0
                carry += 1
            if isclose(digit, 0.0, abs_tol=EPSILON):
                work.pop(k, None)
            else:
                work[k] = digit

            if carry:
                work[k + 1] = work.get(k + 1, 0.0) + carry
                high = max(high, k + 1)

            k += 1

        return EWord(self.sign, work)

    def to_real(self) -> float:
        return self.sign * sum(digit * (e**power) for power, digit in self.digits.items())

    def shift(self, powers: int) -> "EWord":
        return EWord(self.sign, {k + powers: v for k, v in self.digits.items()})

    def add_same_sign(self, other: "EWord") -> "EWord":
        if self.sign != other.sign:
            raise ValueError("add_same_sign requires matching signs")

        result: Dict[int, float] = dict(self.digits)
        for power, digit in other.digits.items():
            result[power] = result.get(power, 0.0) + digit

        return EWord(self.sign, result).normalize()

    def multiply(self, other: "EWord") -> "EWord":
        result: Dict[int, float] = {}
        for left_power, left_digit in self.digits.items():
            for right_power, right_digit in other.digits.items():
                power = left_power + right_power
                result[power] = result.get(power, 0.0) + left_digit * right_digit

        return EWord(self.sign * other.sign, result).normalize()

    def format(self) -> str:
        if not self.digits:
            return "0"

        terms = [
            f"{digit:.12g}*e^{power}"
            for power, digit in sorted(self.digits.items(), reverse=True)
        ]
        prefix = "-" if self.sign < 0 else ""
        return prefix + " + ".join(terms)


Instruction = Tuple[str, ...]


class EComputer:
    """Minimal register machine for E-word programs."""

    def __init__(self) -> None:
        self.registers: Dict[str, EWord] = {}
        self.output: List[str] = []

    def get(self, name: str) -> EWord:
        return self.registers.get(name, EWord.zero())

    def run(self, program: Iterable[Instruction]) -> List[str]:
        for instruction in program:
            self.step(instruction)
        return list(self.output)

    def step(self, instruction: Instruction) -> None:
        opcode = instruction[0].upper()

        if opcode == "CONST":
            _, target, value = instruction
            self.registers[target] = EWord.from_real(float(value))
            return

        if opcode == "DIGITS":
            _, target, *pairs = instruction
            digits: Dict[int, float] = {}
            for pair in pairs:
                power, digit = pair.split(":")
                digits[int(power)] = float(digit)
            self.registers[target] = EWord.from_digits(digits)
            return

        if opcode == "ADD":
            _, target, left, right = instruction
            self.registers[target] = self.get(left).add_same_sign(self.get(right))
            return

        if opcode == "MUL":
            _, target, left, right = instruction
            self.registers[target] = self.get(left).multiply(self.get(right))
            return

        if opcode == "SHIFT":
            _, target, source, powers = instruction
            self.registers[target] = self.get(source).shift(int(powers))
            return

        if opcode == "PRINT":
            _, source = instruction
            word = self.get(source)
            self.output.append(f"{source} = {word.format()} ~= {word.to_real():.12g}")
            return

        raise ValueError(f"unknown opcode: {opcode}")

