"""Scoring helpers for EPU programs and compiler challenges."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Mapping


@dataclass(frozen=True)
class ProgramScore:
    steps: int
    observations: int
    max_temperature: float
    final_temperature: float
    degraded_events: int
    refresh_events: int
    memory_cells: int
    score: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def score_timeline(timeline: Iterable[Mapping[str, object]]) -> ProgramScore:
    events = list(timeline)
    observations = 0
    degraded_events = 0
    refresh_events = 0
    max_temperature = 0.0
    final_temperature = 0.0
    memory_cells = 0

    for event in events:
        op = str(event.get("op", ""))
        flags = set(event.get("flags", []))
        after = event.get("after", {})
        if op in {"EOBS", "EPRINT"} or "OBSERVATION_DIRTY" in flags:
            observations += 1
        if "DEGRADED" in flags:
            degraded_events += 1
        if op in {"EREFRESH", "ESCRUB"}:
            refresh_events += 1
        if isinstance(after, Mapping):
            snapshot_temp = _snapshot_max_temperature(after)
            max_temperature = max(max_temperature, snapshot_temp)
            final_temperature = snapshot_temp
            memory_cells = max(memory_cells, _snapshot_memory_cells(after))

    raw_score = (
        len(events)
        + observations * 12
        + degraded_events * 40
        + max_temperature * 20
        + memory_cells * 0.1
        + refresh_events * 2
    )
    return ProgramScore(
        steps=len(events),
        observations=observations,
        max_temperature=round(max_temperature, 6),
        final_temperature=round(final_temperature, 6),
        degraded_events=degraded_events,
        refresh_events=refresh_events,
        memory_cells=memory_cells,
        score=round(raw_score, 6),
    )


def _snapshot_max_temperature(snapshot: Mapping[str, object]) -> float:
    values: List[float] = []
    er = snapshot.get("er", {})
    if isinstance(er, Mapping):
        for value in er.values():
            if isinstance(value, Mapping):
                values.append(float(value.get("temperature", 0.0)))
    fields = snapshot.get("fields", {})
    if isinstance(fields, Mapping):
        for field in fields.values():
            if isinstance(field, Mapping):
                values.append(float(field.get("temperature", 0.0)))
                cells = field.get("cells", [])
                if isinstance(cells, list):
                    for cell in cells:
                        if isinstance(cell, Mapping):
                            values.append(float(cell.get("temperature", 0.0)))
    return max(values, default=0.0)


def _snapshot_memory_cells(snapshot: Mapping[str, object]) -> int:
    total = 0
    fields = snapshot.get("fields", {})
    if isinstance(fields, Mapping):
        for field in fields.values():
            if isinstance(field, Mapping):
                total += int(field.get("length", 0))
    return total
