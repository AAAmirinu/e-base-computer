# Validation isolation: incomplete, do not execute generated source

## Devin authentication rechecked through permanent isolation — 2026-09-19

Ran existing trusted sandbox_auth_probe for machine inside the permanent managed
daemon mount/PID namespaces, dropping to fleet before controller execution. The
probe owned the shared lock (no nested outer lock), started only the registered
machine VM, executed only isolated Python/auth-status, and verified lease stop.
Evidence: `/home/fleet/controller-validation/auth-status-87u5t3wh/status.log`.
Classification was not_logged_in, CLI returncode0, raw_output_suppressed=true,
model_executed=false. CLI zero exit is therefore NOT login acceptance.

Postchecks through installed managed entry independently verified all eleven
VMs stopped and ten-role controller maintenance_only/resume_available=false.
Manager was explicitly stopped: final inactive/MainPID0. No model, device login,
credential copying or network-policy change occurred. This confirms the auth-only
VM lifecycle now works under the permanent service, not merely mocked status.
User interaction for Devin-specific login is required before model admission;
Docker login is separate. Other roles were not rechecked during this operation.
Fable latest remains historical not_run.

## Read-only turn-fence inspection available — 2026-09-19

`sandbox_driver.py ... inspect-turns` reads only the selected private controller
root and trusted registration. It does not construct/enter a runtime, query sbx,
start a VM, clear STOP or modify/create a fence directory. Each fixed role is
reported absent, unresolved, invalid, or identity_mismatch; read bounded regular
files include their SHA256. Duplicate/malformed JSON, wrong field types/schema,
oversize content, noncanonical identities and unsafe file objects cannot appear
as a resolved operation. Recorded run_directory is never followed or returned;
untrusted strings are not echoed. The report always says resume_available=false
and runtime_state_observed=false. It is evidence inventory, not replay approval.

Live inspection of `/home/fleet/controller-validation/managed-maintenance`
reported all ten absent without starting the manager or VMs. That root has not
run production jobs; this says nothing about legacy Windows work or other roots.
Deployed driver/helper and tested in dedicated Linux: inspection+driver30 passed,
including FIFO, links and ownership cases. Windows whole sandbox suite354:
334 passed,20 platform skips. Windows lstat/fstat legacy ctime differs after a
file rewrite, so Windows inspection compares device/inode/size/mtime; production
Linux additionally compares ctime before/during/after reading. Fable not_run.

## Interrupted model-turn replay fenced — 2026-09-19

`sandbox_turn_fence.py` now creates an exclusive, durable per-role reservation
under the trusted controller root before admission or VM/model work. It reuses
the turn receipt operation ID and survives failures, nonzero model exit and
awaiting_validation. A fresh run_directory, sequence, session, migration epoch
or new runtime instance cannot bypass an existing reservation for that role.
Existing empty/malformed/symlink entries are not read or overwritten. Private
directory checks and file+directory fsync precede admission; incomplete writes
remain blocking. Other roles use independent reservations.

Production runtime/turn entry requires controller_root to match the trusted
registration. This prevents merely selecting another runtime root; editing the
trusted registration itself remains an operator-level action and must not be
used to bypass recovery. Current deployed registry stays production_enabled=false.
No automatic release or human-approved resolution is implemented yet: a fence
does not prove stopped descendants, validation acceptance or candidate commit.
Do not delete it as a retry shortcut. It is a replay barrier, not completed job
recovery or an automatic-resume mechanism.

Deployed only trusted controller modules/tests to dedicated WSL. Linux mocked
turn/fence/runtime suite42 passed; Windows sandbox suite338:321 passed,17 platform
skips. Tests include process-instance replacement, fresh output directories,
unchanged malformed files, operation binding, competing reservations, symlinks
and persistence failures. No real model/VM was executed and no live model crash
was induced. Fable latest remains historical not_run.

## Lock bootstrap and dedicated-distro restart verified — 2026-09-19

Installed root-owned0644 `/etc/tmpfiles.d/e-base-fleet.conf`: lowercase f creates
the same fleet-owned0600 lock at `/tmp/e-base-devin-fleet-global.lock` if absent;
x excludes it from periodic age cleanup. No removal/truncation/purge is used.
All callers retain the same lock path. The service now Requires/After
systemd-tmpfiles-setup.service. Unit verification passed. Previous unit backup:
`/home/fleet/controller-validation/lock-setup-backup-XGqMt6bS`.
New unit SHA2561a16c24ba8a7c95cb51433ba6c46855aa605dd01812cf73b2ddb12b8875111cc;
tmpfiles SHA256a5cf539d7d61c95657e62ca92b8b8dcd098d789eb8c47a00a4160f57e700aeff.
Both are pinned in managed_cutover.HASHES and deployed.

`lock_bootstrap_probe.py` refuses unexpected owner/mode/type/link count, then
runs --create on this config only. Live first creation dev121/inode18; repeated
creation while locked preserved the inode and a second descriptor was excluded;
reacquisition after close succeeded. It does not simulate reboot acceptance.

Separately terminated ONLY EBase-Sandboxes after verifying inactive manager and
no sbx/VM processes, then started that distro again. PID1 starttime changed from
14622960 to14626172. Before the probe reran, tmpfiles-setup reported success and
the lock existed fleet:fleet0600 inode2. Probe reported created_if_absent=false,
same-inode exclusion/reacquisition passed. No other distro or PC was restarted.
Managed service remained inactive/static/MainPID0 on boot. Explicit confined
manager startup then successfully returned all eleven registered VMs stopped
and controller maintenance_only/resume_available=false. The manager was stopped
afterward and final inactive/MainPID0/static confirmed. Legacy Windows STOP
remained present. No model/VM launch, network allowance or credential operation.

New lock-probe tests10 passed; Windows discovery325:308 passed,17 platform skips.
This proves lock bootstrap and status-only manual recovery across one dedicated
distro restart, NOT PC reboot acceptance, automatic model resume, interrupted
job recovery or ten-session production capacity. Fable remains historical not_run.

## Permanent managed namespace live status verified — 2026-09-19

Deployed guarded wrapper and LinuxTransport after backing up originals in
`/home/fleet/controller-validation/caller-backup-h2elYVmg` (root-private).
Initial cutover receipt `managed-cutover-w5yt148n/receipt.json` remains failed,
inspection_required, managed_stop_verified=true, ordinary_restore_attempted=false.
It is NOT rewritten as success. The old daemon PID121525 stopped; no VM started.

Two real portability issues were found and fixed:

- Type=exec with PrivatePIDs makes the daemon namespace-local PID1 (observed
  outer634, NSpid634/1). Accept local PID1 only with all existing identity,
  namespace, service and cgroup checks. Outer process checks still require >1.
- `/run/user/1000/bus` can disappear after distro reinitialization, causing
  systemd NAMESPACE/226 startup failure. The unit and validators now require
  hiding the stable parent `/run/user`, not just that volatile socket.

