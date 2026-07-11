from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cstyle_compiler import CStyleCompiler
from emulator import EPUEmulator


source = """
let n = 5;
let acc = 1;

while (n > 1) {
    acc = acc * n;
    n = n - 1;
}

print(acc);
"""


if __name__ == "__main__":
    compiler = CStyleCompiler(precision=8)
    compiled = compiler.compile(source)
    print("ASSEMBLY:")
    print(compiled.assembly)

    result = EPUEmulator().run(compiled.assembly)
    print("OUTPUT:")
    for key, value in result.output.items():
        print(f"{key}: {value}")
