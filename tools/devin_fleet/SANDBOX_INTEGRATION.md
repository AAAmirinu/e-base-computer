# Production isolation integration map

Status: design grounded in current code, not an implemented production adapter.
The existing fleet must stay stopped. Running its entire controller inside the
outer WSL distro would not isolate roles from controller receipts or each other.

## Implemented dispatch slice (2026-09-17)

Source snapshot connection: `sandbox_snapshot` captures sorted tracked and
nonignored untracked source files, respecting tracked deletions and preserving
Git executable modes. It refuses linked/special files, controller/private paths,
malformed inventories, per-file >1 MiB, >2048 files or total >16 MiB. This is
path-based isolation of known metadata, not a semantic secret scanner. Capture
requires a quiescent lease and matching model-phase base/change fingerprints;
it is not atomic against another guest writer. Credentials are never read from
the agent runtime directory. Git index, branches and source files are not staged
or committed by this capture operation.

`run_guest_model_phase` captures during inspection, stops the VM, then persists
hash-named inert blobs and publishes the manifest last. Original source paths and
modes remain metadata; no source code is materialized or executed on the outer
controller. The awaiting_validation receipt binds the manifest digest. Separate
credential-free materialization/test execution is still not implemented.

Live storage snapshot: 156 files, 1,193,925 bytes, 152 distinct blobs; manifest
SHA256 `11ae09248ff91a77e069ff7eaf6921b9247d1a6cc63897399a78fbbc6782febc`,
base `e7271a6eaca0204c77925ed6e5723412a1c4477e`. Persistent outer evidence:
`/home/fleet/controller-validation/snapshot-evidence-b5bcef2169474269b2bc5b3ecfbde7ff`.
Source HEAD unchanged and VM stopped. Receipt:
`.ai/sandbox-source-snapshot-20260917.json`. Windows suite: 171 tests, 169 passed
and two Linux-only skips. Dedicated Linux repository/snapshot/turn tests: all 60
passed. Duplicate-field rejection refinement was unit-tested after live capture
started; live capture exercised valid helper responses. No model or validation
test executed and no production admission was enabled.

`sandbox_turn.run_guest_model_phase` now connects staged guest args/digests to
`execute_model_attempt`, exits the owning lease, then opens a new lease for
checkpoint/ownership/fingerprint inspection. A fresh outer turn receipt moves
through admitted/prepared/model_stopped to awaiting_validation only after both
leases stop. Nonzero model exits hold without automatic permission retries.
Legacy/foreign session state, STOP, deadline and disabled production registration
refuse admission. No host lane fallback, source sync, generated-code tests,
validation acceptance, candidate commit or state.sessions update is performed.

This is the connected model/checkpoint phase, not a complete role turn. It has no
CLI route and no production admission provider: the trusted callback must still
implement verified auth/free-catalog/policy/capacity/host-boundary checks. The
stored registry remains production_enabled=false. Credential-free snapshot
validation and journaled candidate commit are the next functional stages; tests
must not execute in the authenticated model VM. A mocked model-phase test is not
evidence of real model or safety-gate acceptance.

Connected-phase tests: 16 passed on Windows and dedicated Linux, using mocked
model/VM helpers with host subprocess/Git execution forbidden. Tests cover exact
staged args/digests, stop-before-inspection ordering, failure to stop either
lease, gate/STOP/deadline/foreign-session rejection, wrong model, nonzero exit
hold/no retry, absent report/ownership rejection and unvalidated coordinator
decision storage. Full Windows sandbox suite: 142 total, 140 passed and two
Linux-only skips. No live model phase was run, and no admission gates were marked
verified by these fixtures.

Metadata migration follow-up: bundle-only clones do not inherit the old local
`.git/info/exclude` rule for `.fleet/`. Empty-template clones also omit the info
directory. `sandbox_metadata.configure_guest_metadata` restores an anchored
`/.fleet/` exclusion, preserving original bytes in a unique guest backup and
checking replacement digest/unchanged HEAD. Missing info is created; linked or
special Git metadata and tracked `.fleet` files are refused. Only a final
effective exclusion is treated as idempotent, so a later unignore cannot silently
defeat the setup. This is local Git configuration, not deletion or source commit.