Previous installed service files were backed up under
`/home/fleet/controller-validation/service-backup-DxsY38AK` (root-private).
Current installed hashes: guard32f1e2a00df4c686ba3b4c27a2ca92035e3bb9ba74af27bff79bbe49d6d6a788,
entrybc85d5b41c81538fd85a1870881f375f8dd3213d9525453a0e7be953b0e0ba48,
unit3de1ad9c03e2ed3d6e4b0de010fa3cbb56743428cf4533f0353b112b84e5e2a4.
Following explicit maintenance service start, root managed entry succeeded for
both raw eleven-VM inventory and controller status (ten roles stopped,
maintenance_only,resume_available=false). Actual daemon cgroup was exactly
`0::/system.slice/e-base-sandboxd.service`. Outer fleet wrapper refused with
PermissionError on /proc/1/ns/mnt before sbx launch; MainPID634 remained active.
Service remains static, not enabled. Legacy STOP remains present.
After the bounded WSL helper finished (exit0), the managed service was explicitly
stopped: final ActiveState=inactive,MainPID=0,UnitFileState=static. No ordinary
daemon was restored. Successful status observations above are test-time evidence,
not a claim that the manager remains running.

This was a manually inspected recovery and live status check, not a complete
successful rerun of the cutover script. `/tmp` lock disappeared during dedicated
distro reinitialization and was recreated only after no manager was active.
Persistent lock bootstrap/recovery still needs implementation. A bounded300s
WSL sleep kept the distro alive during debugging; it is not a deployment or
autostart solution. Do not claim reboot-resume acceptance. Existing ordinary
maintenance smoke scripts are incompatible with the now-guarded clients and
must not restore the ordinary daemon. Use the installed managed status entry.

Windows suite315:298 passed,17 platform-dependent skips. Linux mocked guard
and cutover tests24 passed before the final portability fixes; final315 suite
includes readiness regressions and valid localPID1. Fable remains not_run.

## Legacy-client namespace guard prepared — 2026-09-19

Added `managed_cli_guard.py` and connected it in the repository copies of both
LinuxTransport launch paths and sbx-headless.sh. The guard requires fleet in the
dedicated distro, active effective service isolation, exact daemon identity/UID,
exact unified service cgroup, matching mount/PID namespaces, and stable daemon
generation/service settings across verification. Missing/stale state refuses;
there is no ordinary-daemon recovery fallback. A post-check daemon death can
still cause sbx fallback inside the checked namespaces; this is not a hostile
fleet-user boundary or a proof of zero implicit process launches.

Installed only `/usr/local/libexec/e-base-managed-cli-guard.py` root:root0644,
SHA256 `844e4456602b1205799f4f2b119cd02f5d4153a11f7f2614d5e3e004d8a1f8e0`.
Live fleet invocation refused the inactive service, exit1, without changing
ordinary daemon PID121525. Permanent service remained inactive/MainPID0.
The deployed wrapper and transport are NOT updated yet. Cutover now requires
their exact migrated hashes before any daemon operation, so the current mixed
deployment cannot be cut over accidentally using the new cutover script.
The migration-only old-daemon ls/stop path uses direct sbx after identity checks;
normal client paths use the guard. No new VM/model execution or network change.

Nine guard tests passed, including weakened isolation, similar cgroup names,
generation changes, and both transport paths refusing before sbx Popen.
The additional caller-hash test rejects old bytes, symlinks, wrong owner and
group/world-writable files. Windows discovery ran312:295 passed,17
platform-dependent skips. Actual cgroup
shape and systemctl access from inside the permanent namespaces still require
live validation before acceptance; the current live test only proves refusal.
Fable latest remains historical `not_run`.

## Maintenance cutover implementation prepared, not executed — 2026-09-19

`managed_cutover.py` implements an explicit, locked, maintenance-only transition
from a verified ordinary daemon to the installed managed service. It requires
production_enabled=false, eleven distinct stopped identities matching the
registry, root-owned fixed-hash installed artifacts, and an inactive loaded unit
with no drop-ins or pending reload. The old daemon identity is checked before
the first ordinary CLI call and again before stop. Durable receipts precede
stop/start; an old PID still present prevents a second daemon from starting.
The installed entry is loaded from the same verified bytes and checks managed
inventory and controller status. Failures never restore an ordinary daemon:
only the managed service whose start was attempted is stopped, with uncertainty
retained in the receipt. Receipt-write failure does not replace the original
exception. No VM/model launch, network-policy change or automatic enable exists.

DO NOT deploy/run this transition yet. `LinuxTransport` still invokes sbx
directly and `sbx-headless.sh` does not reject an outer-namespace caller after
cutover. Both must be migrated/guarded first, along with maintenance scripts
using them. Otherwise an old caller may implicitly start an ordinary daemon
because the managed daemon's PID file is namespace-local. A documentation-only
warning is not an enforced migration gate. The cutover implementation is not
yet an approved operational entry and has not changed the live manager.

Live read-only check of the installed unit: inactive, MainPID=0, static,
FragmentPath=/etc/systemd/system/e-base-sandboxd.service, DropInPaths empty,
NeedDaemonReload=no. Fable latest remains historical `not_run`.
Fourteen new mocked cutover tests passed, including failed old stop, uncertain
new start, inventory mismatch, failed cleanup and failed receipt persistence.
Windows sandbox test discovery ran302:285 passed,17 platform-dependent skips.
These tests do not prove live cutover or reboot recovery.

## Permanent files installed, service inactive — 2026-09-19

Installed in EBase-Sandboxes under the fleet global lock, without replacing
existing targets: `/etc/systemd/system/e-base-sandboxd.service` and
`/usr/local/libexec/e-base-managed-status.py`. Both are root:root mode0644;
their parent directories are root:root mode0755. Installed SHA256 values match
the reviewed source and staged copies:

- entry: `d24be1e385f08174dbad9f46d99625c0778fd712e7bcc97769eddf3d04b45dc5`
- unit: `ef1065f78ce4b60b0d50a9325b880fc15b6baac649c6a5a1a5952ed6baf64cf0`

systemd-analyze verify passed; daemon-reload loaded the definition only.
Service remains inactive, MainPID=0, UnitFileState=static. Reverse dependency
listing contained only this service. No enable/start or startup hook was added.
Invoking `/usr/bin/python3 -I /usr/local/libexec/e-base-managed-status.py
--controller-status` refused with the expected required-isolation error and
exit1. Existing maintenance daemon PID121525 was unchanged; subsequent inventory
confirmed all ten role VMs and the validation VM stopped. Legacy Windows STOP
remained present. Six managed-status unit tests passed.

This supersedes earlier historical statements that the files were not installed;
it does not establish production cutover, restart recovery or full isolation.
Model execution remains disabled. Fable latest report is historical `not_run`,
not external audit acceptance.

## Existing maintenance controller through managed namespace — 2026-09-19

`managed_sandbox_status.py --controller-status` adds a second fixed status-only
action. After entering pinned service namespaces it drops to fleet and invokes
the existing sandbox_driver with fixed registry/root/status arguments, using
Python -E -s. No user-selected script, root path, command, model or resume flag
is accepted. Strict result parsing rejects duplicate keys, incorrect keys/roles,
nonboolean status flags, non-maintenance mode, resume availability or any role
not stopped. Outer timeout45s allows inner30s plus cleanup5s; it is not full
controller-crash/descendant recovery coverage.

Live test succeeded at
`/home/fleet/controller-validation/daemon-boundary-3p_9ifur/receipt.json`:
both raw managed status and existing-controller status passed inside actual
constrained daemon MainPID121405. Controller reported all ten roles stopped,
maintenance_only and resume_available=false. Separate inventory proved all
eleven stopped. Original maintenance daemon was restored afterward.

