---
name: Compiler challenge entry
about: Share an optimizer, compiler strategy, or challenge result
title: "[challenge] "
labels: challenge
---

## Target challenge

Paste the official command you ran:

```text
ebase challenge --json
ebase challenge --assembly-dir .\generated-assembly --json
ebase challenge --suite numerical --assembly-dir .\generated-numerical --json
```

## Output correctness

## Score

Paste the full JSON from `ebase challenge --json`. Maintainers can save this block as
`submissions/<name>.json` and run `ebase leaderboard submissions/*.json`.
If you submit multiple attempts, add the same top-level `"participant": "<name>"` field
to each JSON so maintainers can use `--best-per-participant`.

```json

```

Checklist:

- [ ] `correct` is `true`
- [ ] All slugs for the selected suite are present
- [ ] I did not modify `epu_scoring.py` or `epu_challenge.py`
- [ ] I did not special-case the official samples by returning only the expected outputs

## Environment

- OS:
- Python:
- Commit or release:
- Branch or fork URL:

## Reproduction

Paste the commands needed to reproduce your JSON from a fresh checkout:

```text
python -m pip install -e .
ebase challenge --json
# or:
ebase challenge --assembly-dir .\generated-assembly --json
```

## Main diff

Summarize the files you changed, especially compiler changes under `src/`.
If you use `--assembly-dir`, list the generated files:

```text
factorial.epu
e-ladder.epu
cold-memory.epu
thermal-degrade.epu
branching.epu
```

## Strategy

## Generated assembly

```text

```
