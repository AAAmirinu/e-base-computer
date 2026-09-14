"""Versioned high-level runtime boundary for E-base programs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, FrozenSet, List, Mapping, Optional

from cstyle_compiler import CStyleCompiler
from emulator import EPUEmulator
from epu import (
    AGING_MODEL_ALIASES,
    AGING_MODELS,
    EPU,
    FIELD_CAPABILITIES,
    THERMAL_MODEL_ALIASES,
    THERMAL_MODELS,
    TaskContext,
)
from epu_scoring import score_timeline
from epu_analysis import analyze_timeline


RUNTIME_SCHEMA_VERSION = 1
LANGUAGE_ALIASES = {"asm": "asm", "c": "cbase", "cbase": "cbase"}
OBSERVER_MODES = frozenset({"non_destructive", "destructive"})


class RuntimeRequestError(ValueError):
    """Raised before execution when a runtime request violates schema v1."""


@dataclass(frozen=True)
class RunRequest:
    source: str
    language: str = "cbase"
    max_steps: int = 10_000
    precision: int = 8
    principal: str = "kernel"
    capabilities: FrozenSet[str] = field(default_factory=frozenset)
    fresh: bool = True
    thermal_model: str = "simple"
    aging_model: str = "simple-v0"
    auto_refresh: bool = False
    observer_mode: str = "non_destructive"
    schema_version: int = RUNTIME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise RuntimeRequestError("schema_version must be an integer")
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise RuntimeRequestError(
                f"unsupported runtime schema_version: {self.schema_version}"
            )
        if not isinstance(self.language, str):
            raise RuntimeRequestError("language must be a string")
        language = self.language.lower()
        if language not in LANGUAGE_ALIASES:
            raise RuntimeRequestError(f"unknown language: {self.language}")
        if not isinstance(self.source, str):
            raise RuntimeRequestError("source must be a string")
        if (
            not isinstance(self.max_steps, int)
            or isinstance(self.max_steps, bool)
            or self.max_steps <= 0
        ):
            raise RuntimeRequestError("max_steps must be a positive integer")
        if (
            not isinstance(self.precision, int)
            or isinstance(self.precision, bool)
            or not 0 <= self.precision <= 15
        ):
            raise RuntimeRequestError("precision must be between 0 and 15")
        if not isinstance(self.principal, str):
            raise RuntimeRequestError("principal must be a string")
        principal = self.principal.strip()
        if not principal:
            raise RuntimeRequestError("principal must not be empty")
        if any(not isinstance(item, str) for item in self.capabilities):
            raise RuntimeRequestError("capabilities must contain only strings")
        capabilities = frozenset(self.capabilities)
        unknown = capabilities.difference(FIELD_CAPABILITIES)
        if unknown:
            raise RuntimeRequestError(
                f"unknown capabilities: {', '.join(sorted(unknown))}"
            )
        if not isinstance(self.fresh, bool):
            raise RuntimeRequestError("fresh must be a boolean")
        if not isinstance(self.auto_refresh, bool):
            raise RuntimeRequestError("auto_refresh must be a boolean")
        if not isinstance(self.observer_mode, str):
            raise RuntimeRequestError("observer_mode must be a string")
        observer_mode = self.observer_mode.strip().lower()
        if observer_mode not in OBSERVER_MODES:
            raise RuntimeRequestError(
                "unknown observer_mode: "
                f"{self.observer_mode}; expected one of {', '.join(sorted(OBSERVER_MODES))}"
            )
        thermal_model = _validated_model(
            self.thermal_model,
            "thermal_model",
            THERMAL_MODEL_ALIASES,
            THERMAL_MODELS,
        )
        aging_model = _validated_model(
            self.aging_model,
            "aging_model",
            AGING_MODEL_ALIASES,
            AGING_MODELS,
        )
        object.__setattr__(self, "language", LANGUAGE_ALIASES[language])
        object.__setattr__(self, "principal", principal)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "thermal_model", thermal_model)
        object.__setattr__(self, "aging_model", aging_model)
        object.__setattr__(self, "observer_mode", observer_mode)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RunRequest":
        raw_capabilities = payload.get("capabilities", ())
        if isinstance(raw_capabilities, str) or not isinstance(
            raw_capabilities, (list, tuple, set, frozenset)
        ):
            raise RuntimeRequestError("capabilities must be an array of strings")
        raw_fresh = payload.get("fresh", True)
        if not isinstance(raw_fresh, bool):
            raise RuntimeRequestError("fresh must be a boolean")
        return cls(
            source=payload.get("source", ""),  # type: ignore[arg-type]
            language=payload.get("language", "cbase"),  # type: ignore[arg-type]
            max_steps=payload.get("max_steps", payload.get("maxSteps", 10_000)),  # type: ignore[arg-type]
            precision=payload.get("precision", 8),  # type: ignore[arg-type]
            principal=payload.get("principal", "kernel"),  # type: ignore[arg-type]
            capabilities=frozenset(raw_capabilities),  # type: ignore[arg-type]
            fresh=raw_fresh,
            thermal_model=payload.get("thermal_model", "simple"),  # type: ignore[arg-type]
            aging_model=payload.get("aging_model", "simple-v0"),  # type: ignore[arg-type]
            auto_refresh=payload.get("auto_refresh", False),  # type: ignore[arg-type]
            observer_mode=payload.get("observer_mode", "non_destructive"),  # type: ignore[arg-type]
            schema_version=payload.get("schema_version", RUNTIME_SCHEMA_VERSION),  # type: ignore[arg-type]
        )

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["capabilities"] = sorted(self.capabilities)
        return payload


@dataclass(frozen=True)
class RunResult:
    language: str
    assembly: str
    symbols: Dict[str, str]
    output: Dict[str, object]
    halted: bool
    steps: int
    pc: int
    trace: List[str]
    timeline: List[Dict[str, object]]
    snapshot: Dict[str, object]
    score: Dict[str, object]
    principal: str
    fresh: bool
    models: Dict[str, object]
    controls: Dict[str, object]
    analysis: Dict[str, object]
    schema_version: int = RUNTIME_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class EPURuntime:
    """Execute fresh programs or explicit continuations through one stable API."""

    def __init__(self) -> None:
        self._session_epu: Optional[EPU] = None

    def reset(self) -> None:
        self._session_epu = None

    def run(self, request: RunRequest) -> RunResult:
        context = TaskContext(request.principal, request.capabilities)
        if not request.fresh and self._session_epu is None:
            raise RuntimeRequestError(
                "session continuation requested before a fresh session exists"
            )
        if request.fresh:
            epu = EPU(context=context)
            self._session_epu = epu
        else:
            assert self._session_epu is not None
            epu = self._session_epu
            epu.set_context(context)

        # Model selection is a high-level execution contract, not assembly
        # source mutation.  Validation already completed in RunRequest, so the
        # machine starts every cycle with resolvable versioned identifiers.
        epu.cr["thermal_model"] = request.thermal_model
        epu.cr["aging_model"] = request.aging_model
        epu.cr["auto_refresh"] = request.auto_refresh
        epu.cr["observer_mode"] = request.observer_mode

        symbols: Dict[str, str] = {}
        if request.language == "cbase":
            compiled = CStyleCompiler(precision=request.precision).compile(request.source)
            assembly = compiled.assembly
            symbols = compiled.symbols
        else:
            assembly = request.source

        emulator = EPUEmulator(
            epu=epu,
            max_steps=request.max_steps,
            context=context,
        )
        execution = emulator.run(assembly)
        timeline = epu.timeline()
        return RunResult(
            language=request.language,
            assembly=assembly,
            symbols=symbols,
            output=execution.output,
            halted=execution.halted,
            steps=execution.steps,
            pc=execution.pc,
            trace=execution.trace,
            timeline=timeline,
            snapshot=epu.visual_snapshot(),
            score=score_timeline(timeline).to_dict(),
            principal=context.principal,
            fresh=request.fresh,
            models={
                "thermal": epu.thermal_model_info(),
                "aging": epu.aging_model_info(),
            },
            controls={
                "auto_refresh": request.auto_refresh,
                "observer_mode": request.observer_mode,
            },
            analysis=analyze_timeline(timeline).to_dict(),
        )


def run_program(request: RunRequest) -> RunResult:
    """Convenience entry point for a single fresh or one-shot request."""

    return EPURuntime().run(request)


def _validated_model(
    value: object,
    field_name: str,
    aliases: Mapping[str, str],
    models: Mapping[str, object],
) -> str:
    if not isinstance(value, str):
        raise RuntimeRequestError(f"{field_name} must be a string")
    configured = value.strip().lower()
    if not configured:
        raise RuntimeRequestError(f"{field_name} must not be empty")
    canonical = aliases.get(configured, configured)
    if canonical not in models:
        allowed = sorted(set(aliases) | set(models))
        raise RuntimeRequestError(
            f"unknown {field_name}: {value}; expected one of {', '.join(allowed)}"
        )
    return canonical
