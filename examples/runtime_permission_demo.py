"""Run one owned E-field across two explicit task contexts."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu import FIELD_CAPABILITIES
from epu_runtime import EPURuntime, RunRequest


runtime = EPURuntime()
runtime.run(
    RunRequest(
        "ECONST ER0, 7.5\nEALLOC EP0, COLD, 4\nESTORE EP0, ER0",
        language="asm",
        principal="alice",
        capabilities=FIELD_CAPABILITIES,
    )
)
observed = runtime.run(
    RunRequest(
        "ELOAD ER1, EP0\nEOBS OUT0, ER1 ; precision=8",
        language="asm",
        principal="bob",
        capabilities=frozenset({"read", "observe_continuous"}),
        fresh=False,
    )
)

print(observed.to_dict()["output"])
