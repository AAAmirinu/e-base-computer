# Independent calibration dataset contract v1

This contract separates **model self-consistency** from evidence about
reproduction fidelity. Unit tests that reproduce equations implemented in the
emulator are useful regression evidence, but they are not empirical
calibration. A dataset evaluated by this tool is evidence only to the extent
supported by its declared provenance.

The machine-readable JSON Schema is
`conformance/calibration-dataset-v1.schema.json`. The in-process validator in
`epu_calibration.py` is fail-closed and pins `schema_version=1`.

## Evidence classification and provenance

Every dataset declares exactly one classification:

- `synthetic`: generated or hand-authored data. It must set
  `provenance.source_type=synthetic` and `provenance.is_fixture=true`.
- `empirical`: independently observed data. It must set
  `provenance.source_type=empirical` and include at least one source artifact
  with a URI and SHA-256 hash.

The repository fixture
`tests/data/calibration_synthetic_v1.json` is explicitly synthetic. It exists
only to test contract validation and residual arithmetic. It is **not a
measurement, calibration result, or claim of physical fidelity**.

`provenance.description` and `provenance.created_at` are mandatory. Source
artifacts are references, not silently embedded evidence. Dataset integrity is
checked before execution:

```text
sha256(canonical JSON of all top-level members except integrity)
  == integrity.canonical_payload_sha256
```

Canonical JSON uses UTF-8, sorted keys, no insignificant whitespace, and no
NaN or infinity; this rule is named `json-sorted-utf8-v1` in the integrity
envelope. Any payload or observation change therefore requires an intentional
new hash.

## Fixed splits

Each case has a fixed `train`, `validation`, or `holdout` label. The dataset
must contain `validation` or `holdout`, and `split_policy.report_only` must
name a report-only split present in the cases. The evaluator reports each split
separately and never changes labels.

`fit_allowed_on: ["train"]` documents where a future, separately reviewed fit
workflow could operate. The v1 evaluator does not implement that workflow.
Validation and holdout observations are report-only.

## Cases and observations

Each case embeds a normal runtime `request`. It must set `fresh=true` and
explicitly name both `thermal_model` and `aging_model`; this prevents session
state or future default changes from altering a calibration replay. An
observation names:

- a unique `observation_id`;
- a `register`, `field`, or derived `temp` target;
- `temperature`, `noise`, or `health`;
- a finite observed number and an explicit unit.

Every empirical observation additionally requires a finite, nonnegative
`uncertainty` in the declared unit. Synthetic fixtures may omit uncertainty.

For a `temp` target, the v1 temperature prediction is TEMP's
`max_temperature`. Register and field predictions use the same-named snapshot
member. Units are carried into records; v1 does not convert units. Producers
must normalize measurements before publishing the dataset.

## Read-only residual evaluator

Run:

```powershell
python scripts/evaluate_calibration.py tests/data/calibration_synthetic_v1.json --pretty
```

The command reads the dataset, verifies its hash, executes the already
published models through `EPURuntime`, and writes one JSON report to stdout. It
does not modify the dataset, model constants, runtime state outside each fresh
case, or any repository file.

For prediction `p` and observation `y`:

```text
residual = p - y
MAE      = mean(abs(residual))
RMSE     = sqrt(mean(residual^2))
max      = max(abs(residual))
coverage = predictions available / observations requested
```

The report includes `overall`, `by_split`, and `by_metric` summaries plus
per-observation records. Missing targets or failed executions reduce coverage
and remain visible; they are not silently dropped from the denominator.
`evaluation_mode=read-only-residuals` and `parameter_fit=false` make the v1
boundary explicit.

## What v1 does not claim

- It does not estimate or update thermal or aging coefficients.
- It does not optimize against train data.
- It does not choose a winning model from validation or holdout data.
- It does not certify experimental apparatus, measurement uncertainty, or
  external reproducibility.
- A passing synthetic fixture proves evaluator mechanics only.

An empirical fidelity claim requires an independently collected dataset,
hashed raw-source provenance, documented units and uncertainty, and a review
separate from emulator regression tests.