The newly created private fleet-owned `/home/fleet/controller-validation/managed-maintenance`
is a status-only root. Its stop_requested=false does NOT describe or clear the
legacy Windows STOP or any other root. No production cutover/epoch migration
or permanent service activation occurred. Six entry/result guard unit tests
passed. Fable latest remains `not_run`.

## Managed status entry prepared and tested — 2026-09-19

Prepared `e-base-sandboxd.service` with the successfully tested private PID and
display-path boundary, Restart=no and KillMode=control-group. systemd-analyze
verify passed. The unit is only a staged artifact: NOT installed/enabled.
`managed_sandbox_status.py` provides a root-only dedicated-distro status entry,
with no CLI command/unit overrides and no start/stop behavior. It validates
effective service restrictions, fleet UID, exact daemon executable/argv and
starttime; pins mount/PID namespace descriptors, rejects shared outer namespaces,
and passes only those descriptors to a fixed namespace-entered fleet status
client with a minimal environment. It checks daemon identity again afterward.
Timeout/interruption kills/reaps its owned client process group. This is not a
production controller or a general privileged command bridge.

Three guard tests passed. Live constrained status matched all 11 stopped UUIDs
in `/home/fleet/controller-validation/daemon-boundary-83sjzsmz/receipt.json`,
managed_status_verified=true, followed by original-mode restoration. A separate
call with the permanent service absent refused with the expected inactive
reason and left the existing daemon PID unchanged; no autostart was requested.
Race/failure unit coverage and fixed controller-entry integration remain work
before permanent cutover. No model executed; Fable latest remains `not_run`.

## Validation VM lifecycle under constrained daemon — 2026-09-19

`daemon_boundary_smoke.py --validation-lifecycle` passed a real validation-VM
start, `/usr/bin/true`, stop and exact all-11 stopped inventory under the
constrained daemon. Registry-1.docker.io:443 policy checks before and after both
returned explicit deny rule da8e1350-568e-4c6a-9e86-e5ea47d2b67c. This is that
destination's policy evidence, not a fresh exhaustive network-policy proof.
No project source, model or clipboard operation ran, and policy was unchanged.

Successful receipt:
`/home/fleet/controller-validation/daemon-boundary-j5naqiyw/receipt.json`.
Phase validation_lifecycle_verified, daemon MainPID120764, guest command and
VM stop true, original maintenance mode restored, all eleven stopped true.
An earlier attempt (`daemon-boundary-tdwd6fsm`) stopped before VM launch because
the helper treated policy-check exit1 (valid deny JSON) as command failure;
it restored successfully. Only policy checks now explicitly accept exit1.

Client calls now own and reap their process groups on timeout/interruption.
Unverified VM cleanup suppresses ordinary-daemon restoration after stopping
the temporary service. Three mocked Linux command-boundary tests cover explicit
deny exit, timeout group termination/reaping and already-exited-group handling;
they do not cover every lifecycle failure. Full boundary/physical reboot and
permanent service cutover remain incomplete. Fable latest is `not_run`.

## Actual daemon isolation compatibility — 2026-09-19

`daemon_boundary_smoke.py` performs an explicit root-only dedicated-WSL
maintenance experiment under the existing fleet lock. It verifies exactly the
registered 11 stopped VMs and original daemon PID command, stops only that
daemon, starts a transient foreground service as fleet with PrivatePIDs=yes and
the tested display/interop path restrictions, and restores the original daemon
mode afterward. No VM or model is launched. Existing PID/state/config files are
not deleted. The root script opens the existing lock read-only for flock; an
initial O_CREAT attempt was rejected by protected_regular before any change.

The daemon writes a namespace-local PID file. Tests therefore verify that value
against MainPID's NSpid and invoke the client using nsenter into the service's
mount/PID namespace, retaining fleet identity. Ordinary outer client autostart
is deliberately NOT tested/admitted. Service cleanup uses systemctl rather
than namespace-ambiguous sbx daemon stop, verifies MainPID zero, then restores.

Two live inventory compatibility runs passed, retaining all 11 UUIDs/stopped
states and restoring original maintenance mode:
`/home/fleet/controller-validation/daemon-boundary-3j40zqod/receipt.json` and
`/home/fleet/controller-validation/daemon-boundary-ij8e9jsv/receipt.json`.
Second run's daemon MainPID120361 had actual namespace display probes:
Wayland/X11/interop EACCES, user bus root-owned mode000/write_access=false, no
conventional abstract display socket names. Clipboard contents were untouched.

This demonstrates actual daemon inventory compatibility and clean repeated
service replacement, not guest execution, daemon-crash recovery, physical
reboot, or production acceptance. The original unrestricted maintenance daemon
was intentionally restored; persistent cutover still requires all controller
clients to enter the constrained namespace and never silently autostart outside
it. Next bounded test is one trusted validation-VM lifecycle plus deny-policy
checks in that namespace. No permanent service or model admission was enabled.
Fable latest remains `not_run`.

## Alternate display route and PID isolation — 2026-09-19

Extended `display_boundary_probe.py --outer-pid 454` to inspect only metadata
through the currently verified dedicated daemon's `/proc/454/root`. With the
previous InaccessiblePaths service settings, both alternate Wayland/X11 paths
were visible mode0777 and write_access=true despite direct-path EACCES. Adding
ProtectProc=ptraceable did NOT close this route on the current system. Neither
configuration is accepted as a complete host display boundary.

A third transient service with PrivatePIDs=yes plus the same InaccessiblePaths
returned ENOENT for both outer-process paths, EACCES for direct display/interop
paths and the root-owned mode000 bus placeholder. It exited successfully in
57ms, using a separate mount namespace. This demonstrates removal of the tested
proc-root route, not all IPC routes. No socket connection, clipboard read/write,
daemon restart, VM start or persistent service installation occurred.

Next cutover gate: actual sbx daemon/client compatibility with a private PID
namespace, especially process identity files and implicit daemon autostart.
All controllers must use the service-owned daemon; silently starting an
unconfined replacement is unacceptable. Preserve current configuration/state
and require stopped inventory before any daemon replacement. Full acceptance
still requires remaining alternate/helper/abstract endpoint checks and restart
evidence. Fable latest remains preflight `not_run`.

## Transient display-boundary experiment — 2026-09-19

Static symbol/string inspection of the installed `/usr/bin/sbx` found
`sbx-clipboard-write`, the `/_sbx/clipboard-write` gateway route, and host
functions `writeClipboardOnHost`, `writeClipboardWithCommands` and
`clipboardCommands`. This locates a proxy-mediated write path; it does not prove
all host backends or policy behavior. No request to this endpoint was sent.

A transient `e-base-display-boundary-probe.service` was run in EBase-Sandboxes
as fleet (uid1000), with InaccessiblePaths for `/mnt/wslg`, `/tmp/.X11-unix`,
`/run/WSL` and `/run/user/1000/bus`. `display_boundary_probe.py` performed only
stat/access/proc metadata reads, never a socket connection. All first three
paths returned EACCES; the user bus path was replaced by a root-owned mode000
socket with write_access=false. No conventional abstract X11/Wayland socket
names were listed. Two runs exited successfully (60ms and34ms); transient units
were collected. No existing daemon, VM, clipboard, global WSL or policy change.

