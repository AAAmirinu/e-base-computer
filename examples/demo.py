from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecomputer import EComputer


program = [
    ("CONST", "A", "12.5"),
    ("CONST", "B", "4.25"),
    ("ADD", "SUM", "A", "B"),
    ("MUL", "PRODUCT", "A", "B"),
    ("SHIFT", "E_TIMES_A", "A", "1"),
    ("PRINT", "A"),
    ("PRINT", "B"),
    ("PRINT", "SUM"),
    ("PRINT", "PRODUCT"),
    ("PRINT", "E_TIMES_A"),
]


if __name__ == "__main__":
    computer = EComputer()
    for line in computer.run(program):
        print(line)