The initial live attempt refused the absent info directory without configuration
changes; the corrected sequential ten-role migration passed. Its probe
compares all non-controller source paths and fingerprints before/after, including
dirty role files. Full Windows sandbox suite: 126 tests, 124 passed and two
Linux-specific skips; metadata helper: 15 passing tests. The latest trailing-rule
refinement was made after live process startup and was unit-tested on Windows
and dedicated Linux (all 15 metadata tests passed); live inputs had empty
exclusion files, not conflicting prior rules. All ten roles gained the local
rule and a backup; all HEADs and non-controller file fingerprints were unchanged.
Uncommitted source counts remain stdlib=4, applications=5, devtools=12, others=0.
All owned VMs stopped. Receipt `.ai/sandbox-metadata-migration-20260917.json`
records each guest backup and hashes. Previous real-role dirty-worktree refusal
included these unexcluded control artifacts; future checks now distinguish them
from actual source changes. Source migration state and legacy STOP are unchanged.

Maintenance operations now have a dedicated-Linux CLI: `sandbox_driver.py`.
See `SANDBOX_OPERATIONS.md` for verified status, explicit sync inspection and
the boundary between maintenance and the still-unimplemented production runner.
Status does not enter/start the runtime. Inspection preserves STOP and requires
fresh private evidence. Runtime STOP checks use lexists and its Linux global lock
has a fixed /tmp path, independent of environment-controlled temporary roots.

Object transfer follow-up: `sandbox_transfer.transfer_commit` exports a bounded
self-contained reachable-ref bundle inside the source VM, reads it as inert
bytes through the controller, and writes/verifies/fetches it in a sequential
target lease. Git never runs on the outer host. Fetch uses no-tags and
no-write-fetch-head; no merge, checkout, remote configuration or automatic retry
occurs. Exact requested commit and unchanged source/target HEAD are verified.
Current export creates a retained, create-only operation ref for the requested
commit and bundles its complete history, including otherwise unreferenced
candidates. The bundle must fit 16MiB. See the transfer hardening evidence below;
the first live transfer described next predates this refinement.

Real `sandbox_transfer_smoke.py` transferred storage candidate
e7271a6eaca0204c77925ed6e5723412a1c4477e into coordinator, 568991 bundle bytes,
with matching SHA256 and commit identity. Coordinator remained at
5f676710e5b2fdadbcb3a3fc421c98ddd1e0af93. Both leases ended stopped. Evidence:
`.ai/sandbox-object-transfer-20260917.json`. Bundle/part files remain as guest
evidence; source legacy STOP/state are unchanged. No model, project tests, merge
or Fable external audit ran. Branch synchronization and integration transactions
must still be connected through this transport before production activation.

Ownership follow-up: both lane pre-test and post-test ownership checks now call
`check_owned_changes`; guest handles use no-follow VM metadata rather than
`(repo / path).is_symlink()` on the host. Guest regular files and missing paths
(deletions) pass ownership checks; symlinks, multiple-link regular files,
directories and special files are rejected. Symlink parents fail no-follow
traversal. Missing repository roots remain errors. Checks require quiescence,
not a claimed atomic snapshot against a concurrent guest-root process.

Eight ownership tests, 15 repository tests and existing 42 fleet tests passed.
Real `guest_ownership_smoke.py` accepted a regular synthetic file and absent
nested path, then rejected a symlink, hardlink, FIFO and symlink parent through
separate leases, each fenced and stopped. Fixtures remain in the dedicated
.fleet/ownership-probe directory. No model/project code ran; original STOP and
state hash remain unchanged. This removes these specific host path callsites,
not the remaining legacy branch sync/recovery or full production scheduler.

Checkpoint retrieval follow-up: the lane's two report reads and coordinator
decision read now use `read_repository_json`. Guest handles use bounded VM reads
and reject non-object JSON, duplicate keys, malformed UTF-8, non-finite constants
and float overflow. Missing guest checkpoints are errors, not empty defaults;
any parsing/read failure fences via the lease controller. Existing local-path
behavior is retained but must not be selected for sandbox production.

Four new checkpoint tests and existing 42 fleet tests passed. Real
`guest_checkpoints_smoke.py` read a synthetic valid report, then rejected a
duplicate-key report and verified a fenced/stopped VM. The later float-overflow
check was unit-tested, not part of that live probe. Probe files remain in their
unique .fleet/checkpoint-probe directory, not the actual checkpoint paths.
No model, generated project code, integration or external audit ran. The current
legacy source STOP and state hash remain unchanged. File parsing is not evidence
that report claims or coordinator approvals are true; independent validation and
the remaining production integration gates are still required.

Coordinator evidence follow-up: `collect_guest_candidate_patches` sequentially
leases owner VMs, verifies exact recorded base/candidate objects and ancestry,
and retrieves log plus binary/full-index diffs with external diff/textconv off.
It preserves whitespace, hashes evidence bytes, and refuses oversized results
without truncation. No host Git or model call is used in this path.