This proves a scoped service can hide these paths, NOT a complete clipboard
boundary. Existing daemon PID454 still uses its original unrestricted mount
namespace. Before any cutover, check alternate/helper/abstract/proc-root routes,
service compatibility and startup ownership; prevent implicit sbx autostart
from bypassing the service. No full-boundary acceptance or model execution.
Fable latest remains `not_run`.

## Clipboard boundary inspection — 2026-09-19

Read-only inspection established an actual remaining host integration path,
not merely missing proof. Docker's current isolation documentation explicitly
allows sandbox text writes to the host clipboard and treats image reads as a
separate opt-in: https://docs.docker.com/ai/sandboxes/security/isolation/ .
Current dedicated `sbx settings list --all --json` exposes clipboard.imagePaste
only (false); no text-copy disable setting was found. The speculative
clipboard.textCopy key is not defined. No clipboard contents were accessed.

Dedicated outer daemon PID 454 was `/usr/bin/sbx daemon start`, in init.scope,
sharing mount namespace mnt:[4026532395] with the dedicated WSL shell.
Its environment contains XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS (names
only inspected; values suppressed), despite DISPLAY/WAYLAND_DISPLAY being absent.
Both `/proc/454/root/mnt/wslg/runtime-dir/wayland-0` and
`/proc/454/root/tmp/.X11-unix/X0` are visible world-accessible Unix sockets.
Therefore headless client environment cleanup alone is not an enforced
no-clipboard-sharing boundary. Existing imagePaste=false, disabled Windows
interop/automount and absent xclip/xsel/wl-copy remain useful but insufficient.

Daemon help confirms foreground `sbx daemon start` and explicit `daemon stop`.
Next engineering investigation should test a dedicated daemon service with
restricted display/socket access, including alternative/abstract socket routes,
before any live cutover. Merely hiding pathnames is not claimed sufficient.
No daemon restart, host clipboard operation, WSLg setting change or network
policy change occurred during this inspection. Never disable GUI support for
all WSL distributions as a workaround. Fable latest remains `not_run`.

## Completed failure resolved as rejection — 2026-09-19

`validation_failure_resolution.py` records only `rejected_awaiting_repair` for
a completed exit-1 failed test with verified cleanup and bound feedback delivery.
The explicit maintenance command reloads the snapshot/capture against trusted
registration, verifies original journal/stdout/feedback/delivery and all-VM stop,
then exclusively persists a canonical resolution. Original failure evidence is
untouched. Resolution binds all four evidence hashes plus distinct outer
dispatch and guest-operation identities; acceptance, replay and model-start
authorization remain false. Partial/conflicting files and simultaneous synthetic
closure are refused. Historical gate checks do not require repaired source to
remain equal to the old snapshot; original evidence must still match exactly.

Live resolution for `dispatch-fbce94e501874b05abbc4ce04f645e43` is stored in its
`failure-resolution.json`, SHA256
`eec527aaef8edc475962c90ea5eb2922a92314b6d25b07312ab8e7e1d5713b19`.
The pending gate now returns an empty unresolved list and all 11 VMs are stopped.
This permits NEW validation dispatches, not replay or acceptance of the rejected
candidate. Model production remains disabled and the actual test failure is not
fixed. Devin login still requires user participation as separately reported.

Windows sandbox suite: 279 tests, 265 passed, 14 Linux-only skips. Dedicated
Linux resolution/gate/store suite: all 21 passed. Fable latest remains `not_run`.

## Live readiness: Devin authentication absent — 2026-09-19

`sandbox_auth_probe.py --role ROLE` checks the underlying installed CLI's
`auth status` without invoking the Docker login wrapper or a model. Raw output
is captured only in guest memory and reduced to `not_logged_in`, `unclassified`
or `timeout`; unknown output never grants admission. It uses a registered role
lease and exports only classified status. This is maintenance, not production.

Live checks returned `not_logged_in` for both machine and stdlib (CLI status
itself exits 0 even when unauthenticated). Evidence directories:
`/home/fleet/controller-validation/auth-status-jvlc0ls5` (machine) and
`/home/fleet/controller-validation/auth-status-00g3x8tj` (stdlib).
Both checks ended with all 11 VMs stopped. No authentication was initiated,
no credentials copied, no network policy changed and no model executed.

Readiness review identifies the shortest path to one bounded repair turn:
user-assisted Devin login in stdlib; live Free SWE-2 catalog/required network
route verification; Normal policy and remaining clipboard boundary checks;
explicit new production-root/epoch admission; invoke existing model phase once,
then stop at awaiting_validation and validate in the separate credential-free
VM. Ten-way capacity and automated integration remain overall requirements but
are not prerequisites for that first bounded repair. A concrete production
admission provider and execution CLI are still missing. Current real stdlib
failure also needs a nonaccepting resolution before another validation dispatch.
Fable latest verdict remains `not_run`.

## Auxiliary model-input integrity checks — 2026-09-19

Staging now returns the digest map for every auxiliary input, including failed
validation feedback, coordinator patches, context and role descriptions. The new
sandbox model-turn path requires this map, persists it in the prepared turn
receipt and forwards it to the execution boundary. The boundary validates a
copied bounded map (62 entries maximum, normalized same-parent plain filenames,
reserved-path exclusions and strict digests), checks regular-file fingerprints
before launch and after execution, and records approved hashes in its operation
receipt. Missing/changed files prevent launch or reject the result and stop the
controller. Old callers may omit the optional map; no auxiliary-file assurance
is claimed for them. These checks detect persistent changes, not transient
edit-and-restore attacks, and are not an immutable filesystem boundary.

Dedicated Linux: 45 related model/turn/feedback tests passed without live model
calls. Windows guest tests: 57 passed before adding one staging-map assertion;
sandbox suite: 273 tests, 259 passed, 14 skipped. Production remains disabled;
failure hold remains. Fable latest is still preflight `not_run`.

## Failed feedback connected to turn preparation — 2026-09-19

`prepare_guest_turn` and `run_guest_model_phase` now accept optional feedback
bytes plus an independently verified controller digest, together or neither.
`verify_turn_feedback` checks bounded canonical JSON/hash, nonaccepting flags,
role/VM, existing byte-identical regular guest feedback and a fresh whole-source
manifest. Missing or stale delivery cannot be silently installed during turn
preparation. Verified bytes enter the fresh staged inputs as
`validation-feedback.json`; a fixed prompt identifies the digest, treats all
embedded content as untrusted evidence, forbids permission expansion and project
test execution in the model VM. The turn receipt records the feedback digest.
No automatic feedback selection, hold resolution or production enablement was
added. The trusted caller must rebuild provenance before supplying the digest.
Model-time immutability of extra input files is NOT yet checked independently;
the existing execution checks bind config/prompt only.

Dedicated Linux: 35 feedback/turn tests passed with model execution mocked.
Windows sandbox suite before two additional turn tests: 271 tests, 257 passed,
14 skipped; guest preparation 5 passed. Wider Windows suite initially reported
four errors from two process-stop cases plus cleanup under restricted execution;
the identified test processes had exited. Re-running the seven process-control
tests with required OS permissions passed. This is not a fully green rerun of
that entire wider suite. No model was called; production stays disabled, the
real stdlib failure remains unresolved, and Fable external audit is `not_run`.

