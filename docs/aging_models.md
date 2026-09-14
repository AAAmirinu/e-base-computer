# Noise and health aging models

This document defines aging-model coefficient schema version `1`. The
machine-readable form is returned by `ebase spec --json` under `aging_models`.
The coefficients are deterministic emulator constants, not measurements of
physical hardware.

## Selection and compatibility

`CR.aging_model` is independent from `CR.thermal_model`, so either aging model
can run with either `simple-v0` or `coupled-v1` thermal transitions.

| Configured value | Resolved model | Behavior |
| --- | --- | --- |
| `simple`, `simple-v0` | `simple-v0` | Compatibility behavior; no per-cycle aging |
| `aging`, `aging-v1` | `aging-v1` | Seed-free temperature, work, observation, and refresh aging |

The default is `simple-v0`. Existing programs and the official challenge
therefore retain their previous output, temperature, metadata, and score unless
they explicitly select `aging-v1`. An unknown value raises
`AGING_MODEL_ERROR` before the instruction semantic effect. This selection
error is fail-closed even when `CR.exception_policy` is `WARN`, because the
machine cannot advance through an undefined state transition.

Both published models have `deterministic=true` and `requires_seed=false`.
Changing a coefficient requires a new canonical model identifier rather than
silently changing `aging-v1`.

## Lifecycle and equations

A successful instruction cycle has this order:

```text
semantic effect
instruction heat
same-bank and inter-bank thermal exchange
ambient/register cooling
aging
due flags and optional auto-refresh
tick
event
```

Aging reads the post-cooling temperature, so heat from the current instruction
is included. With `coupled-v1`, heat transferred into a neighboring field also
affects that field's aging in the same cycle. Every active register and field
receives temperature exposure; only instruction targets receive work stress.
Field cells then mirror their field's noise and health.

For node temperature `T`, guard band `g`, prior noise `N`, prior health `H`,
instruction stress `S`, and target indicator `I`:

```text
N' = N + g * (temperature_noise_rate * max(T, 0)
              + stress_noise_rate * S * I)

H' = max(0, H - temperature_health_rate * max(T, 0)
            - stress_health_rate * S * I)
```

There is no random draw and no hidden clock. Identical initial state and
instruction stream produce bit-for-bit identical noise, health, and events.
Noise is non-decreasing and health is non-increasing during ordinary aging
cycles.

## `aging-v1` coefficients

| Coefficient | Value | Meaning |
| --- | ---: | --- |
| `temperature_noise_rate` | 0.0004 | Noise growth from post-cooling temperature |
| `stress_noise_rate` | 0.0002 | Target-local noise growth per work unit |
| `temperature_health_rate` | 0.00004 | Health loss from post-cooling temperature |
| `stress_health_rate` | 0.00002 | Target-local health loss per work unit |
| `observation_noise_scale` | 1 | Destructive observation noise multiplier |
| `observation_health_loss` | 0.001 | Direct destructive observation loss |
| `refresh_noise_retention` | 0.25 | Fraction of accumulated noise retained by refresh |
| `refresh_health_recovery` | 0.002 | Maximum health repaired by one refresh |
| `refresh_health_ceiling` | 0.995 | Highest health that refresh can reconstruct |

Instruction stress is also published in `aging_models.instruction_stress`.
The main work units are `EMUL`/`ECONV=1`, `EQUANT=0.625`,
`EADD`/`ESUB`/`ESCALE=0.5`, `EOBS`/`EPRINT`/`ESHIFT`/`EDEQ=0.375`,
`ETSEL=0.25`, `ETRIT`/`ETCMP`/`ETEMP=0.125`, other
load/store/normalize operations `0.125..0.25`, conditional branches `0.05`,
and jump/halt/refresh/scrub `0`. The map exhaustively names every public
opcode; unlisted internal operations have zero stress.

## Observation and refresh boundaries

`non_destructive` observation still carries ordinary observation instruction
stress under `aging-v1`. `destructive` observation additionally applies, during
the semantic effect:

```text
N += g * (1 + T) * observation_noise_scale
H = max(0, H - observation_health_loss)
```

The common heat, cooling, and aging stages follow this effect. `EOBS` and
`EPRINT` share the same transition.

Refresh first cools the node through the existing refresh temperature rule,
then computes:

```text
noise_floor = g * (1 + refreshed_temperature)
N_refresh = max(noise_floor, N * refresh_noise_retention)

if H < refresh_health_ceiling:
    H_refresh = min(refresh_health_ceiling, H + refresh_health_recovery)
else:
    H_refresh = H
```

Refresh therefore cannot erase physical noise, cannot rejuvenate worn state to
pristine health, and never lowers already healthier state merely because it is
above the repair ceiling. Explicit `EREFRESH` then completes the remaining
common cycle; automatic refresh runs in the due-maintenance stage.

Under `simple-v0`, ordinary cycles do not evolve noise or health. The existing
destructive-observation effect and refresh noise floor remain exactly as before,
and refresh does not repair health.
