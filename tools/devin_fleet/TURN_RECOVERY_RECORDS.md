# Turn recovery records (2026-09-19)

## Credential-free Git capability: missing dependency

Fixed maintenance action `--validation-git-capability` creates a fresh container
from the existing pinned Python/Node image, with the usual nonroot/network-none/
readonly-root limits. It uses only a synthetic one-file repository, never project
source or model credentials. Before normal Git init/add/commit it requires an empty
inherited Git configuration and no active hooks; it does not disable security
settings, signing or hooks. It verifies the resulting file/tree and clean status.

Live receipt: `/home/fleet/controller-validation/git-capability-7sqdavgw/receipt.json`.
Image `sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f`
does **not** provide Git (`git_available=false`, `commit_verified=false`).
No commit was attempted. The operation correctly remained `inspection_required`.
The container and all11VMs stopped, and the managed launcher confirmed service
shutdown. Network permission was not changed; no package was downloaded.

This establishes a concrete dependency for candidate construction on the
credential-free side. A separate Git-capable image must be built/acquired and
digest-pinned before that step; do not mutate or silently substitute the existing
tested image. Library acquisition may use the user-authorized temporary network
workflow only inside the dedicated validation VM, with denial restoration and
shutdown verified afterward. The old image-acquisition script has a historical
fixed deny-rule ID and is not suitable for direct reuse.

## Retired same-VM validation path

Candidate-finalization review found that the historical `fleet.validate_repository`
guest branch still dispatched Python inside a model-role VM. That branch cannot be
reused for the separated model/validator design. It now refuses every
`GuestRepository` before process launch or log access, with no host fallback.
The historical `guest_validation_smoke.py` is also retired and fails before VM,
thread or filesystem activity. Its earlier synthetic-command evidence remains
historical, not permission to run generated code in an authenticated VM.

The explicit legacy host-path branch is unchanged; this does not enable the old
Windows fleet or remove its STOP. Sandbox validation must use the source snapshot
and credential-free validator path. This change closes the named legacy entry
points, not every possible use of the trusted controller's generic execute API.

Dedicated-WSL mock verification: 99 tests passed (0.849 seconds), covering arbitrary
valid guest roots, no VM or host dispatch/log access, retired-script refusal,
legacy host compatibility, model-phase contracts and separate result binding.
No actual model, VM, candidate execution or commit occurred. Candidate-finalization
and interruption-safe fence resolution are still missing; the historical lane's
validation-and-commit implementation must not be called to fill that gap.

## Validator-to-turn result association

`turn_validation_result.bind_result` now re-parses the recorded validator stdout
and checks it against the saved summary, turn binding, pinned validator/image,
snapshot/base, container shutdown, VM shutdown and consistent test exit signals.
The authenticated model VM cannot also be the validator. Partial, ambiguous,
duplicate-key or inconsistent records require inspection, not retry.

The real dispatch path records this derived `turn_result` only after VM shutdown.
It distinguishes `test_command_succeeded` and `test_command_failed`, with
`review_required=true`, `production_accepted=false`, `committed=false` and
`resume_available=false` for both. A binding rejection is persisted and returned
as a non-successful dispatch. This does not claim all tests passed merely from
the command exit code; skip/expected-failure policy and semantic review remain
acceptance concerns. No fences are cleared.

Saved JSON is compared with numeric types preserved rather than Python dictionary
equality (`True`, `1`, `1.0` are not interchangeable). The canonical dispatch
evidence digest excludes only its derived `turn_result` field, so recording that
field and re-reading/formatting the journal do not change the evidence identity.

Dedicated-WSL controller tests: 72 passed (0.119 seconds), including successful
and failed test commands, stale/mismatched evidence, shutdown failures, numeric
type aliases and stable re-reading. Both changed controller modules passed syntax
compilation. These are mock tests; no actual turn-bound validation, model call,
commit, production scheduler or automatic resume was performed in this step.

## Turn-to-validator provenance connection

The model driver now writes `capture.json` after the inspection lease has stopped
and the source snapshot is durable, before the final `awaiting_validation` record.
It carries operation, epoch, sequence, role/VM identity, snapshot digest, changed
file fingerprints and inventory counts. A capture write failure leaves the turn
incomplete and its fence intact.

