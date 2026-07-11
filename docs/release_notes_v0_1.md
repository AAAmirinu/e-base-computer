# E-base Computer v0.1.0 Release Notes

This is the first public preview of `e-base-computer`: an experimental E-base computer emulator, C-like compiler, local Web Playground, and compiler challenge kit.

## What You Can Try

Start the Playground:

```powershell
python -m pip install -e .
ebase-playground
```

Open `http://127.0.0.1:8765`, choose a sample, and press `Run`. The Playground shows generated assembly, output, score metrics, E-register digits, E-field cells, thermal timeline, and instruction events.

Run the official challenge:

```powershell
ebase challenge --json
```

Or press `Run Official Suite` in the server-backed Playground and use `Copy JSON`.
External compilers can emit `<challenge-slug>.epu` files and run
`ebase challenge --assembly-dir ./generated-assembly --json`.

## Highlights

- E-word arithmetic with continuous digits in powers of `e`.
- E-registers `ER0..ER15` and E-pointers `EP0..EP7`.
- E-memory banks with different thermal behavior: `WORK`, `COLD`, `ARCHIVE`, and `SACRED`.
- Heat, cooling, refresh pressure, quantization, and thermal degradation.
- Structured execution timeline for visualization and scoring.
- C-like compiler with variables, loops, branches, and observations.
- Official compiler challenge with reproducible baseline scoring.
- `ebase leaderboard` for validating multiple challenge JSON submissions and producing a Markdown ranking table.
- Static GitHub Pages Playground fallback for first-click browser demos without a Python server.
- Shareable Playground program links via `Copy Program Link`.
- Machine-readable instruction reference:

```powershell
ebase spec --json
```

## Official Baseline

```text
correct=true
total_score=373.1
```

Official tasks:

- `factorial`
- `e-ladder`
- `cold-memory`
- `thermal-degrade`
- `branching`

## Good First Contributions

- Add a new E-base sample that demonstrates heat, quantization, memory, or refresh.
- Improve C-like compiler output for fewer steps or lower heat.
- Add a visualization to the Playground.
- Submit a challenge entry with `ebase challenge --json`.
- Propose an EPU instruction or constraint with a small example.

## Distribution

Local install:

```powershell
python -m pip install -e .
```

Docker:

```powershell
docker build -t e-base-computer .
docker run --rm -p 8765:8765 e-base-computer
```

Codespaces/devcontainer support is included through `.devcontainer/devcontainer.json`.

The code and technical documentation are distributed under Apache-2.0. Keep
the attribution in `NOTICE`; see `TRADEMARKS.md` for project-name and logo use.

## Known Limits

- This is an experimental software model, not a real CPU model.
- The physics model is intentionally simple and tuned for playability.
- The static Pages Playground is a lightweight browser fallback. Official challenge rankings should be checked with the CLI or Python server.
- Docker local smoke needs Docker Desktop or another Docker daemon to be running.