Real `guest_candidates_smoke.py` collected all 13 pending candidates, 362717
bytes total, then passed them with the complete stopped-round context through
`prepare_guest_turn` into coordinator
`.fleet/control-e68ee97f01a74b9082a730126cb7e2e3`. All 13 destination SHA256
values matched; coordinator HEAD stayed
5f676710e5b2fdadbcb3a3fc421c98ddd1e0af93. Owned VMs stopped after each lease,
including the coordinator at the end. Receipt:
`.ai/sandbox-coordinator-evidence-20260917.json`. This is review-input transfer,
not candidate approval, integration, or model execution. Existing source
STOP/state remained unchanged.

Eleven new candidate tests passed; all 39 guest tests and existing 42 fleet tests
passed. Authentication, catalog/admission, production scheduling and guest
integration/recovery remain unfinished; Fable external audit remains not_run.

Large-input follow-up: `GuestRepository.write_large_bytes` uploads at most 16MiB
as <=32KiB parts into a unique sibling directory, then verifies every part size
and the complete SHA256 inside the VM before atomic destination replacement.
No-follow file/directory checks, output fsync and directory fsync remain in
effect. Failed/ambiguous operations fence; parts remain as recovery evidence.
Chunks still travel in process arguments: non-secret inputs only. Successful
transfer can retain up to another payload-sized copy, so disk budgeting must
include parts. No concurrent guest writer or power-loss guarantee is claimed.

Input staging now selects this transfer for larger metadata files while keeping
config/prompt at 32KiB and the full operation at 512KiB. Real `guest_turn_smoke.py`
prepared the actual stopped round-6 machine context: 90131 bytes, SHA256
b3428c8e9c41e6637c9917185cf321c491b3eae904ea9ff9093de83cba110053,
under `.fleet/control-9020ff34b56341539f96b2f4a6a4dffc`. Reports/candidates/shared
notes matched the complete source objects; old session IDs were not adopted;
HEAD stayed 472781a6c824ec8201d8e23ab06a1e08322be045. A deliberately corrupted
chunk failed full-digest validation and stopped the VM. A separate owned lease
confirmed the old target bytes remained intact, then stopped again.

Four transfer tests passed in Linux; 28 guest tests and 40 sandbox tests passed
on Windows. The exact 16MiB/512-part boundary is mock-protocol tested, not a live
16MiB transfer. Real metadata staging resolves the previously recorded 32KiB
context blocker. Legacy STOP/state hash remain unchanged. No model/auth call or
Fable external audit ran; full scheduler/recovery/isolation cutover is unfinished.

Turn preparation follow-up: `prepare_guest_turn` connects trusted role/mission
generation, driver context, prior report, ownership map and guest Git inventory
to fresh VM input staging. It verifies the role/root mapping, does not adopt
legacy state session IDs, requires all pending coordinator patches explicitly,
resets output checkpoints only after input staging, and checks unchanged HEAD.
Input references target the fresh control directory; shared notes are supplied
in context rather than treating stale coordinator files as current evidence.
This does not sync branches, run the model, test code, or commit a candidate.

Staging now supports explicit extra input files with per-file 32KiB and total
512KiB preflight limits; it refuses oversized contexts rather than truncating
evidence. Three preparation tests passed plus the existing input tests. Actual
legacy state is 164012 bytes. A read-only UTF-8 serialization of the current
context fields measured 90706 bytes (PowerShell formatting), above the 32KiB
per-file limit; current full-context preparation cannot use this small-file
transport. Large context/patch transfer remains a required integration step.
No model or authentication operation was started while waiting for user login.

Input staging follow-up: `stage_guest_model_inputs` builds policy with explicit
guest paths using the same `permission_config` builder as legacy configuration.
It prevalidates input sizes/path patterns, creates a fresh .fleet/control-UUID
directory through no-follow guest directory operations, writes bounded nonsecret
config/prompt bytes, verifies both hashes, and returns explicit model arguments.
The model transport now also requires and rechecks the prompt digest. Staging
control paths receive a CLI Write deny; this is not root-user immutability.

