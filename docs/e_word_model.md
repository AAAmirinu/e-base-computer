# E-word Model

This document defines the compact technical model used by the emulator. It is
the public replacement for narrative or conceptual background material.

## Representation

An E-word stores a sign and a sparse mapping from integer exponent to a real
digit. Its decoded value is:

```text
value = sign * sum(digit[k] * e^k)
```

Each normalized digit is in `[0, e)`. The emulator uses finite precision and a
finite set of exponents; it is not a claim about physical hardware.

## Observable State

An E-word or E-memory field also carries operational metadata used by the
emulator and challenge scorer:

- temperature and estimated noise;
- quantization partition and degradation flags;
- guard-band and refresh state; and
- observation and execution timeline events.

Arithmetic, normalization, quantization, refresh, and their deterministic
scoring effects are specified by [epu_spec.md](epu_spec.md) and exposed by
`ebase spec --json`.

For a worked explanation of heat costs, cooling, safe partitions, degradation,
observation, refresh, and challenge scoring, see
[behavior_model.md](behavior_model.md).

## Scope

The model exists to make compiler experiments reproducible. The authoritative
behavior is the released emulator implementation and its test suite.
