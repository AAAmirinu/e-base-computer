# Changelog

All notable changes to this project are documented here.

## 0.2.0 - 2026-09-04

- Preserved and extended the public Playground experience with timeline
  scrubbing, synchronized per-step state inspection, temperature and precision
  traces, operation profiles, tabular challenge results, shareable links, and
  all eight existing samples.
- Preserved the numerical compiler challenge suite for polynomial evaluation,
  cancellation, and recurrence kernels across the CLI, Python server, static
  Playground, starter compiler, and leaderboard.
- Added challenge schema, emulator version, and scoring-model provenance;
  unversioned v0.1 submissions remain readable but are isolated in an explicit
  legacy comparison cohort instead of being silently ranked against v0.2.
- Hardened Playground request validation so malformed JSON, invalid limits,
  large source bodies, numeric overflow, and deep source nesting return client
  errors instead of unhandled server failures.
- Rejected non-finite E-word values consistently across the emulator, CLI, and
  Playground, accepted UTF-8 BOM-prefixed C-like source files on Windows, and
  enforced documented EPU field/bank allocation limits.
- Added a technical behavior guide covering heat costs, cooling, memory-bank
  differences, safe quantization partitions, degradation, observation,
  refresh, and scoring, while enforcing the documented partition ladder
  (`3, 9, 27, 81, 243`) in Python and the static Playground.

- Unified native and control instructions under one thermal/tick lifecycle, so
  branches, `EPRINT`, and `EHALT` now advance cooling and refresh pressure.
- Added capability-aware task contexts, field ownership enforcement, a
  versioned runtime API, target-local degradation policy, and finite E-word
  input validation.
- Connected `CR.thermal_model` to execution with an exact `simple-v0`
  compatibility model and a deterministic, energy-conserving `coupled-v1`
  field/bank heat-exchange model with published schema-v1 coefficients.
- Added opt-in deterministic `aging-v1` noise/health evolution and executable
  balanced-ternary `TR0..TR7` plus a derived read-only `TEMP` diagnostic layer.
- Added a schema-v1 machine-readable metadata propagation contract covering all
  38 opcodes, with executable drift checks and atomic snapshot/observer guards.
- Added a versioned high-level execution analysis that summarizes instruction
  mix, maintenance, exceptions, model usage, and thermal/noise/health hotspots
  independently from challenge scoring.
- Exposed auto-refresh and destructive/non-destructive observation as validated
  task-runtime, CLI, and local Playground controls with effective settings in
  every result.
- Added a versioned independent calibration-data contract with provenance and
  SHA-256 integrity, fixed train/validation/holdout labels, and a read-only
  residual evaluator reporting MAE, RMSE, maximum error, and coverage. The
  bundled test fixture is explicitly synthetic and makes no empirical claim.
- Recalibrated the current official baseline score from `373.1` to `366.6`;
  outputs are unchanged, while control-heavy programs receive corrected
  per-tick cooling and initializer-register promotion removes redundant moves
  from C-like assembly.
- Replaced the static Playground's direct C-like evaluator with a deterministic
  JavaScript compiler that emits the same EPU assembly, symbols, diagnostics,
  output order, execution events, and challenge scores as `CStyleCompiler` for
  the cross-runtime conformance corpus.
- Expanded static `runAsm` to all 38 public opcodes with exact discrete-state,
  output, control-flow, and diagnostic parity against Python plus documented
  schema-v1 floating-point tolerances.
- Relicensed the technical implementation and documentation under Apache-2.0.
- Added `NOTICE`, `TRADEMARKS.md`, and `TECHNICAL_SCOPE.md` for attribution,
  project-name use, and the public technical boundary.
- Removed worldbuilding and narrative material from the public documentation
  set and excluded local private materials from release bundles.

## 0.1.0 - Initial Public Preview

### Added

- Prototype E-base computer runtime with continuous E digits, E-word normalization, E registers, E pointers, E fields, memory banks, heat, refresh, observation, quantization, and degradation.
- Higher-level emulator layer with labels, conditional branches, `EPRINT`, `EHALT`, and execution limits.
- C-like compiler for small programs with variables, arithmetic, `if/else`, `while`, `print`, and `observe`.
- CLI tools: `ebase compile`, `ebase run`, `ebase demo`, `ebase samples`, `ebase challenge`, `ebase leaderboard`, `ebase spec`, and `ebase-playground`.
- Local Web Playground with source editing, sample loading, generated assembly, output, score metrics, thermal timeline, E Digit Ladder, E Field Map, event log, official challenge execution, and JSON copy.
- Static GitHub Pages Playground fallback for first-click browser demos without a Python server.
- Shareable Playground program links via `Copy Program Link`.
- Official compiler challenge suite with five baseline tasks: `factorial`, `e-ladder`, `cold-memory`, `thermal-degrade`, and `branching`.
- Challenge submission validation and Markdown leaderboard generation for contest organizers.
- Machine-readable EPU instruction reference via `ebase spec --json`.
- Public-release support files: README screenshot, license, contributing guide, security note, issue templates, PR template, Dockerfile, devcontainer, GitHub Actions, release checklist, kickoff draft, and publication audit.

### Baseline

- Official challenge result: `correct=true`
- Baseline total score: `373.1`
- Refresh events are counted as a cost, not a score discount, so refresh loops cannot lower a submission score.

### Verification

```powershell
python .\scripts\publication_audit.py --full
python .\scripts\release_smoke.py
```

Docker smoke is included in GitHub Actions. Local Docker verification requires a running Docker daemon.
