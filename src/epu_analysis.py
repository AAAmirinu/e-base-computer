"""Deterministic, versioned summaries of EPU execution timelines."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, Iterator, Mapping, Optional, Tuple

from epu_spec import instruction_specs


ANALYSIS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ExecutionAnalysis:
    """A compact semantic projection of a complete EPU timeline.

    This is intentionally separate from challenge scoring: it describes what a
    run did and where state pressure accumulated, without assigning quality or
    fidelity points.
    """

    event_count: int
    opcode_counts: Dict[str, int]
    group_counts: Dict[str, int]
    flag_counts: Dict[str, int]
    maintenance_counts: Dict[str, int]
    model_counts: Dict[str, Dict[str, int]]
    observation_events: int
    branch_events: int
    refresh_events: int
    degraded_events: int
    exception_events: int
    first_exception: Optional[Dict[str, object]]
    max_temperature: float
    final_temperature: float
    hottest_target: Optional[str]
    max_noise: float
    noisiest_target: Optional[str]
    min_health: float
    weakest_target: Optional[str]
    peak_refresh_due_count: int
    tick_sequence_valid: bool
    schema_version: int = ANALYSIS_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def analyze_timeline(
    timeline: Iterable[Mapping[str, object]],
) -> ExecutionAnalysis:
    """Aggregate a timeline without mutating it or the machine state."""

    events = list(timeline)
    groups = {item.opcode: item.group for item in instruction_specs()}
    opcode_counts: Dict[str, int] = {}
    group_counts: Dict[str, int] = {}
    flag_counts: Dict[str, int] = {}
    maintenance_counts: Dict[str, int] = {}
    thermal_models: Dict[str, int] = {}
    aging_models: Dict[str, int] = {}
    observation_events = 0
    branch_events = 0
    refresh_events = 0
    degraded_events = 0
    exception_events = 0
    first_exception: Optional[Dict[str, object]] = None
    max_temperature = 0.0
    final_temperature = 0.0
    hottest_target: Optional[str] = None
    max_noise = 0.0
    noisiest_target: Optional[str] = None
    min_health = 1.0
    weakest_target: Optional[str] = None
    peak_refresh_due_count = 0
    ticks = []

    for event in events:
        op = str(event.get("op", ""))
        _increment(opcode_counts, op)
        _increment(group_counts, groups.get(op, "unknown"))

        raw_flags = event.get("flags", [])
        flags = set()
        if isinstance(raw_flags, (list, tuple, set, frozenset)):
            flags = {str(flag) for flag in raw_flags}
        for flag in sorted(flags):
            _increment(flag_counts, flag)
        if op in {"EOBS", "EPRINT"} or "OBSERVATION_DIRTY" in flags:
            observation_events += 1
        if op.startswith("EJ"):
            branch_events += 1
        if "DEGRADED" in flags:
            degraded_events += 1

        tick = event.get("tick")
        ticks.append(tick)
        exception = event.get("exception")
        if exception is not None:
            exception_events += 1
            if first_exception is None:
                first_exception = {"tick": tick, "op": op, "code": str(exception)}

        raw_maintenance = event.get("maintenance", [])
        if isinstance(raw_maintenance, list):
            for item in raw_maintenance:
                kind = str(item).partition(":")[0]
                _increment(maintenance_counts, kind)
                if kind == "auto_refresh":
                    refresh_events += 1
        if op in {"EREFRESH", "ESCRUB"}:
            refresh_events += 1

        aging = event.get("aging_model")
        if aging is not None:
            _increment(aging_models, str(aging))

        after = event.get("after")
        if not isinstance(after, Mapping):
            continue
        temp = after.get("temp")
        if isinstance(temp, Mapping):
            thermal = temp.get("thermal_model")
            if thermal is not None:
                _increment(thermal_models, str(thermal))
            peak_refresh_due_count = max(
                peak_refresh_due_count, int(temp.get("refresh_due_count", 0))
            )

        event_max = 0.0
        for target, node in _iter_nodes(after):
            temperature = float(node.get("temperature", 0.0))
            noise = float(node.get("noise", 0.0))
            health = float(node.get("health", 1.0))
            event_max = max(event_max, temperature)
            if temperature > max_temperature:
                max_temperature = temperature
                hottest_target = target
            if noise > max_noise:
                max_noise = noise
                noisiest_target = target
            if health < min_health:
                min_health = health
                weakest_target = target
        final_temperature = event_max

    return ExecutionAnalysis(
        event_count=len(events),
        opcode_counts=_sorted_counts(opcode_counts),
        group_counts=_sorted_counts(group_counts),
        flag_counts=_sorted_counts(flag_counts),
        maintenance_counts=_sorted_counts(maintenance_counts),
        model_counts={
            "thermal": _sorted_counts(thermal_models),
            "aging": _sorted_counts(aging_models),
        },
        observation_events=observation_events,
        branch_events=branch_events,
        refresh_events=refresh_events,
        degraded_events=degraded_events,
        exception_events=exception_events,
        first_exception=first_exception,
        max_temperature=round(max_temperature, 12),
        final_temperature=round(final_temperature, 12),
        hottest_target=hottest_target,
        max_noise=round(max_noise, 12),
        noisiest_target=noisiest_target,
        min_health=round(min_health, 12),
        weakest_target=weakest_target,
        peak_refresh_due_count=peak_refresh_due_count,
        tick_sequence_valid=_valid_tick_sequence(ticks),
    )


def _increment(counts: Dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _sorted_counts(counts: Mapping[str, int]) -> Dict[str, int]:
    return {key: counts[key] for key in sorted(counts)}


def _valid_tick_sequence(ticks: Iterable[object]) -> bool:
    values = list(ticks)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        return False
    return all(right == left + 1 for left, right in zip(values, values[1:]))


def _iter_nodes(
    snapshot: Mapping[str, object],
) -> Iterator[Tuple[str, Mapping[str, object]]]:
    registers = snapshot.get("er", {})
    if isinstance(registers, Mapping):
        for name, node in registers.items():
            if isinstance(node, Mapping):
                yield str(name), node

    fields = snapshot.get("fields", {})
    if not isinstance(fields, Mapping):
        return
    for name, node in fields.items():
        if not isinstance(node, Mapping):
            continue
        label = str(name)
        yield label, node
        cells = node.get("cells", [])
        if isinstance(cells, list):
            for index, cell in enumerate(cells):
                if isinstance(cell, Mapping):
                    yield f"{label}[{index}]", cell
