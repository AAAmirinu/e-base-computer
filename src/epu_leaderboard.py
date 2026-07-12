"""Validate and rank E-base compiler challenge submissions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import glob
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from epu_challenge import NUMERICAL_CHALLENGE_SLUGS, OFFICIAL_CHALLENGE_SLUGS


@dataclass(frozen=True)
class LeaderboardEntry:
    participant: str
    source: str
    valid: bool
    correct: bool
    total_score: float
    claimed_total_score: Optional[float]
    total_steps: int
    total_assembly_lines: int
    degraded_events: int
    slugs: List[str]
    issues: List[str]
    suite: str = "official"
    max_relative_error: float = 0.0
    mean_accuracy_digits: float = 0.0

    def ranking_key(self) -> Tuple[object, ...]:
        bucket = 0 if self.valid and self.correct else 1 if self.valid else 2
        if self.suite == "numerical":
            return (
                self.suite,
                bucket,
                self.max_relative_error,
                self.total_steps,
                self.total_score,
                self.total_assembly_lines,
                self.participant.lower(),
            )
        return (
            self.suite,
            bucket,
            self.total_score,
            self.total_steps,
            self.total_assembly_lines,
            self.participant.lower(),
        )

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def load_leaderboard(
    paths: Sequence[Path],
    best_per_participant: bool = False,
) -> List[LeaderboardEntry]:
    entries = [load_submission(path) for path in expand_submission_paths(paths)]
    if best_per_participant:
        entries = select_best_per_participant(entries)
    return sorted(entries, key=lambda entry: entry.ranking_key())


def expand_submission_paths(paths: Sequence[Path]) -> List[Path]:
    expanded: List[Path] = []
    seen: set[str] = set()
    for path in paths:
        text = str(path)
        if has_glob(text):
            matches = sorted(glob.glob(text))
            if matches:
                for match in matches:
                    append_unique_path(expanded, seen, Path(match))
            else:
                append_unique_path(expanded, seen, path)
        else:
            append_unique_path(expanded, seen, path)
    return expanded


def select_best_per_participant(entries: Iterable[LeaderboardEntry]) -> List[LeaderboardEntry]:
    best: Dict[str, LeaderboardEntry] = {}
    for entry in entries:
        key = entry.participant.lower()
        current = best.get(key)
        if current is None or entry.ranking_key() < current.ranking_key():
            best[key] = entry
    return list(best.values())


def append_unique_path(output: List[Path], seen: set[str], path: Path) -> None:
    key = str(path.resolve(strict=False)).lower()
    if key not in seen:
        seen.add(key)
        output.append(path)


def load_submission(path: Path) -> LeaderboardEntry:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return invalid_entry(path.stem or str(path), str(path), f"cannot read file: {exc}")
    except json.JSONDecodeError as exc:
        return LeaderboardEntry(
            participant=path.stem,
            source=str(path),
            valid=False,
            correct=False,
            total_score=0.0,
            claimed_total_score=None,
            total_steps=0,
            total_assembly_lines=0,
            degraded_events=0,
            slugs=[],
            issues=[f"invalid JSON: {exc}"],
        )
    return submission_from_payload(payload, source=str(path), fallback_participant=path.stem)


def submission_from_payload(
    payload: object,
    source: str = "<memory>",
    fallback_participant: str = "submission",
) -> LeaderboardEntry:
    issues: List[str] = []
    wrapper_participant: Optional[str] = None

    if not isinstance(payload, Mapping):
        return invalid_entry(fallback_participant, source, "payload must be a JSON object")

    if isinstance(payload.get("participant"), str):
        wrapper_participant = str(payload["participant"])
    elif isinstance(payload.get("name"), str):
        wrapper_participant = str(payload["name"])

    submission_payload: Mapping[str, object] = payload
    nested = payload.get("submission")
    if isinstance(nested, Mapping) and isinstance(nested.get("results"), list):
        submission_payload = nested

    participant = wrapper_participant or fallback_participant
    suite_value = submission_payload.get("suite", "official")
    suite = suite_value if isinstance(suite_value, str) else "official"
    if suite not in {"official", "numerical"}:
        issues.append(f"unknown suite: {suite!r}")
        suite = "official"
    results = submission_payload.get("results")
    if not isinstance(results, list):
        return invalid_entry(participant, source, "payload must include a results array")

    by_slug: Dict[str, Mapping[str, object]] = {}
    for index, item in enumerate(results):
        if not isinstance(item, Mapping):
            issues.append(f"results[{index}] must be an object")
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            issues.append(f"results[{index}] is missing slug")
            continue
        if slug in by_slug:
            issues.append(f"duplicate slug: {slug}")
        by_slug[slug] = item

    official = list(
        NUMERICAL_CHALLENGE_SLUGS if suite == "numerical" else OFFICIAL_CHALLENGE_SLUGS
    )
    slugs = list(by_slug)
    missing = [slug for slug in official if slug not in by_slug]
    extra = [slug for slug in slugs if slug not in official]
    if missing:
        issues.append("missing official slug(s): " + ", ".join(missing))
    if extra:
        issues.append("unknown slug(s): " + ", ".join(extra))

    total_score = 0.0
    total_steps = 0
    total_assembly_lines = 0
    degraded_events = 0
    relative_errors: List[float] = []
    accuracy_digits: List[float] = []
    all_correct = True

    for slug in official:
        result = by_slug.get(slug)
        if result is None:
            all_correct = False
            continue
        all_correct = all_correct and result.get("correct") is True
        score_path = "numerical_score" if suite == "numerical" else "score.score"
        total_score += read_float(result, score_path, issues, slug)
        total_steps += int(read_float(result, "steps", issues, slug))
        total_assembly_lines += int(read_float(result, "assembly_lines", issues, slug))
        degraded_events += int(read_float(result, "score.degraded_events", issues, slug, default=0.0))
        if suite == "numerical":
            relative_errors.append(read_float(result, "relative_error", issues, slug))
            accuracy_digits.append(read_float(result, "accuracy_digits", issues, slug))

    claimed_correct = submission_payload.get("correct")
    if claimed_correct is not None and claimed_correct is not all_correct:
        issues.append(f"claimed correct={claimed_correct!r} but results imply {all_correct}")

    claimed_total_score = optional_float(submission_payload.get("total_score"))
    total_score = round(total_score, 6)
    if claimed_total_score is not None and abs(claimed_total_score - total_score) > 1e-6:
        issues.append(
            f"claimed total_score={claimed_total_score} but results sum to {total_score}"
        )

    valid = not issues
    return LeaderboardEntry(
        participant=participant,
        source=source,
        valid=valid,
        correct=bool(all_correct and valid),
        total_score=total_score,
        claimed_total_score=claimed_total_score,
        total_steps=total_steps,
        total_assembly_lines=total_assembly_lines,
        degraded_events=degraded_events,
        slugs=slugs,
        issues=issues,
        suite=suite,
        max_relative_error=max(relative_errors, default=0.0),
        mean_accuracy_digits=round(
            sum(accuracy_digits) / max(1, len(accuracy_digits)), 3
        ),
    )


def leaderboard_payload(entries: Sequence[LeaderboardEntry]) -> Dict[str, object]:
    ranked = sorted(entries, key=lambda entry: entry.ranking_key())
    return {
        "official_slugs": list(OFFICIAL_CHALLENGE_SLUGS),
        "numerical_slugs": list(NUMERICAL_CHALLENGE_SLUGS),
        "entries": [entry.to_dict() for entry in ranked],
    }


def format_leaderboard_markdown(entries: Sequence[LeaderboardEntry]) -> str:
    ranked = sorted(entries, key=lambda entry: entry.ranking_key())
    lines = [
        "| Rank | Suite | Participant | Valid | Correct | Max rel error | Digits | Total score | Steps | Assembly lines | Degraded | Source | Issues |",
        "| ---: | --- | --- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for index, entry in enumerate(ranked, start=1):
        issues = "; ".join(entry.issues) if entry.issues else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    entry.suite,
                    escape_cell(entry.participant),
                    yes_no(entry.valid),
                    yes_no(entry.correct),
                    f"{entry.max_relative_error:.3g}",
                    f"{entry.mean_accuracy_digits:g}",
                    f"{entry.total_score:g}",
                    str(entry.total_steps),
                    str(entry.total_assembly_lines),
                    str(entry.degraded_events),
                    escape_cell(Path(entry.source).name),
                    escape_cell(issues),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def invalid_entry(participant: str, source: str, issue: str) -> LeaderboardEntry:
    return LeaderboardEntry(
        participant=participant,
        source=source,
        valid=False,
        correct=False,
        total_score=0.0,
        claimed_total_score=None,
        total_steps=0,
        total_assembly_lines=0,
        degraded_events=0,
        slugs=[],
        issues=[issue],
    )


def read_float(
    result: Mapping[str, object],
    path: str,
    issues: List[str],
    slug: str,
    default: Optional[float] = None,
) -> float:
    current: object = result
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            if default is not None:
                return default
            issues.append(f"{slug} is missing {path}")
            return 0.0
        current = current[part]
    value = optional_float(current)
    if value is None:
        if default is not None:
            return default
        issues.append(f"{slug} has non-numeric {path}")
        return 0.0
    return value


def optional_float(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def has_glob(value: str) -> bool:
    return any(marker in value for marker in "*?[")