## Failed-feedback staging in owner VM — 2026-09-19

`sandbox_feedback_delivery.py` is an explicit maintenance-only command. It
rebuilds stored feedback under the fleet lock, checks all 11 VMs stopped, opens
only the owning role lease, recaptures the whole source manifest (including
modes), and refuses a mismatch. It writes only a missing digest-addressed
`.fleet/validation-feedback-<SHA>.json`; identical files are read, not rewritten;
conflicting, linked or special destinations are refused. It checks readback and
checkpoint stability. The outer delivery receipt is finalized only after lease
shutdown and all-VM stopped verification. Existing delivery transactions require
inspection, not automatic replay. This maintenance path intentionally does not
release the normal validation hold or enable production/model execution.

Live stdlib delivery succeeded. Full recapture matched manifest
`2c4008d2837858e8e733eb943335a564da65c8a4723becc3456cd84b438c73eb`.
Feedback SHA `b1018ce94bdf34ed9a2903a97f43f4fb5837e11bb7d1623381882076f7d85d8a`
was read back from the digest-named `.fleet` file in VM
`53309df1-bbf5-4aa7-9614-b6159d607d6c`. Durable outer receipt:
`/home/fleet/controller-validation/dispatch-fbce94e501874b05abbc4ce04f645e43/feedback-delivery.json`.
Receipt phase `delivered` means staged in the role filesystem, NOT consumed by
Devin. `source_vm_stopped=true`, `model_executed=false`, `hold_cleared=false`,
`validation_passed=false`. Current source freshness was checked at this delivery,
not promised for future runs. No original source files were modified.

Six delivery unit tests passed in dedicated Linux; Windows full controller suite
268 tests: 254 passed, 14 Linux-only skips. Next work remains explicit delivery
recovery, model-turn input association and non-accepting failure resolution.
Fable latest report remains `not_run`.

## Durable failed-validation feedback — 2026-09-19

`validation_feedback_store.py` now reloads snapshot, capture, registry, journal
and stdout under the fleet lock, checks stopped inventory, and creates
`failure-feedback.json` exclusively in the private dispatch directory. File
and parent-directory fsync precede acknowledgement. Exact-byte repeats fsync
again without rewriting; partial/conflicting records are preserved and refused.
Symlink, hardlink and FIFO targets are refused. This is controller storage only,
not delivery, current-source verification, acceptance or failure-hold closure.

Live stdlib feedback saved at
`/home/fleet/controller-validation/dispatch-fbce94e501874b05abbc4ce04f645e43/failure-feedback.json`,
SHA256 `b1018ce94bdf34ed9a2903a97f43f4fb5837e11bb7d1623381882076f7d85d8a`.
Windows regression suite: 262 tests, 248 passed, 14 Linux-specific skips.
Dedicated Linux feedback/store suite: all 16 passed, including partial write,
file/directory sync failure, repeated save, FIFO/symlink/hardlink cases. Initial
Linux test invocation lacked a shared fixture module; after explicit staging,
the full invocation passed. No project source or model executed. Physical
power-loss persistence remains untested. Fable latest remains `not_run`.

## Failed-validation feedback builder — 2026-09-19

`validation_failure_feedback.py` builds a non-authorizing in-memory feedback
record from bounded journal/stdout bytes and separately validated capture
evidence. It binds source/image/operation/validation VM, checks stdout SHA and
embedded summary equality, requires stopped cleanup and a completed exit-1 test
invocation, and verifies materialization against capture counts. Duplicate and
nonfinite JSON, boolean integer claims, missing or swapped provenance, timeout,
success, and incomplete cleanup are rejected. Test output remains explicitly
untrusted data; the full test-output hash is retained but not reverified from
the summary tail. No hold is cleared and no replay or acceptance is authorized.

Eight new unit tests pass. Full Windows controller suite: 254 tests, 243 passed,
11 Linux-only skips. Read-only execution against the actual stdlib dispatch
`dispatch-fbce94e501874b05abbc4ce04f645e43`, with freshly loaded snapshot/capture
and live inventory under the fleet lock, returned bound feedback for operation
`1dc665d5195544dd8c04842d9d26465b` and 260 reported tests. All 11 VMs were stopped.
This is builder validation, not a new project test run. Feedback has NOT been
persisted or delivered to the role, current role-source freshness is unverified,
and the original failure hold remains. Next: durable delivery with freshness
checks and a separate non-accepting failed-result resolution transaction.
Fable MCP latest report remains preflight `not_run`, not external acceptance.

## Dirty role candidate capture + validation — 2026-09-19

`sandbox_snapshot_smoke.py --role ROLE` now records controller-owned capture
provenance after role-VM lease exit: exact role/VM, base, changed paths/content
fingerprints, manifest digest, path and counts. No model or source code executes
in that role VM. Optional dispatch `--capture-receipt` binds this protected
receipt to the selected snapshot and trusted role registry. It checks fingerprint
agreement/deletions and counts, and embeds the receipt plus raw SHA in the outer
journal. This is historical candidate provenance, not a model turn/epoch token.

Live stdlib capture retained four untracked changes: docs/fleet/stdlib/earray_v0.md,
examples/stdlib/vector_dot.epu, guest/stdlib/earray.epu, tests/test_stdlib_earray.py.
Role VM `53309df1-bbf5-4aa7-9614-b6159d607d6c`, unchanged base
`c25b2d33ef3823fd78a0117f20f6bd1d50e86260`. Snapshot: 152 files, 1,145,273 bytes,
148 blobs, SHA256 `2c4008d2837858e8e733eb943335a564da65c8a4723becc3456cd84b438c73eb`.
Capture record at
`/home/fleet/controller-validation/snapshot-evidence-e4417f75b0804a8cbcbcb38c897c3ebb/capture.json`.

Validation dispatch `dispatch-fbce94e501874b05abbc4ce04f645e43` finished with
test exit 1, was retained as inspection_required, and verified VM stopped.
Guest operation `1dc665d5195544dd8c04842d9d26465b`, container
`415bb4bb27b1a763d44e90a173f4458dfbfae23c334b5541c35ef960a22f2363`.
260 tests: 258 passed, 1 failure, 1 expected failure, no skips. Failure:
`tests/test_stdlib_earray.py:188`, test_guest_app_example expected 51 steps but
observed 52. No assumption yet whether implementation or expectation is wrong.
Full output retained in guest receipt; outer summary SHA256 of full test output
`a503aa0275e9f1e5a4be75bc6b437a902c83561d46f9f041deba4145b9f579fb`.

No original role change was edited/staged/committed and no model was called.
The admission fence intentionally holds subsequent runs until this failed-test
outcome is handled with a non-accepting resolution. Synthetic crash closure
cannot clear this real-source result. Eight loader/provenance tests passed.

## Explicit candidate snapshot input — 2026-09-19

