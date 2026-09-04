# Task Runtime v0

Task Runtime v0 is the stable high-level boundary above the EPU instruction
engine. It makes task identity, permissions, reset behavior, execution limits,
and result shape explicit without changing the assembly language.

## Lifecycle invariant

Every successfully executed instruction, including `EJMP`, conditional jumps,
`EPRINT`, and `EHALT`, passes through the same lifecycle:

```text
semantic effect -> heat -> thermal exchange -> ambient cooling
-> aging -> refresh/thermal flags -> tick -> event
```

For each successful event, `after.tick == before.tick + 1`. A fail-closed
exception under the default `HALT` policy records an exception event but does
not advance time or apply a partial semantic effect. Under `WARN`, the failed
instruction advances through the common cycle and execution may continue.

This corrects the earlier behavior where control instructions advanced the
program counter and event log but skipped cooling and refresh-pressure updates.
When `CR.auto_refresh` is enabled, due maintenance runs in this cycle and is
listed in the event's `maintenance` field so scoring includes its cost.

`CR.observer_mode` accepts `non_destructive` and `destructive`. Destructive
observation deterministically raises the observed register's noise and lowers
health after producing the external value; unknown modes fail with
`MODE_ERROR`.

`CR.thermal_model` is resolved before the semantic effect. `simple` is the
compatibility alias for `simple-v0`; `coupled` selects `coupled-v1`. Unknown
models fail closed with `THERMAL_MODEL_ERROR`, including under the otherwise
recoverable `WARN` exception policy. The coefficient schema and transition
ordering are specified in [Thermal Models](thermal_models.md).

`CR.aging_model` independently selects noise/health evolution. The default
`simple-v0` is the exact compatibility path; `aging-v1` opt-in connects
post-cooling temperature, target-local instruction stress, observation,
refresh, and coupled-field temperature without randomness or a seed. Unknown
aging models fail closed with `AGING_MODEL_ERROR`. Coefficients, equations,
refresh recovery limits, and exact ordering are specified in
[Noise and health aging models](aging_models.md).

## Task identity and capabilities

`TaskContext` contains a `principal` and a set of capabilities. The default
`kernel` context preserves the unrestricted behavior of earlier releases.
Non-kernel callers are checked at the following boundaries:

| Operation | Required capability |
| --- | --- |
| `ELOAD` | `read` on the field |
| `ESTORE`, `ERESTORE` | `write` on the field |
| `EMODE` | `change_mode` |
| `EOBS`, `EPRINT`, `ETRACE` | `observe_continuous` |
| `ETHERM` | `read` |
| `EQOS` | `thermal_control` |
| `EREFRESH` | `refresh` |
| `ESCRUB` | `thermal_control` plus `refresh` on each field |
| `ESNAP` | `snapshot` |

`EALLOC` assigns the active principal as field owner. The kernel and the owner
may operate on that field. Another principal must both hold the capability and
find it in the field's permission set. Denials raise `PERMISSION_ERROR`, leave
the protected state unchanged, and record the principal and required
capability in the event.

Register observations and global thermal operations have no field owner, so a
non-kernel task must hold the corresponding task capability.

## Runtime schema v1

`epu_runtime.RunRequest` accepts:

| Field | Type | Default |
| --- | --- | --- |
| `schema_version` | integer | `1` |
| `source` | string | required |
| `language` | `asm`, `c`, or `cbase` | `cbase` |
| `max_steps` | positive integer | `10000` |
| `precision` | integer from 0 through 15 | `8` |
| `principal` | non-empty string | `kernel` |
| `capabilities` | capability array | empty |
| `fresh` | boolean | `true` |
| `thermal_model` | `simple-v0` or `coupled-v1` and aliases | `simple` |
| `aging_model` | `simple-v0` or `aging-v1` and aliases | `simple-v0` |
| `auto_refresh` | boolean | `false` |
| `observer_mode` | `non_destructive` or `destructive` | `non_destructive` |

`RunResult.to_dict()` returns JSON-ready schema v1 data: canonical language,
generated assembly, symbols, output, halt state, steps, program counter, trace,
complete timeline, final snapshot, score decomposition, principal, reset mode,
resolved `models.thermal` / `models.aging` coefficient fingerprints, effective
`controls.auto_refresh` / `controls.observer_mode`, and the versioned `analysis`
execution summary.  The summary covers the same complete
timeline as the result and remains separate from challenge scoring; see
[Execution Analysis schema v1](execution_analysis_v1.md).

Unknown schema versions, languages, capabilities, models, and invalid limits fail
before execution.

The same fields are accepted by the local Playground `/api/run` payload.  The
CLI exposes them as `--thermal-model`, `--aging-model`, `--auto-refresh`, and
`--observer-mode`.  This keeps model and maintenance/observation policy above
assembly text while recording canonical identifiers, coefficients, and
effective controls in every result.

## Fresh and session execution

`fresh=true` is the default. It replaces the complete EPU state, including
registers, memory, output, tick, trace, and events. This is the mode used by the
CLI and each stateless Playground HTTP request.

`fresh=false` is an explicit continuation mode on a persistent `EPURuntime`
Python object. It reuses EPU state and may change the active principal. A
continuation without a preceding fresh run is rejected. This makes state reuse
intentional rather than an accidental consequence of reusing an emulator
object.

```python
from epu_runtime import EPURuntime, RunRequest

runtime = EPURuntime()
runtime.run(RunRequest("ECONST ER0, 2", language="asm"))
result = runtime.run(
    RunRequest("EPRINT ER0", language="asm", fresh=False)
)
```

## Compatibility

`EPU()`, `EPU.step()`, `EPUEmulator()`, the existing CLI commands, and the
Playground payload remain supported. Callers that do not provide a
`TaskContext` execute as `kernel`. The current official challenge outputs are
unchanged. Its score is now `366.6`: control instructions receive corrected
per-tick cooling and promoted initializer registers remove redundant `EMOV`
instructions from the two C-like cases.