Ten input/model tests passed in dedicated Linux; existing 42 fleet tests passed
after the policy-builder refactor. The real `guest_inputs_smoke.py` staged into
machine `.fleet/control-75789906e3514d238b5d5147c4c86dc3`, verified both hashes and
absent export, preserved HEAD, then confirmed existing-leaf creation fails and
fences/stops the VM. The synthetic input files remain as guest evidence and are
not a claim of a clean working tree. Config SHA256:
ab3417e37fe090ac52263736e2b1fd9bb9cb505211bc541cccef7f7bb12d44d0;
prompt SHA256: a34771790881279463764c1e4d9c3d07c34264c6e6b4f2a0126009afa781718f.
No model invocation occurred. Legacy lane orchestration still needs to call this
staging path; runtime/state/candidate integration and admission remain unfinished.

Runtime ownership follow-up: `SandboxRuntime` binds exact ten-role registration
to fresh per-lease controllers/GuestRepository handles. It takes the shared
Linux GlobalLock, verifies every registered VM is stopped before entry, caps
leases at verified capacity (currently one), binds external STOP, and stops the
VM at lease end. A failed stop poisons the runtime. No old controller is resumed.
Lease-controller proxies revoke both execution and stop authority, preventing a
stale GuestRepository error handler from stopping a newer same-VM lease.

Six new runtime tests passed on Windows and dedicated Linux; all 40 sandbox
tests passed on Windows. Real `sandbox_runtime_smoke.py` used the actual registry,
read machine HEAD across two leases, rejected an old repository call during the
new lease, verified the new lease still worked, then read applications HEAD and
its five dirty paths. Final owned VM stops succeeded. No model/project code ran.

This runtime is currently for trusted maintenance only. It is not yet the
production lane scheduler and does not satisfy catalog/auth/security admission.
Other local Windows processes are not serialized by the Linux GlobalLock; legacy
fleet STOP must remain. A maintenance lease is not permission to start Devin.

Recovery separation follow-up: an `execution.json` marker now refuses legacy
prepare, loop, configure, finished recovery, integration recovery and integration
reconciliation before state/host operations. Even malformed or broken-link
markers cannot silently select the local backend. No marker was installed in
the original run, and no new production root has been activated.

`sandbox_recovery.recover_sessions` validates explicit controller-selected
receipt/export pairs without filesystem scans, VM starts or Git. Only current
migration epoch + registered VM identity + verified export digest/model/session
can provide identities. Legacy/foreign epochs and prepared-only operations do
not resurrect sessions; ambiguous sequences or duplicates are rejected. It
returns a copy, preserving candidate state. This is session validation only,
not candidate recovery or a complete restart implementation.

Guest model operation receipts now include migration epoch and ordered sequence;
these are required inputs for guest launches. Five recovery/guard tests and six
model boundary tests passed. No actual session resumed and no Fable external
acceptance occurred. Remaining work includes trusted file selection/persistence,
guest candidate/integration recovery, and the sandbox runtime entrypoint.

Model transport follow-up: the existing lane launch now calls
`execute_model_attempt`. Local lanes retain their previous runner; guest handles
require explicit guest paths, exact Devin/SWE-2/Normal flags, a driver-approved
config SHA256, absent export, and a fresh outer operation receipt. Config bytes
are checked before/after; model and resumed-session evidence are checked before
returning results. Guest receipts record operation ID/VM UUID/export hash rather
than pretending a client PID is a guest model PID. Result retrieval now carries
the fleet STOP through GuestRepository. No fallback or automatic resume occurs.

Six model boundary tests passed (mock transport, no model calls), all 17 guest
dispatch/validation/model tests passed, repository tests passed all 15 after the
global STOP retrieval test, and existing fleet tests passed 42. The initial model
fixture accidentally used Mock's reserved name keyword and failed serialization;
explicit fixture attributes fixed the test, not production receipt behavior.

Still required before model launch: actual guest CLI/path compatibility, fresh
free-model catalog/account/capacity admission, staging immutable approved policy
inputs, and model-credential boundaries. Hash checks are not protection against
a concurrent guest-root process changing and restoring a config. Recovery still
scans legacy attempt files without a VM migration epoch; it must be migrated
before operation receipts can be used for restart. Existing lane construction
still produces host paths and guest dispatch intentionally rejects those.

Validation follow-up: lane unit-test and integration publication-audit callsites
now use `validate_repository`. Guest handles select `/usr/bin/python3` inside
their recorded VM, pass a distinct absolute fleet STOP to controller polling,
retain only a bounded log tail and propagate fencing as RunInterrupted, not a
failed candidate. Local handles still use the old local runner; production
repository construction is NOT migrated and this is not production isolation.
The caller still owns final quiescence after successful validation; normal CLI
exit alone is not proof that generated descendants are gone.

