import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "data" / "calibration_synthetic_v1.json"
sys.path.insert(0, str(SRC))

from epu_calibration import (
    CALIBRATION_DATASET_SCHEMA_VERSION,
    CALIBRATION_EVALUATION_SCHEMA_VERSION,
    CalibrationDataError,
    canonical_payload_sha256,
    evaluate_calibration_dataset,
    load_calibration_dataset,
    validate_calibration_dataset,
)


class CalibrationEvaluatorTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _rehash(self, payload: dict[str, object]) -> dict[str, object]:
        integrity = payload["integrity"]
        assert isinstance(integrity, dict)
        integrity["canonical_payload_sha256"] = canonical_payload_sha256(payload)
        return payload

    def test_fixture_is_explicitly_synthetic_and_integrity_verified(self) -> None:
        dataset = load_calibration_dataset(FIXTURE)

        self.assertEqual(CALIBRATION_DATASET_SCHEMA_VERSION, 1)
        self.assertEqual(dataset.classification, "synthetic")
        self.assertTrue(dataset.payload["provenance"]["is_fixture"])  # type: ignore[index]
        self.assertIn("not empirical", dataset.payload["provenance"]["description"])  # type: ignore[index]
        self.assertEqual(
            dataset.canonical_payload_sha256,
            dataset.payload["integrity"]["canonical_payload_sha256"],  # type: ignore[index]
        )

    def test_integrity_tampering_is_fail_closed(self) -> None:
        payload = self._payload()
        payload["dataset_id"] = "tampered"

        with self.assertRaisesRegex(CalibrationDataError, "integrity mismatch"):
            validate_calibration_dataset(payload)

    def test_empirical_data_requires_hashed_source_artifact(self) -> None:
        payload = self._payload()
        payload["classification"] = "empirical"
        provenance = payload["provenance"]
        assert isinstance(provenance, dict)
        provenance["source_type"] = "empirical"
        provenance["is_fixture"] = False
        self._rehash(payload)

        with self.assertRaisesRegex(CalibrationDataError, "hashed source artifact"):
            validate_calibration_dataset(payload)

    def test_cases_require_fresh_execution_and_explicit_models(self) -> None:
        for mutation, message in (
            (lambda request: request.update(fresh=False), "fresh must be true"),
            (lambda request: request.pop("thermal_model"), "explicitly name"),
            (lambda request: request.pop("aging_model"), "explicitly name"),
        ):
            with self.subTest(message=message):
                payload = self._payload()
                request = payload["cases"][0]["request"]
                mutation(request)
                self._rehash(payload)
                with self.assertRaisesRegex(CalibrationDataError, message):
                    validate_calibration_dataset(payload)

    def test_empirical_observations_require_finite_nonnegative_uncertainty(self) -> None:
        payload = self._payload()
        payload["classification"] = "empirical"
        provenance = payload["provenance"]
        provenance["source_type"] = "empirical"
        provenance["is_fixture"] = False
        provenance["source_artifacts"] = [
            {"uri": "urn:test:raw-observations", "sha256": "a" * 64}
        ]
        self._rehash(payload)
        with self.assertRaisesRegex(CalibrationDataError, "uncertainty"):
            validate_calibration_dataset(payload)

        for case in payload["cases"]:
            for observation in case["observations"]:
                observation["uncertainty"] = 0.001
        dataset = validate_calibration_dataset(self._rehash(payload))
        report = evaluate_calibration_dataset(dataset)
        self.assertTrue(all(record["uncertainty"] == 0.001 for record in report["records"]))

        payload["cases"][0]["observations"][0]["uncertainty"] = -0.1
        self._rehash(payload)
        with self.assertRaisesRegex(CalibrationDataError, "nonnegative"):
            validate_calibration_dataset(payload)

    def test_report_only_holdout_is_required(self) -> None:
        payload = self._payload()
        cases = payload["cases"]
        assert isinstance(cases, list)
        for case in cases:
            case["split"] = "train"
        self._rehash(payload)

        with self.assertRaisesRegex(CalibrationDataError, "validation or holdout"):
            validate_calibration_dataset(payload)

    def test_read_only_evaluation_reports_residual_metrics_and_models(self) -> None:
        before = FIXTURE.read_bytes()
        first = evaluate_calibration_dataset(load_calibration_dataset(FIXTURE))
        second = evaluate_calibration_dataset(load_calibration_dataset(FIXTURE))

        self.assertEqual(first, second)
        self.assertEqual(FIXTURE.read_bytes(), before)
        self.assertEqual(first["evaluation_schema_version"], CALIBRATION_EVALUATION_SCHEMA_VERSION)
        self.assertEqual(first["evaluation_mode"], "read-only-residuals")
        self.assertFalse(first["parameter_fit"])
        self.assertTrue(first["synthetic_fixture"])
        self.assertEqual(first["overall"]["count"], 7)  # type: ignore[index]
        self.assertEqual(first["overall"]["covered"], 7)  # type: ignore[index]
        self.assertEqual(first["overall"]["coverage"], 1.0)  # type: ignore[index]
        self.assertAlmostEqual(first["overall"]["max_abs_error"], 0.002)  # type: ignore[index]
        self.assertEqual(first["by_split"]["holdout"]["count"], 4)  # type: ignore[index]
        self.assertGreater(first["overall"]["mae"], 0.0)  # type: ignore[index]
        self.assertGreater(first["overall"]["rmse"], 0.0)  # type: ignore[index]
        records = first["records"]
        assert isinstance(records, list)
        self.assertEqual(records[0]["models"], {"thermal": "simple-v0", "aging": "aging-v1"})
        self.assertEqual(records[-1]["models"], {"thermal": "coupled-v1", "aging": "aging-v1"})

    def test_unresolvable_target_counts_as_missing_coverage(self) -> None:
        payload = self._payload()
        cases = payload["cases"]
        assert isinstance(cases, list)
        observation = cases[0]["observations"][0]
        observation["target"]["id"] = "ER99"
        dataset = validate_calibration_dataset(self._rehash(payload))

        report = evaluate_calibration_dataset(dataset)

        self.assertEqual(report["overall"]["count"], 7)  # type: ignore[index]
        self.assertEqual(report["overall"]["covered"], 6)  # type: ignore[index]
        self.assertEqual(report["overall"]["missing"], 1)  # type: ignore[index]
        self.assertAlmostEqual(report["overall"]["coverage"], 6 / 7)  # type: ignore[index]

    def test_cli_emits_json_and_does_not_modify_dataset(self) -> None:
        before = FIXTURE.read_bytes()
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "evaluate_calibration.py"), str(FIXTURE)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["dataset_id"], "epu-calibration-synthetic-fixture-v1")
        self.assertEqual(FIXTURE.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
