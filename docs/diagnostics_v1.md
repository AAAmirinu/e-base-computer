# Ternary and diagnostic registers v1

This document turns the previously descriptive `TR0..TR7` and `TEMP`
registers into an executable, versioned diagnostic layer.

## TR registers

Each of the eight `TR` registers stores one to 27 balanced-ternary lanes.  A
lane is exactly `-1`, `0`, or `+1`; invalid values fail before state mutation.
The first lane is the scalar condition used by selection instructions.  The
remaining lanes are available to future packed-trit and vector operations.

```text
ETRIT TR0, -1, 0, 1
ETCMP TR1, ER0, ER1 ; epsilon=1e-12
ETSEL ER2, TR1, ER_NEGATIVE, ER_ZERO, ER_POSITIVE
```

- `ETRIT` loads explicit balanced ternary lanes.
- `ETCMP` compares two E registers.  It writes `-1`, `0`, or `+1` according
  to `left - right`, using the non-negative finite `epsilon` option.
- `ETSEL` copies the negative, zero, or positive E-register source according
  to the first lane.  The complete E-register metadata is preserved.

`ETCMP` and `ETSEL` require `observe_discrete`; permission failures are
audited and fail before changing their destination.

## TEMP register

`TEMP` is read-only and derived from the current machine state.  It is not a
mutable register and therefore cannot become stale.  The snapshot contains:

| Field | Meaning |
| --- | --- |
| `tick` | logical time at which the aggregate was sampled |
| `thermal_model` | resolved versioned thermal model identifier |
| `aging_model` | configured/resolved aging model identifier |
| `max_temperature` | maximum of all ER and allocated field nodes |
| `mean_temperature` | thermal-mass-weighted mean |
| `total_thermal_load` | sum of temperature multiplied by node mass |
| `register_max` / `field_max` | per-class maxima |
| `hottest_target` | deterministic name of the hottest node |
| `refresh_due_count` | targets whose refresh deadline has elapsed |
| `min_health` / `max_noise` | worst current degradation indicators |

Every ER has mass `1`; an E field has mass equal to its cell length, matching
the coupled thermal model.  Ties for `hottest_target` are resolved by sorted
target name.  With no allocated fields the 16 ER nodes still define a valid
zero-temperature aggregate.

```text
ETEMP OUT_DIAGNOSTICS
```

`ETEMP` copies the pre-instruction `TEMP` value into output after a `read`
capability check.  It does not heat a node.  The event's `after.temp` is then
the post-cycle aggregate, so consumers can distinguish observation time from
the lifecycle transition.

## Snapshot schema

`visual_snapshot()` and Runtime schema v1 add two backward-compatible keys:

```json
{
  "tr": {"TR0": {"lanes": [-1, 0, 1], "encoding": "balanced"}},
  "temp": {"tick": 0, "max_temperature": 0.0}
}
```

Existing `er`, `ep`, `fields`, and output payloads retain their meaning.