`SandboxController.execute(external_stop=...)` checks fleet STOP before spawn,
after identity lookup and throughout execution. It never deletes that marker.
Five race/lifecycle tests and four validation-routing tests passed; dedicated
Linux also passed all nine. `guest_validation_smoke.py` waited for an actual
trusted guest process to print its running marker, then raised a synthetic global
STOP: the running operation was interrupted, VM stop verified, and explicit role
resume left the fleet marker intact. Original legacy STOP/state were untouched.
No model or generated project code was executed in this test.

The existing `git`/`sha`, `changes`, and `fingerprints` helpers now explicitly
dispatch `GuestRepository` handles through the isolated controller. Guest handles
reject host path/string coercion, and `run` refuses them as cwd/argv. Changed
paths use NUL framing with no rename collapse and malformed-frame rejection.
Fingerprints distinguish missing files from missing repository roots and reject
links/special files rather than silently treating every failure as absence.
Multi-file fingerprints require quiescence, not a claimed atomic snapshot.

Evidence: seven new routing/protocol tests passed on Windows; all 28 existing
sandbox tests passed. Dedicated Linux passed the 21 dispatch/repository tests.
`guest_dispatch_smoke.py` exercised actual applications guest HEAD, five dirty
paths, known SHA256, absent nested file, directory-error fence and missing-root
fence; it passed and the controller stopped its VM. No model/project code ran.

This is not production cutover: constructors/callers still use local Paths;
lane model/tests, integration, recovery, and other file operations remain to be
migrated. The legacy launcher must remain stopped. Do not infer containment from
these helpers while other host execution paths exist.

## Required execution boundary

Keep state, holds, journals and verified receipts outside model-writable VMs.
Represent each repository by recorded sandbox UUID, role and absolute guest path,
not by an outer-host Path. Every operation on a model-writable repository must
dispatch through that boundary, including apparently read-only Git commands.
Git config, hooks, filters, textconv, fsmonitor, signing and remote helpers can
execute code. Never copy guest `.git/config` or hooks into a trusted host checkout.

| Existing function | Required replacement |
| --- | --- |
| `run`, `git`, raw subprocess calls in `rework_patch` and `reconcile_integration` | Explicit guest repository dispatch; no local fallback |
| `init` | Guest integration and role repositories; credential-free source import |
| `archive_rework_lane`, `sync_lane` | Guest fetch/checkout/merge/archives; remap saved host paths |
| `recover_finished`, `recover_integration` | Guest HEAD/tree/log/fetch/merge; bounded inert receipt retrieval |
| `lane` coordinator patch preparation | Produce patch text in source VM; transfer inert data to coordinator |
| `lane` model execution | Guest config/prompt/export paths, Normal mode, exact SWE-2/session checks |
| `lane` tests and commit | Auth-free, network-denied validation of immutable candidate; guest Git commit |
| `integrate` gate and publication audit | Guest clone/merge and entire publication audit including subprocesses |
| `catalog_check` | Trusted identity/agent boundary, retain current free-model admission check |
| `check_existing_sessions` | Registered sandbox identities and owned operations; host process list is supplemental |
| PowerShell Start/Resume/RunOnce/StopAndWait | Guest-aware prepare/recovery and actual sandbox stop verification |

Important: `prepare` invokes integration recovery before Resume clears STOP.
That recovery can fetch/merge on the host. Routing only the ordinary cycle's
model/test calls leaves this path uncontained.

## Controller contract

`SandboxController` now requires `sandbox_id` (canonical recorded UUID), checks
it on resume, before exec, before stop, and after stop. A same-name replacement
is neither executed nor stopped. The registration must be controller-owned;
never adopt an ID from a model report. UUID lookup and named sbx operation are
not atomic: retain exclusive cross-process ownership and forbid concurrent
manual replacement while a controller owns a sandbox.

Use per-sandbox STOP files, plus a separate fleet-wide admission barrier. Explicit
per-sandbox resume removes its own marker, so it must never receive fleet STOP.
The controller must own all clients; drain queued/active execs before stopping.
Keep this gate closed after unknown status, failed stop, or identity mismatch.

Next implementation interfaces: guest Git, guest file/stat/fingerprint access,
bounded log/report retrieval, immutable snapshot validation, controlled object
transfer, and UUID-bound driver receipts. Migration must preserve dirty edits,
ten session histories, candidate objects and integration ancestry; fresh guest
authentication does not prove legacy session IDs are portable.

## Evidence and remaining gates

### Implemented repository boundary primitives

