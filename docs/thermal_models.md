# Thermal Models

This document defines thermal-model coefficient schema version `1`. The
machine-readable form is also returned by `ebase spec --json` under
`thermal_models`.

## Selection and compatibility

`CR.thermal_model` accepts canonical versioned identifiers and convenience
aliases:

| Configured value | Resolved model | Behavior |
| --- | --- | --- |
| `simple`, `simple-v0` | `simple-v0` | Original independent-node cooling |
| `coupled`, `coupled-v1` | `coupled-v1` | Field and bank heat exchange |

The default remains `simple`, so programs that do not select a model retain
the previous temperatures and challenge score. An unknown identifier raises
`THERMAL_MODEL_ERROR` before the instruction semantic effect. This error is
fail-closed even when `CR.exception_policy` is `WARN` because the machine
cannot advance time without a defined transition.

## Coefficients

| Coefficient | `simple-v0` | `coupled-v1` | Meaning |
| --- | ---: | ---: | --- |
| `register_cooling_rate` | 0.005 | 0.005 | Absolute register cooling per cycle |
| `field_coupling` | 0 | 0.125 | Fractional approach to the same-bank equilibrium |
| `bank_coupling` | 0 | 0.025 | Fractional approach of bank means to machine equilibrium |
| `ambient_cooling_scale` | 1 | 1 | Multiplier on each bank's existing cooling rate |
| `cell_thermal_mass` | 1 | 1 | Thermal mass assigned to one field cell |

These are deterministic emulator coefficients, not measurements of physical
hardware. Changing any value requires a new canonical model identifier rather
than silently changing an existing model.

## `coupled-v1` transition

One successful instruction cycle has the following strict order:

```text
semantic effect
instruction heat
same-bank field exchange
inter-bank exchange
ambient/register cooling
refresh and thermal flags
tick
event
```

For fields `i` in a bank, thermal mass is `m_i = length_i *
cell_thermal_mass`. The mass-weighted bank mean is:

```text
T_bank = sum(m_i * T_i) / sum(m_i)
T_i' = T_i + field_coupling * (T_bank - T_i)
```

The same equation is then applied to each bank mean using `bank_coupling` and
the total mass of each bank. Every field in a bank receives the same bank
delta. Both exchange stages use simultaneous updates, conserve `sum(m_i*T_i)`
before ambient cooling, move temperatures monotonically toward equilibrium,
and cannot overshoot because each coupling coefficient is in `[0, 1]`.

After exchange, cells mirror their owning field temperature. Finally, each
field and cell approaches its bank's existing base-temperature floor through
the existing bank cooling rate. Registers remain independent nodes.