`validation_snapshot_dispatch.py --capture-receipt ... --turn-receipt ...` validates
both explicit controller-owned files. Model-turn captures require the turn receipt;
maintenance snapshots remain separate. The turn must be `awaiting_validation`,
uncommitted and unaccepted, match the capture exactly, and belong to the current
registered migration epoch. Missing registration epoch refuses this path.
The resulting dispatch stores `turn_evidence` with the turn/capture hashes and
identities for later result association. It does not release a fence or commit.

Dedicated-WSL mock verification: 80 tests passed (0.151 seconds), including a real
controller-file round trip from model-phase output through both loaders, rejection
of stale/malformed/mismatched identities and partial/duplicate-key JSON, and durable
capture failure. Initial attempts exposed a missing transferred test module, two
test calls lacking the new required epoch argument, and an indentation mistake in
one updated test; all were corrected before this passing run. No actual model,
validator VM, project code or production scheduler ran in this verification.

This is the provenance connection, not the missing terminal transaction below.
Legacy receipts are not upgraded, production stays disabled, and the next-turn
fence remains unresolved until a separately implemented finalization workflow.

## Continuation gap and shared-runtime admission

Current-source review confirms `run_guest_model_phase` ends at
`awaiting_validation` and keeps its per-role fence. There is no transactional
candidate finalization/rejection workflow to resolve that fence and advance to
another turn. `test_new_output_directory_cannot_bypass_awaiting_validation`
explicitly verifies the next call remains blocked. Authenticating all roles
alone therefore cannot make this implementation run continuously.

The required connection must bind operation/epoch/VM/snapshot to a real validator
result, persist candidate acceptance or rejection/feedback, verify shutdown, and
resolve only that operation's fence with interruption-safe recovery. Do not
substitute fence deletion, a positive model report, or maintenance evidence for
this missing transaction. The validator acquires the same global lock, so it
must not be launched while `SandboxRuntime` still holds that lock.

Runtime entry also previously checked stopped status only for registered model
roles, ignoring an active credential-free validator or other sandbox. It now
rejects any inventory row whose status is not `stopped`, without stopping that
unowned workload. A stopped validator is allowed alongside the registered roles.
Related dedicated-WSL controller mock tests: 61 passed (0.196 seconds), including
validator/unknown workload running, starting, unknown or missing status, lock
release after rejection, and unchanged normal role capacity. No model or VM was
started for these tests; production remains disabled.

The model-phase driver now persists `awaiting_admission` before invoking
the initial admission callback. Each admission check records its stage
(`initial` or `before_model`) and `checking` before invocation, then `passed`
only after normal return. Callback exceptions and interrupts record a
generic `held` / `incomplete` result without copying exception text.
The unresolved per-role fence remains intact; none of these records permit
automatic retry or claim that a VM is stopped.

Before the second (source inspection) VM lease, `inspection_pending` is
persisted. Only successful lease cleanup advances it to `inspection_stopped`.
A crash or failed cleanup therefore cannot leave an apparently current
`model_stopped` record while an inspection VM may be running.

Verified in dedicated EBase-Sandboxes WSL using trusted controller mock tests:
`python3 -E -s -m unittest test_sandbox_turn test_sandbox_turn_fence test_sandbox_turn_inspection`
50 tests passed (0.153 seconds). The model-phase tests prohibit actual model,
host process execution and candidate validation. No real reboot was exercised.

Power loss may leave an in-progress record; failed durable writes can leave
older records. The persistent fence still blocks retries. Runtime inspection
and a separate authorized resolution workflow remain necessary. This change
does not implement production admission, clear STOP, enable production, raise
capacity, resolve fences, authenticate remaining roles, or authorize publishing.

## Export-label consistency

The live model evidence checker accepted both the exact requested UID
`swe-2-high` and the observed CLI export label `SWE-2 High`, but session
recovery previously rejected that observed label. Both now use the same
immutable `fleet.MODEL_EXPORT_NAMES` set. Requests and Free catalog checks
still use only the UID; other variants and case/whitespace approximations
are rejected. Epoch, digest, sandbox identity and prepared-record gates
remain unchanged. Session identity recovery is not runtime resume authority.

Dedicated WSL verification: 102 tests passed in 0.956 seconds across
`test_fleet`, `test_sandbox_recovery`, `test_sandbox_turn`,
`test_sandbox_turn_fence`, and `test_sandbox_turn_inspection`.
An initial test collection failed because `test_fleet.py` had not been
transferred; the missing trusted test file was supplied and the full suite
rerun successfully. No real model, role-VM resume or authentication took place.