`sandbox_repository.py` provides `GuestRepository(controller, guest_root, log_dir)`
with guest-only Git, bounded regular-file reads and SHA256. Fixed Python code is
sent through the UUID-bound controller; no guest Python or Git executes on the
outer host. File opens walk directory descriptors with no-follow, reject special
files, and use nonblocking open so a FIFO cannot hang a read. Responses have a
per-operation marker and strict JSON/base64 shape; this handles startup banners
and bounds parsing, but is NOT authentication or proof a compromised guest told
the truth. Operation failure stops/fences the owned sandbox, including missing
files; callers must not silently retry with wider permissions or host fallbacks.

`sandbox_control.py` also rejects excessive log output before accepting exit
success. This is polled and may overshoot between checks, not a hard disk quota.

Live Linux validation on 2026-09-17: 25 controller/repository unit tests passed.
`sandbox_repository_smoke.py` passed actual guest Git init/rev-parse, a Git helper
whose kernel differs from outer WSL, persistent marker read, traversal refusal,
symlink refusal and FIFO refusal. Both latter errors stopped/fenced the sandbox;
final independent listing was stopped. Synthetic `repo-probe-*` directories stay
inside the test VM; no project source was imported or model invoked.

Windows regression before repository tests were added: all 109 tests passed in
normal host execution context. A restricted run had four errors in legacy
process-tree termination/cleanup; the seven focused process tests passed when
retested in normal context. Do not conceal that environment-dependent result.

Production `fleet.py` still uses local paths and subprocesses. These primitives
are not yet a complete adapter: general source transfer/listing/stat, cross-VM transfer,
immutable test snapshots, integration recovery and receipt binding remain needed.

### Small non-secret guest writes

`GuestRepository.write_bytes` now transfers at most 32 KiB per call through the
native Linux controller. Payloads are encoded in process arguments: credentials
and other secrets are forbidden. Parent directories must already exist. The
guest opens parents without following symlinks, rejects nonregular destinations,
writes an exclusive temporary file with mode 0600, fsyncs, atomically replaces,
then fsyncs the directory. Existing executable permissions are deliberately not
preserved, so this is for context/config/prompt data, not general source migration.
Digest mismatch or uncertain execution stops/fences the owned sandbox.

Requires no concurrent writer/model. Same-user/root guest races are not prevented
by a client-side protocol. A failure after replacement may mean the write already
committed; no automatic retry is safe. Returned digests are guest claims, not
independent attestation. Native Linux avoids Windows command-line size limits.

2026-09-17: 28 controller/repository tests passed in Linux; the live smoke passed
new-file creation, replacement, empty payload and symlink/FIFO write refusal.
The extended live smoke also passed exact 32 KiB binary round-trip, mode 0600,
and replacement of a hard-linked destination without changing its other link.
No existing role source/configuration was migrated, and no model was invoked.

2026-09-17: 13 controller contract tests passed in dedicated Linux, including
same-name replacement rejection. Real single-VM smoke passed marker persistence,
timeout stop and post-stop refusal. These do not prove full fleet integration.
Clipboard text-write containment, model endpoint admission, source/history
migration, ten-role memory allocation and complete restart recovery remain open.
### Journaled fast-forward synchronization — 2026-09-17

### Epoch-bound recovery inspection — 2026-09-17

Recovery integrity follow-up: require the complete producer transfer shape,
exact operation-bound bundle path/ref, valid source SHA and integer byte count
1..16 MiB. Before non-no-op verified_applied, resolve both recorded commits and
verify before is the merge-base of before/baseline. This closes false acceptance
of a syntactically valid but nonexistent/unrelated before commit. All 95 sandbox
tests passed, including 16 recovery inspection tests. No replay is authorized.

An explicit post-merge/pre-completion exception probe passed on independent
VM repos. Its retained outer evidence directory is
`/home/fleet/controller-validation/interruption-evidence-979232ccf9954d10aaf67ddff1f8daf2`.
This is controlled driver exception injection, not physical power loss. It
loaded the preceding recovery checker; a separate reinspection with the above
lineage/shape checks also passed after the probe finished. Merge invocation count
was exactly one, applying receipt bytes remained unchanged, updated content and
original outer role HEADs were verified, and all owned leases stopped.
Operation `97662573b97e4c319129118831003566`, epoch
`515de445-6292-4b9f-b942-f084096ced7b`, recovered HEAD
`61f71c61fa0a2a7a64ac805c475dcb3490ecdb10`, original receipt SHA256
`c112c3a9ef8adb6d3e681777275cfa4dfd4a04182db133a688017e5d615da8ac`.
Both inspections returned verified_applied and replay_permitted=false. The
updated 16 recovery tests passed on dedicated Linux as well. Original probe
receipts, result.json and reinspection evidence remain on disk. Legacy fleet
STOP and state SHA256 remained unchanged. Actual OS reboot/power-loss behavior,
partial filesystem checkout interruption and production scheduler activation
are not established by this controlled exception test.

