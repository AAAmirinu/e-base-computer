"""Versioned ternary and aggregate diagnostic values for the EPU."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Dict, Mapping, Sequence


DIAGNOSTIC_SCHEMA_VERSION = 1
MAX_TRIT_LANES = 27


@dataclass(frozen=True)
class TRegisterValue:
    """One short balanced-ternary lane vector."""

    lanes: tuple[int, ...] = (0,)

    def __post_init__(self) -> None:
        lanes = tuple(self.lanes)
        if not 1 <= len(lanes) <= MAX_TRIT_LANES:
            raise ValueError(
                f"TR register requires 1..{MAX_TRIT_LANES} lanes, got {len(lanes)}"
            )
        if any(isinstance(value, bool) or type(value) is not int for value in lanes):
            raise ValueError("TR lanes must be integers")
        if any(value not in {-1, 0, 1} for value in lanes):
            raise ValueError("TR lanes must be balanced ternary values -1, 0, or 1")
        object.__setattr__(self, "lanes", lanes)

    @property
    def scalar(self) -> int:
        return self.lanes[0]

    def to_dict(self) -> Dict[str, object]:
        return {"lanes": list(self.lanes), "encoding": "balanced"}


@dataclass(frozen=True)
class TemperatureReport:
    schema_version: int
    tick: int
    thermal_model: str
    aging_model: str
    max_temperature: float
    mean_temperature: float
    total_thermal_load: float
    register_max: float
    field_max: float
    hottest_target: str
    refresh_due_count: int
    min_health: float
    max_noise: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def temperature_report(
    *,
    er: Mapping[str, object],
    fields: Mapping[str, object],
    tick: int,
    thermal_model: str,
    aging_model: str,
) -> TemperatureReport:
    """Derive the read-only TEMP register from current EPU state.

    E registers have unit mass.  A field's cell length is its thermal mass,
    matching the coupled thermal model.  Objects are intentionally duck-typed
    so this module does not depend on the EPU implementation module.
    """

    nodes: list[tuple[str, float, float, float, float]] = []
    refresh_due_count = 0
    for name in sorted(er):
        value = er[name]
        temperature = _finite_metric(getattr(value, "temperature"), "temperature")
        health = _bounded_health(getattr(value, "health"))
        noise = _finite_metric(getattr(value, "noise"), "noise")
        nodes.append((name, temperature, 1.0, health, noise))
        if tick - int(getattr(value, "last_refresh")) >= 64:
            refresh_due_count += 1

    for name in sorted(fields):
        value = fields[name]
        length = int(getattr(value, "length"))
        if length <= 0:
            raise ValueError(f"field {name} has non-positive thermal mass")
        temperature = _finite_metric(getattr(value, "temperature"), "temperature")
        health = _bounded_health(getattr(value, "health"))
        noise = _finite_metric(getattr(value, "noise"), "noise")
        nodes.append((name, temperature, float(length), health, noise))
        if tick - int(getattr(value, "last_refresh")) >= int(
            getattr(value, "refresh_deadline")
        ):
            refresh_due_count += 1

    # The architectural ER file is always non-empty, but retain a total
    # function for isolated unit use.
    if not nodes:
        return TemperatureReport(
            DIAGNOSTIC_SCHEMA_VERSION,
            tick,
            thermal_model,
            aging_model,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            "",
            0,
            1.0,
            0.0,
        )

    total_mass = sum(node[2] for node in nodes)
    total_load = sum(node[1] * node[2] for node in nodes)
    maximum = max(node[1] for node in nodes)
    hottest = min(node[0] for node in nodes if node[1] == maximum)
    register_temperatures = [node[1] for node in nodes if node[0].startswith("ER")]
    field_temperatures = [node[1] for node in nodes if not node[0].startswith("ER")]
    return TemperatureReport(
        DIAGNOSTIC_SCHEMA_VERSION,
        tick,
        thermal_model,
        aging_model,
        maximum,
        total_load / total_mass,
        total_load,
        max(register_temperatures, default=0.0),
        max(field_temperatures, default=0.0),
        hottest,
        refresh_due_count,
        min(node[3] for node in nodes),
        max(node[4] for node in nodes),
    )


def compare_trit(left: float, right: float, epsilon: float) -> TRegisterValue:
    if not isfinite(epsilon) or epsilon < 0:
        raise ValueError("ETCMP epsilon must be finite and non-negative")
    difference = left - right
    if difference < -epsilon:
        return TRegisterValue((-1,))
    if difference > epsilon:
        return TRegisterValue((1,))
    return TRegisterValue((0,))


def _finite_metric(value: object, name: str) -> float:
    metric = float(value)
    if not isfinite(metric) or metric < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return metric


def _bounded_health(value: object) -> float:
    health = float(value)
    if not isfinite(health) or not 0 <= health <= 1:
        raise ValueError("health must be finite and between zero and one")
    return health
