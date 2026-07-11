"""Curated E-base experiments shared by the CLI and playground."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Experiment:
    slug: str
    title: str
    language: str
    description: str
    source: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


EXPERIMENTS: List[Experiment] = [
    Experiment(
        slug="factorial",
        title="Factorial loop",
        language="c",
        description="C-like while loop compiled into EPU control flow.",
        source="""let n = 5;
let acc = 1;

while (n > 1) {
    acc = acc * n;
    n = n - 1;
}

print(acc);
""",
    ),
    Experiment(
        slug="e-ladder",
        title="E digit ladder",
        language="asm",
        description="Multiplication, normalization, e-shift, and observation in a short EPU trace.",
        source="""ECONST ER0, 12.5
ECONST ER1, 4.25
EMUL ER2, ER0, ER1
ENORM ER2
ESHIFT ER3, ER2, 1
EOBS OUT0, ER3 ; precision=8
""",
    ),
    Experiment(
        slug="cold-memory",
        title="Cold E-memory",
        language="asm",
        description="Store an E-word into a cold E-field, reload it, and inspect the field map.",
        source="""ECONST ER0, 7.5
EALLOC EP0, COLD, 4 ; mode=EWORD
ESTORE EP0, ER0
ELOAD ER1, EP0
EOBS OUT0, ER1 ; precision=8
ETRACE EP0
""",
    ),
    Experiment(
        slug="thermal-degrade",
        title="Thermal degradation",
        language="asm",
        description="Heat a register before quantization so the requested 243-way partition degrades.",
        source="""ECONST ER0, 1.2
ECONST ER1, 1.01
ECONST ER3, 30
ECONST ER4, 1
heat:
EMUL ER0, ER0, ER1
ESUB ER3, ER3, ER4
EJGTZ ER3, heat
EQOS ER0 ; min_partition=243 degrade=allow
EQUANT ER1, ER0, 243
ETHERM OUT_THERMAL, ER1
EOBS OUT0, ER1 ; precision=8
""",
    ),
    Experiment(
        slug="branching",
        title="Branching C-like",
        language="c",
        description="A tiny if/else program showing runtime output numbering.",
        source="""let signal = -2;

if (signal >= 0) {
    print(1);
} else {
    print(0);
}
""",
    ),
]


def list_experiments() -> List[Experiment]:
    return list(EXPERIMENTS)


def experiment_map() -> Dict[str, Experiment]:
    return {experiment.slug: experiment for experiment in EXPERIMENTS}


def get_experiment(slug: str) -> Experiment:
    experiments = experiment_map()
    if slug not in experiments:
        choices = ", ".join(sorted(experiments))
        raise KeyError(f"unknown experiment {slug!r}; choose one of: {choices}")
    return experiments[slug]