Sync receipts are now schema 2, with operation ID and canonical migration epoch;
the caller registration must explicitly specify backend=sandbox plus that epoch.
The stored provision-only registry is deliberately NOT activated or assigned a
production epoch. Probe scripts use separate ephemeral test epochs.

`sandbox_sync_recovery.inspect_sync_recovery` accepts bounded raw receipt bytes
and an explicit expected operation. It rejects legacy/foreign records, duplicate
keys, floating-point/nonfinite numbers and mismatched nested transfer bindings
before VM admission. It compares real target path, HEAD, branch attachment,
cleanliness and operation markers, stops the lease, then writes separate
inspection evidence with the original-byte SHA256. Original receipts remain
untouched. Applying/complete plus matching clean baseline yields verified_applied;
pre-application phases at before yield pre_application; ambiguous combinations
remain inspection_required. No result permits replay, merge, reset or resume.
Interrupted inspection/stop failure retains checking, never a final verdict.

All 91 sandbox tests passed (30 synchronization, 12 recovery-inspection tests
included). A nonfinite nested transfer number regression initially exposed a
parser gap; float parsing is now rejected and the entire set rerun successfully.
Initial live no-op attempt on the original storage repository refused dirty
worktree state without mutation. The next probe targets the previously created
independent guest probe repository instead passed: no-op receipt reconciled,
original bytes unchanged, target VM stopped. Operation
`92ca78738e69424b98c0fc9abb664bef`, probe epoch
`19e8ae3f-1cc9-4bf3-a229-3c650608135c`, observed HEAD
`1abe686fac8746a233f4691b13dfa5b398073c18`, head_ref refs/heads/master,
original receipt SHA256
`13a199ba3723283c5bfd72ce175fb7e950b8501fae2e02c1992ee8d4f8d51dae`.
Evidence outcome verified_applied, replay_permitted=false. This live case is
no-op reconciliation, not recovery from an actual interrupted merge. Outer
temporary probe records were removed on successful test exit.

This is reconciliation evidence, not full automatic recovery or scheduler wiring.
Actual power-loss recovery and live interrupted-apply reconciliation remain open.

### Synchronization guard evidence

Operation-state gate: synchronization now requires a standalone in-repository
`.git` directory and rejects external Git directories/gitfiles. It refuses
index/HEAD locks, merge/autostash/cherry-pick/revert markers, rebase directories,
sequencer and bisect state, including symlink and other nonmissing path types.
It never removes these markers. The gate runs before synchronization, again
after transfer and after merge. This supports the migrated standalone clones;
linked worktrees require a separate explicit adapter. Sync tests now total 27.
Expanded live smoke passed with these checks and the earlier fsync/attachment
fixes: content update, ignored collision refusal with local bytes preserved,
and unfinished MERGE_HEAD refusal with marker retained. Original role HEADs
unchanged and owned VMs stopped. The 27 sync unit tests also passed on dedicated
Linux (0.023 seconds). Windows sandbox test set: 76 passed in the preceding run.

Live probe root suffix `sync-probe-99afffa1e32d4139aff44bf3354496a0`, operation
`00af004e78764865b003811a64f3f9f1`; target advanced from
`f9a4856fdaf47058ef1691a486d0eb5e8b96c894` to
`1ccf281f211dd19597e10798d05b3fc14616b067`, recorded detached `head_ref=HEAD`
and exact probe guest_root. Bundle 674 bytes, SHA256
`96be1c30264e5e865fe581e469a7295ebe280485a62d2a1ac468e0457819bede`.
This executes the new guards on their successful path; injected branch-switch
and fsync-failure behavior remains unit-tested, not a real power-loss test.
Probe repositories/markers remain isolated and inactive; temporary outer probe
journals were removed on successful test exit. No automatic recovery or model
admission was enabled. Fable latest verdict remains not_run.

Follow-up hardening: fsync the fresh journal directory's parent before any VM
lease, and bind/recheck guest_root plus symbolic HEAD attachment before and
after applying. Same-commit branch switching must not update a different branch.
All 71 sandbox tests passed, including 22 synchronization tests. The final two
identity tests first exposed a missing post-merge guest_root comparison; it was
fixed and the full sandbox test set rerun. No automated recovery is enabled:
migration epoch binding, active Git-operation checks and recovery reconciliation
remain outstanding. Windows directory fsync remains unsupported by the helper;
production controller execution is intended for dedicated Linux.

