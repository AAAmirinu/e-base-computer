# E-base Computer v0.2.0 Release Notes

E-base Computer v0.2.0 deepens the deterministic emulator model and its
higher-level runtime while preserving the public v0.1 Playground, numerical
challenge, sample, sharing, CLI, and server workflows.

## Highlights

- Added an opt-in, energy-conserving `coupled-v1` thermal model while keeping
  `simple-v0` as the exact compatibility default.
- Added deterministic opt-in `aging-v1` noise and health evolution.
- Made balanced-ternary `TR0..TR7` registers and the derived read-only `TEMP`
  diagnostic layer executable.
- Expanded the public instruction contract to all 38 opcodes in Python and the
  static Playground, backed by cross-runtime C-like and assembly conformance
  corpora.
- Added a versioned task runtime with fresh/session execution, principals,
  capabilities, field ownership, auto-refresh, observer mode, and validated
  thermal/aging controls.
- Added high-level execution analysis for instruction mix, maintenance,
  exceptions, and thermal/noise/health hotspots.
- Added a fail-closed calibration-data contract and residual evaluator. The
  bundled dataset remains explicitly synthetic and is not an empirical fit.

## Existing Experience Preserved

The GitHub Pages and local Playgrounds retain timeline scrubbing, synchronized
per-step state, temperature and precision traces, operation profiles, tabular
challenge results, shareable program links, and the eight public samples.

Both challenge families remain available:

```powershell
ebase challenge --suite official --json
ebase challenge --suite numerical --json
```

The numerical suite continues to cover polynomial evaluation, cancellation,
and recurrence kernels. Server-backed clients can select the same suites via
`/api/challenge?suite=official` and `/api/challenge?suite=numerical`.

## Compatibility and Scoring

`simple-v0`, non-destructive observation, and automatic refresh disabled remain
the defaults. Callers that omit the new runtime controls keep the compatibility
path.

Control instructions now follow the same tick/cooling lifecycle as native
instructions. Together with corrected initializer-register promotion, this
changes the official baseline score from `373.1` to `366.6`; expected program
outputs are unchanged.

New challenge JSON identifies `challenge_schema_version=2`, the
`emulator_version`, and a suite-specific `scoring_model` (`official-score-v1`
or `numerical-score-v1`). Unversioned v0.1 submissions remain loadable as
`legacy-unversioned`, with a visible compatibility warning and a separate
comparison cohort.

## Install and Try

```powershell
python -m pip install e_base_computer-0.2.0-py3-none-any.whl
ebase --version
ebase demo --run
ebase challenge --json
ebase-playground
```

The static Playground is available at
[aaamirinu.github.io/e-base-computer](https://aaamirinu.github.io/e-base-computer/).
Official submissions should still be reproduced with the CLI or Python-backed
Playground.

## Release Verification

The release workflow verifies publication files, the full Python suite,
cross-runtime static parity, a fresh-wheel install, HTTP Playground behavior,
package/tag consistency, and distribution metadata before creating the GitHub
Release. The release includes a wheel, sdist, deterministic source ZIP, and
`SHA256SUMS.txt`.

## Known Limits

- This remains an experimental software model, not a physical CPU model.
- Thermal and aging coefficients are deterministic modeling choices, not
  independently measured hardware calibration.
- The bundled calibration fixture is synthetic; it cannot support empirical or
  universal fidelity claims.
- Static Pages is a browser demo. Use the Python runtime for authoritative
  challenge submissions and session/capability behavior.
- Docker verification requires a working Docker daemon.

The code and technical documentation are distributed under Apache-2.0. Keep
the attribution in `NOTICE`; see `TRADEMARKS.md` for project-name and logo use.