Dispatch now requires `--snapshot ABSOLUTE_DIRECTORY --manifest-sha256 SHA256`.
The input must remain under the protected dedicated controller tree, with
unlinked paths and root/fleet-owned non-group/other-writable ancestors. Loader
checks private directories, bounded single-link regular files, exact blob
inventory and canonical manifest/content hashes before sending any bytes.
The explicit digest flows through outer journal, guest CLI, container receiver
and result binding. No generated source is imported on the outer controller.
Six input-loader tests passed, including rejecting a wrong manifest hash before
reading blobs. This is an operator dispatch interface, not scheduler admission.

Live explicit-input run on the previously validated 156-file snapshot completed:
`/home/fleet/controller-validation/dispatch-2bfae0d1d26b406d8e74ab21a71b9ac2`.
VM stopped and result retained. Read-only recovery inspection remains a separate
fixed-baseline helper; arbitrary candidate integration/checkpointing is not yet
connected. Path checks rely on the protected controller tree, not an adversarial
concurrent filesystem writer; no general host-directory import is supported.

## Explicit synthetic-probe closure — 2026-09-19

`validation_probe_closure.py DIRECTORY --journal-sha256 HASH` now closes only
an identified trusted_driver_sigkill probe with source_executed=false. Under
the fleet lock it binds the original journal/crash hashes, inspects the exact
owned container/image/operation label and no-restart/stopped state, stops and
rechecks the exact VM, and rechecks that both original files are unchanged.
It creates closure.json exclusively with fsync; no old phase is rewritten.
Closure grants neither validation acceptance nor replay. Real interrupted test
runs cannot use this synthetic-probe-only closure route.

Live closure added for `dispatch-8bbbd7e7447844cfa450390c63cd66f0`, preserving
journal SHA256 `d0d005a11c2c3b219b10bba061411aa6957072324cdd1030a87cd58da04dfc11`.
Crash evidence SHA256 `5b3807e1da1dcefa448e7a10de7c05f40e9f48fd3fc76a63ce04aa3f28490421`.
The pending gate recognizes only fully bound closure evidence and a currently
stopped VM. Modified, wrong-image, wrong-container, replay/acceptance claims
or float signal codes are refused. Eight closure tests pass.

A separate NEW fixed-source dispatch then completed successfully at
`/home/fleet/controller-validation/dispatch-5feed6ac5d76453092ea8dded96d7513`.
It did not resume the old interrupted operation. VM stop was verified. Controller
regression: 238 tests, 227 passed, 11 Linux-only skipped on Windows. Full fleet,
arbitrary-candidate recovery, outer-controller crash and physical reboot remain
unverified; external Fable verdict remains not_run.

## Unresolved-dispatch admission fence — 2026-09-19

`validation_pending_gate.py` now scans bounded dispatch history under the held
fleet lock, before any new directory or guest execution. Missing, malformed,
unfinished or inconsistent records block admission. A complete phase is not
sufficient: the output hash, embedded summary, VM identity and current stopped
state are rechecked. Linked/special/multiple-hardlink evidence is rejected.
The gate neither edits nor clears records. Seven gate unit tests passed.

Live dispatcher attempt correctly refused the retained crash-test journal
`dispatch-8bbbd7e7447844cfa450390c63cd66f0` with incomplete_dispatch_phase,
exit 1 before sandbox exec. Subsequent sandbox inventory showed all eleven VMs
still stopped. This is a deliberate safety hold, not a failed model/test run.

Next required implementation: explicit evidence-bound closure of an inspected
interrupted operation, preserving the original journal and proving cleanup.
No blanket ignore, deletion, phase rewrite or automatic replay is implemented.

## Controlled helper interruption + VM restart — 2026-09-19

`validation_crash_probe.py` created a checked, network-none idle container,
then its own trusted guest helper deliberately SIGKILLed itself. No model or
project code ran. The outer controller held the fleet lock, verified exact VM
identity/all VMs stopped before admission, and retained a running-phase journal.

Live operation `8bbbd7e7447844cfa450390c63cd66f0`, container
`2b804d0cb11fbc6c41cab2dfd7ece279648a90d4750787147bbb2f119f67f50c`.
Guest exit 137; container remained running after helper crash. Controlled stop
of e-base-validation followed by a read-only inspect restart showed container
not running and restart policy `no`. Final exact VM stopped-state check passed.
No other VM/distro or physical PC was rebooted.

Evidence directory:
`/home/fleet/controller-validation/dispatch-8bbbd7e7447844cfa450390c63cd66f0`.
Original journal remained byte-identical, SHA256
`d0d005a11c2c3b219b10bba061411aa6957072324cdd1030a87cd58da04dfc11`.
Recovery inspection returned inspection_required/incomplete_dispatch_phase,
with replay_permitted=false and validation_passed=false. Separate crash evidence
was saved without rewriting the unfinished original journal.

This establishes this guest-helper crash path and controlled dedicated-VM
restart behavior only. It is not outer-controller death, physical power loss,
arbitrary test interruption or automatic recovery acceptance. Final-stop failure
still propagates as an error; a missing evidence file must never be success.

## Read-only dispatch recovery inspection — 2026-09-19

`validation_dispatch_recovery.py DIRECTORY` is a dedicated-Linux fixed-probe
inspection command. It takes the fleet lock and reads bounded regular no-follow
journal/log files, checks exact validation VM identity/current stopped state,
snapshot/base/image binding, raw output hash and agreement with the embedded
summary. Only complete successful nonempty test-command evidence is recognized.
Incomplete phases, stale/running VM identity and malformed/inconsistent evidence
require inspection. No receipt mutation, model/test execution, start, stop or
automatic retry occurs. Replay and production acceptance always remain false.

Eight synthetic recovery tests passed. The CLI also requires caller ownership,
private directory permissions and no group/other-writable evidence files.
Live read-only CLI against
`/home/fleet/controller-validation/dispatch-e41ed400b2724c8ba86487cdb1d99e56`
returned verified_completed_dispatch for operation
`d1c0c91b020e4b71b9f7766a3b66145f`, reporting 273 tests. Original journal SHA256:
`d9f08456af96beb58774f41fe628f9960fb2183a16c6bbde559f35a4a8055eb6`.
This confirms evidence reinspection, not physical reboot/crash recovery. It
does not clear the known expected failure or admit continuous production work.

## Outer dispatch journal — 2026-09-19

`validation_snapshot_dispatch.py` now creates a private fresh outer directory,
journals prepared/running/result_received and completion/failure phases using
atomic fsync-backed writes, and retains stdout/stderr files. Each redirected log
is capped at 8 MiB by the child's RLIMIT_FSIZE; execution remains time-bounded.
VM-stop cleanup runs even when result parsing or journaling fails. Complete
requires exact VM identity and observed stopped state, not only a stop exit code.

`validation_dispatch_receipt.py` binds exactly one guest summary to the expected
snapshot, base commit, image, canonical operation/container IDs and receipt path.
It rejects incomplete cleanup and production acceptance claims. This parser is
an evidence binding check, NOT a standalone test acceptance or recovery gate.
Four pure parser tests passed. Review found no outer stop-skipping path.

