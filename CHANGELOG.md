# Changelog

All notable changes to this project are documented here.

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
