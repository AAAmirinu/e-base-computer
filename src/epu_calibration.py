"""Versioned, read-only residual evaluation for independent EPU calibration data."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Union

from epu_runtime import EPURuntime, RunRequest


CALIBRATION_DATASET_SCHEMA_VERSION = 1
CALIBRATION_EVALUATION_SCHEMA_VERSION = 1
ALLOWED_SPLITS = frozenset({"train", "validation", "holdout"})
ALLOWED_METRICS = frozenset({"temperature", "noise", "health"})
ALLOWED_TARGET_KINDS = frozenset({"register", "field", "temp"})


class CalibrationDataError(ValueError):
    """Raised when calibration data fails its contract or integrity check."""


@dataclass(frozen=True)
class CalibrationDataset:
    payload: Mapping[str, object]
    canonical_payload_sha256: str

    @property
    def dataset_id(self) -> str:
        return str(self.payload["dataset_id"])

    @property
    def classification(self) -> str:
        return str(self.payload["classification"])


def canonical_payload_bytes(payload: Mapping[str, object]) -> bytes:
    """Canonicalize the hash-covered payload, excluding its integrity envelope."""

    covered = {key: value for key, value in payload.items() if key != "integrity"}
    return json.dumps(
        covered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def load_calibration_dataset(path: Union[Path, str]) -> CalibrationDataset:
    dataset_path = Path(path)
    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationDataError(f"cannot read calibration dataset: {exc}") from exc
    if not isinstance(payload, dict):
        raise CalibrationDataError("calibration dataset root must be an object")
    return validate_calibration_dataset(payload)


def validate_calibration_dataset(payload: Mapping[str, object]) -> CalibrationDataset:
    _expect_exact_version(payload)
    dataset_id = _required_string(payload, "dataset_id")
    if not dataset_id:
        raise CalibrationDataError("dataset_id must not be empty")
    classification = _required_string(payload, "classification")
    if classification not in {"synthetic", "empirical"}:
        raise CalibrationDataError("classification must be synthetic or empirical")

    provenance = _required_mapping(payload, "provenance")
    source_type = _required_string(provenance, "source_type")
    _required_string(provenance, "description")
    _required_string(provenance, "created_at")
    if source_type != classification:
        raise CalibrationDataError("provenance.source_type must match classification")
    if classification == "synthetic" and provenance.get("is_fixture") is not True:
        raise CalibrationDataError("synthetic data must set provenance.is_fixture=true")
    artifacts = provenance.get("source_artifacts", [])
    if not isinstance(artifacts, list):
        raise CalibrationDataError("provenance.source_artifacts must be an array")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise CalibrationDataError("each provenance source artifact must be an object")
        _required_string(artifact, "uri")
        _validate_sha256(_required_string(artifact, "sha256"), "source artifact sha256")
    if classification == "empirical" and not artifacts:
        raise CalibrationDataError("empirical data requires a hashed source artifact")

    split_policy = _required_mapping(payload, "split_policy")
    if split_policy.get("strategy") != "fixed-case-labels":
        raise CalibrationDataError("split_policy.strategy must be fixed-case-labels")
    report_only = split_policy.get("report_only")
    if not isinstance(report_only, list) or not report_only:
        raise CalibrationDataError("split_policy.report_only must be a non-empty array")
    if any(split not in {"validation", "holdout"} for split in report_only):
        raise CalibrationDataError("split_policy.report_only permits validation and holdout only")
    fit_allowed = split_policy.get("fit_allowed_on", [])
    if not isinstance(fit_allowed, list) or any(split != "train" for split in fit_allowed):
        raise CalibrationDataError("split_policy.fit_allowed_on permits train only")

    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CalibrationDataError("cases must be a non-empty array")
    case_ids: set[str] = set()
    splits: set[str] = set()
    observation_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise CalibrationDataError("each case must be an object")
        case_id = _required_string(case, "case_id")
        if case_id in case_ids:
            raise CalibrationDataError(f"duplicate case_id: {case_id}")
        case_ids.add(case_id)
        split = _required_string(case, "split")
        if split not in ALLOWED_SPLITS:
            raise CalibrationDataError(f"invalid split for {case_id}: {split}")
        splits.add(split)
        request = _required_mapping(case, "request")
        if request.get("fresh") is not True:
            raise CalibrationDataError(f"request.fresh must be true for {case_id}")
        if "thermal_model" not in request or "aging_model" not in request:
            raise CalibrationDataError(
                f"request must explicitly name thermal_model and aging_model for {case_id}"
            )
        try:
            RunRequest.from_dict(request)
        except ValueError as exc:
            raise CalibrationDataError(f"invalid request for {case_id}: {exc}") from exc
        observations = case.get("observations")
        if not isinstance(observations, list) or not observations:
            raise CalibrationDataError(f"observations for {case_id} must be non-empty")
        for observation in observations:
            if not isinstance(observation, dict):
                raise CalibrationDataError(f"observation in {case_id} must be an object")
            observation_id = _required_string(observation, "observation_id")
            if observation_id in observation_ids:
                raise CalibrationDataError(f"duplicate observation_id: {observation_id}")
            observation_ids.add(observation_id)
            metric = _required_string(observation, "metric")
            if metric not in ALLOWED_METRICS:
                raise CalibrationDataError(f"invalid metric for {observation_id}: {metric}")
            target = _required_mapping(observation, "target")
            kind = _required_string(target, "kind")
            if kind not in ALLOWED_TARGET_KINDS:
                raise CalibrationDataError(f"invalid target kind for {observation_id}: {kind}")
            if kind != "temp":
                _required_string(target, "id")
            elif metric != "temperature":
                raise CalibrationDataError(
                    f"TEMP target only supports temperature for {observation_id}"
                )
            observed = observation.get("observed")
            if not _finite_number(observed):
                raise CalibrationDataError(f"observed must be finite for {observation_id}")
            if classification == "empirical":
                uncertainty = observation.get("uncertainty")
                if not _finite_number(uncertainty) or float(uncertainty) < 0.0:
                    raise CalibrationDataError(
                        f"empirical uncertainty must be finite and nonnegative for {observation_id}"
                    )
            _required_string(observation, "unit")
    if not ({"validation", "holdout"} & splits):
        raise CalibrationDataError("dataset requires a validation or holdout split")
    if not (set(report_only) & splits):
        raise CalibrationDataError("dataset must contain a declared report-only split")

    integrity = _required_mapping(payload, "integrity")
    if integrity.get("algorithm") != "sha256":
        raise CalibrationDataError("integrity.algorithm must be sha256")
    if integrity.get("canonicalization") != "json-sorted-utf8-v1":
        raise CalibrationDataError(
            "integrity.canonicalization must be json-sorted-utf8-v1"
        )
    declared_hash = _required_string(integrity, "canonical_payload_sha256")
    _validate_sha256(declared_hash, "integrity canonical_payload_sha256")
    actual_hash = canonical_payload_sha256(payload)
    if declared_hash.lower() != actual_hash:
        raise CalibrationDataError(
            f"integrity mismatch: declared {declared_hash.lower()} actual {actual_hash}"
        )
    return CalibrationDataset(dict(payload), actual_hash)


def evaluate_calibration_dataset(dataset: CalibrationDataset) -> Dict[str, object]:
    """Execute published models and report residuals without fitting parameters."""

    records: List[Dict[str, object]] = []
    cases = dataset.payload["cases"]
    assert isinstance(cases, list)
    for case in cases:
        assert isinstance(case, dict)
        case_id = str(case["case_id"])
        split = str(case["split"])
        observations = case["observations"]
        assert isinstance(observations, list)
        try:
            request = RunRequest.from_dict(_required_mapping(case, "request"))
            result = EPURuntime().run(request)
            snapshot = result.snapshot
            model_ids = {
                "thermal": result.models["thermal"]["model_id"],  # type: ignore[index]
                "aging": result.models["aging"]["model_id"],  # type: ignore[index]
            }
            execution_error = None
        except Exception as exc:  # evaluator records coverage rather than fitting around failures
            snapshot = {}
            model_ids = {}
            execution_error = f"{type(exc).__name__}: {exc}"

        for observation in observations:
            assert isinstance(observation, dict)
            base: Dict[str, object] = {
                "case_id": case_id,
                "observation_id": observation["observation_id"],
                "split": split,
                "metric": observation["metric"],
                "target": observation["target"],
                "unit": observation["unit"],
                "observed": observation["observed"],
                "uncertainty": observation.get("uncertainty"),
                "models": model_ids,
            }
            if execution_error is not None:
                base.update(status="missing", reason=execution_error, predicted=None, residual=None, abs_error=None)
            else:
                try:
                    predicted = _prediction(snapshot, observation)
                except (KeyError, TypeError, ValueError) as exc:
                    base.update(status="missing", reason=str(exc), predicted=None, residual=None, abs_error=None)
                else:
                    observed = float(observation["observed"])
                    residual = predicted - observed
                    base.update(
                        status="ok",
                        predicted=predicted,
                        residual=residual,
                        abs_error=abs(residual),
                    )
            records.append(base)

    return {
        "evaluation_schema_version": CALIBRATION_EVALUATION_SCHEMA_VERSION,
        "dataset_schema_version": CALIBRATION_DATASET_SCHEMA_VERSION,
        "dataset_id": dataset.dataset_id,
        "classification": dataset.classification,
        "synthetic_fixture": dataset.classification == "synthetic",
        "provenance": dataset.payload["provenance"],
        "integrity": {
            "algorithm": "sha256",
            "canonicalization": "json-sorted-utf8-v1",
            "canonical_payload_sha256": dataset.canonical_payload_sha256,
            "verified": True,
        },
        "evaluation_mode": "read-only-residuals",
        "parameter_fit": False,
        "overall": _summary(records),
        "by_split": {
            split: _summary(record for record in records if record["split"] == split)
            for split in sorted({str(record["split"]) for record in records})
        },
        "by_metric": {
            metric: _summary(record for record in records if record["metric"] == metric)
            for metric in sorted({str(record["metric"]) for record in records})
        },
        "records": records,
    }


def evaluate_calibration_file(path: Union[Path, str]) -> Dict[str, object]:
    return evaluate_calibration_dataset(load_calibration_dataset(path))


def _prediction(snapshot: Mapping[str, object], observation: Mapping[str, object]) -> float:
    target = _required_mapping(observation, "target")
    kind = str(target["kind"])
    metric = str(observation["metric"])
    if kind == "register":
        bucket = snapshot["er"]
        assert isinstance(bucket, Mapping)
        node = bucket[str(target["id"])]
    elif kind == "field":
        bucket = snapshot["fields"]
        assert isinstance(bucket, Mapping)
        node = bucket[str(target["id"])]
    else:
        if metric != "temperature":
            raise ValueError("TEMP aggregate only supports temperature")
        temp = snapshot["temp"]
        assert isinstance(temp, Mapping)
        node = {"temperature": temp["max_temperature"]}
    if not isinstance(node, Mapping):
        raise TypeError("prediction target is not an object")
    value = node[metric]
    if not _finite_number(value):
        raise ValueError("prediction is not finite")
    return float(value)


def _summary(records: Iterable[Mapping[str, object]]) -> Dict[str, object]:
    rows = list(records)
    errors = [float(row["residual"]) for row in rows if row.get("status") == "ok"]
    count = len(rows)
    covered = len(errors)
    return {
        "count": count,
        "covered": covered,
        "missing": count - covered,
        "coverage": covered / count if count else 0.0,
        "mae": sum(abs(error) for error in errors) / covered if covered else None,
        "rmse": math.sqrt(sum(error * error for error in errors) / covered) if covered else None,
        "max_abs_error": max((abs(error) for error in errors), default=None),
    }


def _expect_exact_version(payload: Mapping[str, object]) -> None:
    version = payload.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise CalibrationDataError("schema_version must be an integer")
    if version != CALIBRATION_DATASET_SCHEMA_VERSION:
        raise CalibrationDataError(f"unsupported calibration schema_version: {version}")


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise CalibrationDataError(f"{key} must be an object")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CalibrationDataError(f"{key} must be a non-empty string")
    return value.strip()


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise CalibrationDataError(f"{label} must be 64 hexadecimal characters")


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


__all__ = [
    "CALIBRATION_DATASET_SCHEMA_VERSION",
    "CALIBRATION_EVALUATION_SCHEMA_VERSION",
    "CalibrationDataError",
    "CalibrationDataset",
    "canonical_payload_bytes",
    "canonical_payload_sha256",
    "evaluate_calibration_dataset",
    "evaluate_calibration_file",
    "load_calibration_dataset",
    "validate_calibration_dataset",
]
