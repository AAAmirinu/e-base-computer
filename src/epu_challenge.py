"""Official challenge runner for E-base compiler experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose, log10
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

NUMERICAL_EXPECTED_OUTPUTS: Dict[str, Dict[str, float]] = {
    "numerical-polynomial": {"OUT0": -0.9704407594824638},
    "numerical-cancellation": {"OUT0": 1.23456789},
    "numerical-recurrence": {"OUT0": 0.843256190266822},
}

NUMERICAL_CHALLENGE_SLUGS = tuple(NUMERICAL_EXPECTED_OUTPUTS.keys())
NUMERICAL_ABS_TOLERANCE = 5e-8
NUMERICAL_REL_TOLERANCE = 5e-8


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


@dataclass(frozen=True)
class NumericalChallengeResult:
    slug: str
    title: str
    language: str
    correct: bool
    output: Dict[str, object]
    expected: Dict[str, float]
    assembly_lines: int
    steps: int
    score: ProgramScore
    absolute_error: float
    relative_error: float
    accuracy_digits: float
    error_penalty: float
    numerical_score: float
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


def run_numerical_suite(
    max_steps: int = 10_000,
    assembly_dir: Optional[Path] = None,
) -> List[NumericalChallengeResult]:
    experiments = {experiment.slug: experiment for experiment in list_experiments()}
    missing = [slug for slug in NUMERICAL_CHALLENGE_SLUGS if slug not in experiments]
    if missing:
        raise ValueError(f"numerical challenge sample missing: {', '.join(missing)}")
    return [
        run_numerical_experiment(
            experiments[slug],
            max_steps=max_steps,
            assembly_override=load_assembly_override(slug, assembly_dir),
        )
        for slug in NUMERICAL_CHALLENGE_SLUGS
    ]


def run_numerical_experiment(
    experiment: Experiment,
    max_steps: int = 10_000,
    assembly_override: Optional[str] = None,
) -> NumericalChallengeResult:
    expected = NUMERICAL_EXPECTED_OUTPUTS.get(experiment.slug)
    if expected is None:
        raise ValueError(f"no numerical expected output for {experiment.slug!r}")
    if assembly_override is None:
        assembly = (
            CStyleCompiler(precision=12).compile(experiment.source).assembly
            if experiment.language == "c"
            else experiment.source
        )
        language = experiment.language
        submission_source = "official"
    else:
        assembly = assembly_override
        language = "asm"
        submission_source = "assembly-dir"
    emulator = EPUEmulator(max_steps=max_steps)
    result = emulator.run(assembly)
    performance = score_timeline(emulator.epu.timeline())
    absolute_error, relative_error = output_errors(result.output, expected)
    accuracy_digits = error_digits(relative_error)
    error_penalty = min(1_000_000.0, relative_error * 1_000_000.0)
    numerical_score = round(performance.score + error_penalty, 6)
    return NumericalChallengeResult(
        slug=experiment.slug,
        title=experiment.title,
        language=language,
        correct=outputs_match(
            result.output,
            expected,
            rel_tol=NUMERICAL_REL_TOLERANCE,
            abs_tol=NUMERICAL_ABS_TOLERANCE,
        ),
        output=result.output,
        expected=expected,
        assembly_lines=count_assembly_lines(assembly),
        steps=result.steps,
        score=performance,
        absolute_error=round(absolute_error, 15),
        relative_error=round(relative_error, 15),
        accuracy_digits=round(accuracy_digits, 3),
        error_penalty=round(error_penalty, 6),
        numerical_score=numerical_score,
        submission_source=submission_source,
    )


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


def numerical_assembly_for_slug(slug: str) -> str:
    if slug not in NUMERICAL_CHALLENGE_SLUGS:
        raise ValueError(f"no numerical challenge sample for {slug!r}")
    experiment = get_experiment(slug)
    if experiment.language == "c":
        return CStyleCompiler(precision=12).compile(experiment.source).assembly
    return experiment.source


def load_assembly_override(slug: str, assembly_dir: Optional[Path]) -> Optional[str]:
    if assembly_dir is None:
        return None
    if not assembly_dir.is_dir():
        raise ValueError(f"assembly-dir is not a directory: {assembly_dir}")
    path = assembly_dir / f"{slug}.epu"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def outputs_match(
    output: Mapping[str, object],
    expected: Mapping[str, float],
    rel_tol: float = 1e-8,
    abs_tol: float = 1e-8,
) -> bool:
    if not expected:
        return False
    for key, expected_value in expected.items():
        if key not in output:
            return False
        value = output[key]
        if not isinstance(value, (int, float)):
            return False
        if not isclose(float(value), expected_value, rel_tol=rel_tol, abs_tol=abs_tol):
            return False
    return True


def output_errors(
    output: Mapping[str, object], expected: Mapping[str, float]
) -> tuple[float, float]:
    absolute_error = 0.0
    relative_error = 0.0
    for key, expected_value in expected.items():
        value = output.get(key)
        if not isinstance(value, (int, float)):
            return 1_000_000.0, 1_000_000.0
        error = abs(float(value) - expected_value)
        scale = max(abs(expected_value), 1e-15)
        absolute_error = max(absolute_error, error)
        relative_error = max(relative_error, error / scale)
    return absolute_error, relative_error


def error_digits(relative_error: float) -> float:
    if relative_error <= 0:
        return 15.0
    return max(0.0, min(15.0, -log10(relative_error)))


def count_assembly_lines(assembly: str) -> int:
    return sum(1 for line in assembly.splitlines() if line.strip())


def summarize_suite(results: List[ChallengeResult]) -> Dict[str, object]:
    total_score = round(sum(result.score.score for result in results), 6)
    return {
        "correct": all(result.correct for result in results),
        "total_score": total_score,
        "results": [result.to_dict() for result in results],
    }


def summarize_numerical_suite(
    results: List[NumericalChallengeResult],
) -> Dict[str, object]:
    return {
        "suite": "numerical",
        "correct": all(result.correct for result in results),
        "total_score": round(sum(result.numerical_score for result in results), 6),
        "performance_score": round(sum(result.score.score for result in results), 6),
        "mean_accuracy_digits": round(
            sum(result.accuracy_digits for result in results) / max(1, len(results)),
            3,
        ),
        "results": [result.to_dict() for result in results],
    }
