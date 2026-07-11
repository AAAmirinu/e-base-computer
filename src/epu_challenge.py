"""Official challenge runner for E-base compiler experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from cstyle_compiler import CStyleCompiler
from emulator import EPUEmulator
from epu_experiments import Experiment, get_experiment, list_experiments
from epu_scoring import ProgramScore, score_timeline


EXPECTED_OUTPUTS: Dict[str, Dict[str, float]] = {
    "factorial": {"OUT0": 120.0},
    "e-ladder": {"OUT0": 144.40872214},
    "cold-memory": {"OUT0": 7.5},
    "thermal-degrade": {"OUT0": 1.62761319},
    "branching": {"OUT0": 0.0},
}

OFFICIAL_CHALLENGE_SLUGS = tuple(EXPECTED_OUTPUTS.keys())


@dataclass(frozen=True)
class ChallengeResult:
    slug: str
    title: str
    language: str
    correct: bool
    output: Dict[str, object]
    expected: Dict[str, float]
    assembly_lines: int
    steps: int
    score: ProgramScore
    submission_source: str = "official"

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["score"] = self.score.to_dict()
        return data


def run_challenge(
    slug: str,
    max_steps: int = 10_000,
    assembly_dir: Optional[Path] = None,
) -> ChallengeResult:
    return run_experiment(
        get_experiment(slug),
        max_steps=max_steps,
        assembly_override=load_assembly_override(slug, assembly_dir),
    )


def run_official_suite(
    max_steps: int = 10_000,
    assembly_dir: Optional[Path] = None,
) -> List[ChallengeResult]:
    experiments = {experiment.slug: experiment for experiment in list_experiments()}
    missing = [slug for slug in OFFICIAL_CHALLENGE_SLUGS if slug not in experiments]
    if missing:
        raise ValueError(f"official challenge sample missing: {', '.join(missing)}")
    return [
        run_experiment(
            experiments[slug],
            max_steps=max_steps,
            assembly_override=load_assembly_override(slug, assembly_dir),
        )
        for slug in OFFICIAL_CHALLENGE_SLUGS
    ]


def run_experiment(
    experiment: Experiment,
    max_steps: int = 10_000,
    assembly_override: Optional[str] = None,
) -> ChallengeResult:
    if experiment.slug not in EXPECTED_OUTPUTS:
        raise ValueError(f"no official expected output for {experiment.slug!r}")
    if assembly_override is None:
        assembly = official_assembly_for_experiment(experiment)
        language = experiment.language
        submission_source = "official"
    else:
        assembly = assembly_override
        language = "asm"
        submission_source = "assembly-dir"
    emulator = EPUEmulator(max_steps=max_steps)
    result = emulator.run(assembly)
    score = score_timeline(emulator.epu.timeline())
    expected = EXPECTED_OUTPUTS[experiment.slug]
    return ChallengeResult(
        slug=experiment.slug,
        title=experiment.title,
        language=language,
        correct=outputs_match(result.output, expected),
        output=result.output,
        expected=expected,
        assembly_lines=count_assembly_lines(assembly),
        steps=result.steps,
        score=score,
        submission_source=submission_source,
    )


def official_assembly_for_experiment(experiment: Experiment) -> str:
    if experiment.language == "c":
        return CStyleCompiler().compile(experiment.source).assembly
    return experiment.source


def official_assembly_for_slug(slug: str) -> str:
    if slug not in OFFICIAL_CHALLENGE_SLUGS:
        raise ValueError(f"no official challenge sample for {slug!r}")
    return official_assembly_for_experiment(get_experiment(slug))


def load_assembly_override(slug: str, assembly_dir: Optional[Path]) -> Optional[str]:
    if assembly_dir is None:
        return None
    if not assembly_dir.is_dir():
        raise ValueError(f"assembly-dir is not a directory: {assembly_dir}")
    path = assembly_dir / f"{slug}.epu"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def outputs_match(output: Mapping[str, object], expected: Mapping[str, float]) -> bool:
    if not expected:
        return False
    for key, expected_value in expected.items():
        if key not in output:
            return False
        value = output[key]
        if not isinstance(value, (int, float)):
            return False
        if not isclose(float(value), expected_value, rel_tol=1e-8, abs_tol=1e-8):
            return False
    return True


def count_assembly_lines(assembly: str) -> int:
    return sum(1 for line in assembly.splitlines() if line.strip())


def summarize_suite(results: List[ChallengeResult]) -> Dict[str, object]:
    total_score = round(sum(result.score.score for result in results), 6)
    return {
        "correct": all(result.correct for result in results),
        "total_score": total_score,
        "results": [result.to_dict() for result in results],
    }