Live fixed-snapshot run completed and was read back after VM shutdown:
`/home/fleet/controller-validation/dispatch-e41ed400b2724c8ba86487cdb1d99e56/dispatch.json`.
Guest operation `d1c0c91b020e4b71b9f7766a3b66145f`; stdout SHA256
`61e41d58e8f17f8390dbf146cb449040ee626f5aa3a813e194182bd7d0329805`.
273 tests in 4.891s: 272 passed, one expected failure, zero skips. Matching
snapshot/image identifiers and both container/VM stop evidence were retained.
`complete` here means the operator dispatch and cleanup finished, not full fleet
acceptance; validation_passed remains false. This does not yet test controller
crash, physical reboot, automatic recovery or arbitrary candidate dispatch.

## Python + Node validation — 2026-09-19

User approved Node image acquisition and subsequently authorized temporary
isolated-environment communications for dependencies needed during construction.
This supersedes historical per-image approval holds below. Keep acquisition
destinations narrow and restore denial afterward; do not apply to role-model
execution, paid fallbacks, external publication or unrelated environments.

Official node:22-bookworm-slim acquired under the same three-host scoped window,
then all-host denial restored and VM stopped. Node image digest:
`sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5`
(79,901,626 bytes). Networkless build using the pinned Python base and only
COPY of `/usr/local/bin/node` produced local image:
`sha256:1750198e508ceeabc96bb744de28bce36fe877ab0cd7f5a4a2eb0eff6d710f1f`.
No VM OS libraries, credential folders or agent entrypoints were copied.
Recipe: `validation_python_node.Dockerfile`; no RUN or package installation.

Node v22.23.2 runs in the checked non-root, network-none container. The same
156-file snapshot was tested again: operation
`3c9425edd21e4dc8b3b71ddce83e3a72`, container
`f4bfe01246e459db43a344aff6a579814ad1cd2dfd1ddadf9083b8e1ef2ae7c4`.
Receipt: `/tmp/validation-source-3c9425edd21e4dc8b3b71ddce83e3a72.json`
inside validation VM. Output SHA256:
`6da73904efbcf97822193a6f7603f6471915a1ce939779458b770d2e3cda540e`.

273 tests in 4.872s: **272 passed, zero skipped, one expected failure**:
`test_assurance_store_window.StaticRuntimeDivergenceTests.test_static_runtime_matches_normative_contract`.
This removes missing-Node coverage skips, not the known normative/static runtime
divergence. Exit 0 is unittest's expected-failure semantics, not 273 passes.
Container non-running and exact VM stopped state were verified. No role VM
was started and legacy STOP remains. Full production acceptance and continuous
Devin operation remain disabled; no candidate was committed or merged.

## Failure containment tests — 2026-09-18

While additional Node image authorization is pending, the source-smoke helper
now journals testing/tested/cleanup_pending and cleanup_failed phases and syncs
the receipt directory after replacement. A failed pre-cleanup journal write
still attempts Docker stop, never preserves a success claim. Selector setup
failure also kills/waits the owned Docker client. Outer VM shutdown remains
required: killing the client alone does not prove its daemon-side work stopped.

All 12 trusted synthetic failure tests passed in the existing validation VM:
normal/failing process exit, timeout, stdout-closed timeout, bounded output,
failed/timed-out stop, invalid/still-running inspect, interrupted testing,
zero-test/nonzero/timeout rejection, journal failure and selector setup failure.
No model/project source ran during these tests. VM stopped afterward; network
policy unchanged. This is not physical reboot or automatic recovery acceptance.

## Node runtime preparation — 2026-09-18

Read-only inspection of the existing shell VM runtime found `/usr/bin/node`,
version v22.22.1, SHA256
`d0efb6fcb9d023ba4e2b160ec2384dc28fe4f17732141ef47f676828fa960505`.
It is a distro-packaged dynamic executable using libnode.so.127 plus system
libc, ICU 78, OpenSSL, libstdc++ and other shared libraries. Copying that single
binary cannot provide the missing runtime in the Python image. No system
libraries, credentials or VM home files were copied into an image.

Prefer a compatible official Node image as a pinned build input instead of
transplanting the shell VM OS libraries. Additional image acquisition has not
been performed: request approval for the same temporary, validation-VM-only
Docker distribution allowance for this Node input. Network denial stayed in
place throughout the local inspection, and the VM was stopped afterward.

## Source execution milestone — 2026-09-18

Operator-authorized saved-source smoke now ran inside the checked network-none
container only. This supersedes earlier statements that no source has run;
production model-generated candidate validation is still not admitted.
The dedicated outer dispatcher holds the fleet lock, checks exact validation
VM UUID/all VMs stopped, checks registry denial, and verifies VM stopped after
the run. It transports inert manifest/blobs over stdin, without shared mounts.

Snapshot SHA256 `11ae09248ff91a77e069ff7eaf6921b9247d1a6cc63897399a78fbbc6782febc`,
base `e7271a6eaca0204c77925ed6e5723412a1c4477e`, 156 files. Receiver verifies the
fixed expected digest both outside and inside before fresh /work/source
materialization. The source executes only after the trusted inner boundary probe.

Final detailed run: operation `88f91ad7b0784c2d9669a3809913bc72`, container
`49e900f0be44c5d517db48ab9d870bfa6f04ac5fe0d5c43fc17d581857ec2881`.
Receipt/full bounded output retained in validation VM at
`/tmp/validation-source-88f91ad7b0784c2d9669a3809913bc72.json`.
Output SHA256 `d9048bdf4b5ad6d0149710da7feb35aafcfab046ad12ff2791d9e7346bcb752b`.
Unittest reported 273 tests in 4.538 seconds: 267 passed, 6 skipped, no failures.
All six skips explicitly require Node.js: static ASM/C parity and normative
runtime contract checks. Python-only image coverage is not full acceptance.

120-second and 1-MiB output bounds apply. Failure/timeout/zero reported tests
produce nonzero runner status; test summary is observational, not an independent
attestation against malicious tests. Container non-running and VM stopped were
verified. `validation_passed=false` remains intentional: no automatic candidate
commit/integration/PR or continuous scheduler activation follows this smoke.
Next: provide a pinned Node-capable validation image and run skipped parity
coverage, then integrate durable validation lifecycle and snapshot/result binding.

## Active boundary milestone — 2026-09-18

Trusted `validation_active_smoke.py` passed with restored network denial.
Final operation `cc482c79c7e14c16ae514ef6167dd710`, retained container
`257e0a2beb32223d51f090ac12cff5285d61cb7f61a2dc6a60a7f3aba8472bf1`.
Receipt retained in the validation VM:
`/tmp/validation-active-cc482c79c7e14c16ae514ef6167dd710.json`.

- A fresh world-readable outer VM /tmp canary was invisible from the container
  and unchanged afterward. This tests that canary, not every possible host path.
- Root write refused with EROFS (30); scratch write/read matched exactly.
- Direct TCP attempt to 192.0.2.1:443 failed ENETUNREACH (101); loopback:443
  refused (111). These specific failures supplement the no-external-route check.
- cgroup observations: memory.max=536870912, memory.swap.max=0, pids.max=64,
  cpu.max="100000 100000". No memory-exhaustion or fork-bomb stress was attempted.
- Detached child PID 19 matched outer PID 371 through NSpid. Outer PID/start-time
  identities 309/127 and 371/152 were both absent or replaced after container stop.
  Container inspect reported non-running; enclosing VM stop also succeeded.

