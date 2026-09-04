# EPU Conformance Matrix

This matrix distinguishes implemented behavior from declared metadata and
future fidelity work. The executable Python runtime and its tests are the
current normative reference; there is no claim that this fictional machine is
calibrated against physical hardware.

Status vocabulary is `Implemented`, `Partial`, and `Not implemented`. No row
in the current matrix is classified as `Not implemented`.

| Area | Status | Current evidence or limit |
| --- | --- | --- |
| Finite signed E-word arithmetic | Implemented | Normalize, add, multiply, shift, finite input and exponent-domain checks |
| Native instruction lifecycle | Implemented | Shared heat, cooling, due flags, tick, and event ordering |
| Control instruction lifecycle | Implemented | Branches, print, and halt now use the same cycle |
| E-memory banks and fields | Implemented | Allocation, load/store, bank thermal parameters, field snapshots |
| Field ownership and capabilities | Implemented | Fail-closed checks with auditable `PERMISSION_ERROR` events |
| Task runtime schema | Implemented | Versioned fresh/session API shared by Python, CLI, and local Playground requests; thermal/aging model and auto-refresh/observer controls are validated before execution, and resolved fingerprints/effective controls are returned |
| Versioned execution analysis | Implemented | `RunResult.analysis` deterministically aggregates instruction mix, maintenance, errors, model use, refresh pressure, and thermal/noise/health hotspots without changing the normative timeline or challenge score |
| Target-local QoS degradation policy | Implemented | Register and field `allow_degrade` no longer mutate global policy |
| Quantization partition domain | Implemented | Requests are limited to `3, 9, 27, 81, 243` |
| Thermal coefficient calibration | Partial | `simple-v0` and `coupled-v1` publish deterministic schema-v1 coefficients. A versioned independent dataset contract and read-only residual evaluator now separate self-consistency from calibration, but the repository contains only an explicitly synthetic fixture and no independent empirical dataset. |
| Metadata propagation | Implemented | Schema-v1 machine-readable rules cover all 38 opcodes and every value metadata field, separating semantic preserve/copy/reset/derive/aggregate effects from common heat/cooling/aging; behavior tests pin reducers, invalidation, observation atomicity, and snapshot restore |
| `noise` and `health` evolution | Implemented | Default `simple-v0` preserves compatibility; opt-in `aging-v1` is versioned, seed-free, monotone during ordinary cycles, and connects temperature, target work, observation, and bounded refresh repair |
| `auto_refresh` | Implemented | Due registers/fields refresh within the shared cycle and maintenance is visible/scored in the event |
| `observer_mode` | Implemented | `non_destructive` and deterministic `destructive` register observation are executable |
| `thermal_model` selection | Implemented | `simple`/`simple-v0` preserve compatibility; `coupled`/`coupled-v1` execute conservative field and bank heat exchange |
| Field-local interference | Implemented | `coupled-v1` exchanges field heat conservatively before `aging-v1`, so post-exchange neighbor temperature drives deterministic field/cell noise and health evolution |
| TR registers and TEMP register | Implemented | Eight strict balanced-ternary registers support explicit lanes, epsilon comparison, metadata-preserving selection, and a read-only mass-weighted TEMP aggregate exposed in snapshots/runtime results |
| Full opcode behavioral matrix | Implemented | All 38 public opcodes have table-driven success and representative failure/error-code tests; spec, dispatch, and case sets must match exactly |
| Python/server/static-JS parity | Implemented | `conformance/runtime-v1.json` covers five server/browser scenarios. Schema-v1 ASM parity covers the exact 38-opcode set, discrete state/output/control flow, and exact diagnostics with documented `1e-9` real/thermal absolute tolerances. Static C-like source also compiles to byte-identical Python assembly and preserves the `366.6` baseline. |
| Independent compiler oracle | Implemented | A fixed-seed parameter/AST-level oracle checks 40 generated nested loop/branch programs, all six comparisons, output order, and deterministic assembly |

## Acceptance gates for the next fidelity stages

1. All public opcodes have table-driven success, failure, error-code, flags,
   and tick-transition tests; the executable and published opcode sets match
   exactly.
2. A fixed-seed E-word property corpus proves digit range, normalization value
   preservation, and arithmetic tolerance across the supported exponent range.
3. Thermal tests pin heat/cooling order, bank ordering, `q_max` monotonicity,
   quantization error bounds, refresh deadlines, and exact degradation policy.
4. Noise, health, observation, and automatic refresh models are versioned,
   deterministic, and represented in trace events. Any stochastic model must
   record its seed.
5. C-like programs are compared with an independent small AST interpreter for
   generated nested expressions and control flow.
6. The versioned JSON conformance corpora continue to run through Python,
   local server, and static browser runtimes with zero unexplained
   discrete-state mismatches and documented float tolerances.
7. Correctness and conformance remain fail-closed before challenge scoring;
   score changes record their lifecycle/model version and updated baseline.