Expanded live smoke passed real `content.txt` replacement and an ignored
`protected.txt` collision: merge refused, prior HEAD and both file contents
preserved, collision journal left at applying. Original role HEADs unchanged;
VM leases stopped. Successful content-update operation
`d57cfd10476e425cac61bedce85a85f9` advanced probe HEAD
`fe836abe308c30850385ac1cdb677588c00abf9b` to
`1f79c1be9fb6cc5703ed65b2bd0697995e03214d`; bundle 674 bytes, SHA256
`498087a1f58e44bd4b4d3fa32b6fb96aab24bb52e9eb0522fa0f31643a48c136`.
The live process had loaded the pre-hardening sync module before the concurrent
parent-fsync/identity edits. Those edits currently have unit coverage only;
do not describe this live run as verification of the new identity checks.
No actual power interruption, automated recovery, model execution or production
cutover was performed. Temporary outer probe receipts were removed on successful
test exit; probe guest repos remain as non-production artifacts.

`sandbox_sync.synchronize_fast_forward` imports a specified baseline using the
VM-only transfer adapter and advances a clean target only when its exact
expected HEAD is an ancestor. A fresh private outer journal records prepared,
transferred, applying and complete phases. Complete is written only after the
target lease has stopped successfully. Dirty or stale targets and divergence
are refused; no stash, reset, rollback, retry or legacy host Git is used.
Hooks and autostash are disabled for merge, and `--no-overwrite-ignore` prevents
silent replacement of ignored files (https://git-scm.com/docs/git-merge).

This is the clean fast-forward branch of production synchronization, not a
replacement for divergent merge, rejected-candidate archival, checkpoint
reconciliation, or full scheduler admission. Interrupted journals require
inspection; automatic recovery is not yet implemented. Callers must provide a
trusted private journal parent and hold the runtime lock throughout.

Trusted tests: all 66 `test_sandbox_*.py` tests passed, including 17 sync tests
covering VM-stop failures that must retain an incomplete journal phase.

Live `sandbox_sync_smoke.py` passed in fresh nested guest probe repositories:
`b440b7f77ac4af5309997401f6397c801785a7ae` advanced to
`25974094a7ee587e5bf915de23c1412c4dbb73fb`, transfer operation
`629bbc622f8640d7b036e456be613ccf`, bundle SHA256
`671ed75b3aa1339328b770384d6f283170ca404d6087945b64ba82645bcb4027`
(430 bytes). Final journal phase complete, original storage/coordinator HEADs
unchanged, owned VMs stopped. This used an empty commit: real file-content
updates, ignored-file collisions and interrupted-write recovery still need live
coverage. The smoke's outer temporary journals were cleaned up on exit; guest
probe repos and transfer refs remain. This is not production fleet activation.

### Unreferenced candidate transfer hardening — 2026-09-17

`transfer_commit` now creates a unique, create-only
`refs/fleet-transfers/<operation-id>` recovery ref before bundling. The bundle
contains that candidate and its history, rather than unrelated `--all` refs.
The exact advertised ref/commit is checked before target admission. Target fetch
uses the advertised ref without changing HEAD or writing FETCH_HEAD. Recovery
refs and bundle artifacts are retained, including on failure; no automatic
cleanup/retry is attempted. This closes the omission of candidates existing in
the object database but not reachable from a branch. The 16 MiB bound remains.

Trusted driver tests: all 49 `test_sandbox_*.py` tests passed, including nine
transfer tests. These fake-transport tests do not prove production admission,
authentication, ten-VM capacity or external audit acceptance.

Live dedicated-VM probe also passed: synthetic unreferenced commit
`4eaf21760f82e9060ebd0b594427a56e0126d5f4` transferred storage -> coordinator,
operation `1bb2fee7b58e43dcbe1ea298bf2690c0`. Bundle: 568575 bytes, SHA256
`b1287f8d9b96e8e04513b0adfb76a3893c3dceec41b4feedd9875902f7bdefca`.
Source HEAD remained `e7271a6eaca0204c77925ed6e5723412a1c4477e`; target HEAD
remained `5f676710e5b2fdadbcb3a3fc421c98ddd1e0af93`. A subsequent source lease
confirmed the retained recovery ref points to the synthetic commit. Both owned
VMs stopped on lease exit. No model/project-code execution or production cutover.