No project source was executed. Canary, stopped container and receipts remain.
This operator probe still requires outer ownership/lock and VM shutdown on
failure. It is not a production cleanup/reboot-recovery controller; an incomplete
receipt or timeout must not authorize a new validation run. Physical reboot and
automatic recovery remain unverified. Fable external verdict remains not_run.

## Live milestone — 2026-09-18 (supersedes image-acquisition hold below)

User explicitly authorized temporary validation-VM-only registry access.
`validation_image_acquire.py` verified all VMs stopped, took the shared lock,
allowed only auth.docker.io:443, registry-1.docker.io:443 and
production.cloudfront.docker.com:443, and checked example.com remained denied.
Domains were selected from https://docs.docker.com/desktop/setup/allow-list/.
The bounded official python:3.12-slim pull succeeded (46,192,946 bytes).

Pinned local image and repository digest:
`sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea`.
The temporary allows were removed; all-host denial was restored, with rule
`3c875974-ac25-48cd-b5e1-e6ee013522fa`. Registry/auth/general-site denial checks
passed. Final policy listing contains no network allow. VM stopped afterward.
The one-shot acquisition helper embeds the old deny ID and is not reusable
without reviewing current policy and obtaining new authorization.

Live trusted container smoke then succeeded under restored network denial:
operation `a4fa50d9f74341789d446cde1dd47dbf`, container
`de919e052e78708d94f8fecf0b878c3c66444f51e14e1d9d8b77e38829d0402a`.
Pre-start inspect contract matched. Inner observations: UID/GID 65532,
only HOME/LANG/PATH environment keys, zero capability sets, NoNewPrivs=1,
Seccomp=2, loopback only, no IPv4 routes, only loopback IPv6 routes, no Unix
sockets, known credential/host paths absent, read-only root and private tmpfs.
`/work` was observed noexec as well. No project source was introduced/executed.
Container inspect reported not running after stop; VM stop also completed.
Stopped probe containers are retained; no removal/prune was performed.

Live compatibility fixes: Docker rejects `--pid private`, so use its default
private PID namespace and verify inspect rejects sharing. Local log driver
requires compression disabled with max-file=1; fixed and inspected accordingly.
10 specification tests and 9 boundary-probe tests passed after these changes.

This remains limited observation evidence, **not full isolation acceptance**.
Required next gates include VM-side canary inaccessibility, direct connection
failures, filesystem write denial, cgroup enforcement, descendant cleanup and
restart behavior, then source transport/test execution with digest binding.
The smoke is an operator-run probe, not a production lifecycle driver.

## Observed dedicated environment (2026-09-17)

The separate shell sandbox `e-base-validation` has UUID
`84a0fc99-4cbb-4383-a1df-4c22bbe0d2e6`, 2 CPUs and 4 GiB memory.
It is separate from the ten registered Devin role VMs; it is not an additional
model session. It was created without workspace, volume or port mappings,
with explicit deny-network `**`. Provisioning is not production admission.

Trusted presence probe found no Devin binary, Devin credential file, SSH home,
GitHub credential file, Windows drive mounts or sandbox source mount. However,
OPENAI_API_KEY, ANTHROPIC_API_KEY, GH_TOKEN and SSH_AUTH_SOCK variable names
were present. Values were neither read nor displayed. This is **not** proof of
a credential-free runtime. An example.com HTTP 403 proves that request was
refused, not that every network protocol or local credential proxy is isolated.

Inner `docker image ls --no-trunc` returned successfully with zero images.
No inner image was downloaded or built, and no project source was executed.
The sandbox was stopped after both metadata and trusted test probes.

Subsequent bounded acquisition attempt: `docker pull python:3.12-slim` inside
e-base-validation was rejected with HTTP 403 on the registry manifest HEAD
request to registry-1.docker.io. No policy was changed and no alternative
download route was attempted. The VM was stopped afterward. Image acquisition
now requires approval for a narrowly scoped temporary validation-VM registry
allowance; all ten role VM policies must remain unchanged. An approved attempt
must restore deny-only policy before any runtime probe or project execution,
and pin/record the returned immutable image digest. This failed pull does not
establish successful image installation or a runnable validation container.

## Receiver implemented; runtime still missing

`sandbox_snapshot_receiver.py` accepts canonical bounded JSON only when its
SHA-256 matches the trusted caller's expected digest. It verifies exact schema,
integer types, base and content hashes, sorted unique safe paths, file/ancestor
conflicts, Git file modes, complete blob membership and expanded size limits.
Source persistence now applies this admission check as well.

Linux-only materialization uses descriptor-relative no-follow traversal,
exclusive new regular files and a fresh private output directory. Content is
copied rather than hard-linked; mode and file/directory sync happen before
returning the receipt. Failed partial output is retained and cannot be reused.
The caller must protect the parent directory and its ancestors against other
writers. The receiver does not implement VM ownership, credential isolation,
container lifecycle, source execution or validation acceptance.

Trusted synthetic receiver tests: 18/18 passed inside e-base-validation.
Windows controller regression: 189 tests, 183 passed and 6 Linux-only skipped.
No model-generated source, emulator tests, commit or PR was run by these tests.
Fable latest report remains preflight `not_run`, not external audit acceptance.

## Required next boundaries

`sandbox_validation_container.py` now provides a pure create-command builder
and pre-start Docker inspect contract checker. It requires a local immutable
image ID, forbids implicit pulls, uses network none, non-root UID/GID, fixed
runc runtime, read-only root and bounded private tmpfs, drops capabilities,
disables healthchecks/restart, and bounds CPU/memory/PIDs/logs. Inspection rejects
unexpected mounts, devices, ambient credential environment names, namespace
sharing and network attachments. These helpers do not invoke Docker. Their
synthetic metadata tests are not live compatibility or isolation acceptance.
No lifecycle driver or actual validation container has been activated yet.

`validation_boundary_probe.py` adds a trusted in-container observation check:
UID/GID and groups, all capability sets, no-new-privileges, seccomp mode,
environment key allowlist (no values), interfaces and routes, Unix sockets,
known sensitive path presence, root read-only and private scratch mount flags,
plus an explicit expected Docker mount-target allowlist.
It reads bounded proc metadata and never reads credential contents or executes
source. Nine synthetic tests pass. It explicitly returns
`full_isolation_accepted=false`: cross-boundary canary tests, resource enforcement,
live Docker compatibility, transport integrity and descendant cleanup still
require separate evidence. No live validation container has run this probe.

1. Provision and pin a suitable non-agent runtime image using an explicitly
   bounded image acquisition path; do not loosen the role VM network policies.
2. Run a disposable inner container with no network, host/VM mounts or sockets,
   non-root identity, no added groups, all capabilities dropped,
   no-new-privileges, separate PID/IPC namespaces, bounded resources and logs,
   and a trusted environment allowlist/entrypoint. Disable image healthchecks.
3. Verify actual mounts, namespaces, capabilities, sockets, environment names,
   route absence, canary isolation and descendant termination before deploying
   project source. Flags alone are not acceptance.
4. Transfer verified manifest/blobs to that runtime, rehydrate there, execute
   tests, and bind results to the exact digest. Integrate lifecycle/STOP/reboot
   recovery under the shared fleet lock, including this eleventh VM.

Legacy STOP, production_enabled=false and verified capacity=1 remain unchanged.
Do not use the host-executing legacy Resume path to bypass these gates.
