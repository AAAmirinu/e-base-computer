# Execution Analysis schema v1

`RunResult.analysis` is a deterministic, JSON-ready projection of the complete
EPU timeline.  It is an observability layer, not a challenge score and not an
empirical fidelity claim.

## Scope

For a fresh run the projection covers that program.  For `fresh=false` it covers
the complete retained session timeline, matching `RunResult.timeline`.  Calling
the analyzer does not mutate registers, memory, thermal state, or the event log.

Schema v1 reports:

- exact opcode, instruction-group, status-flag, maintenance, and model counts;
- observation, branch, refresh, degradation, and exception event counts;
- the first exception as `{tick, op, code}`;
- peak and final temperature, peak noise, minimum health, and their target;
- peak refresh-due pressure; and
- whether event ticks are contiguous integers.

Counts use lexically sorted object keys so repeated runs have stable JSON.  The
thermal/noise/health extrema inspect all ERs, fields, and field cells present in
each post-cycle snapshot.  Floating values are rounded to 12 decimal places in
the summary only; the normative timeline remains unchanged.

## Stability boundary

`analysis.schema_version` is `1`.  New optional fields require an additive
schema change; changed meanings or removed fields require a new schema version.
Unknown future opcodes are retained under their exact opcode and assigned the
instruction group `unknown`, so diagnostics do not silently discard events.

The analysis is intentionally separate from `RunResult.score`: score remains
the versioned challenge cost function, while analysis describes execution
behavior for tooling, profiling, and model comparison.
