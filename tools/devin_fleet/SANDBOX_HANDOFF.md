# Per-role Docker Sandboxes migration

## Authorized direction and current state — 2026-09-17

The user approved one persistent sandbox per role and delegated implementation details. This supersedes the VirtualBox/Ubuntu installation proposal. The full objective is not achieved. One mountless Linux sandbox now exists and has passed initial network and persistence checks; no Devin model or production fleet has been started.

Completed on the host:

- Confirmed Windows Hypervisor Platform `Win32_OptionalFeature.InstallState = 1` (enabled); no optional feature was changed and no host reboot occurred.
- Downloaded Docker's per-user `DockerSandboxes.msi` from release `v0.43.0` at `https://github.com/docker/sbx-releases/releases/tag/v0.43.0`.
- Checked SHA-256 against the release asset digest: `947cf45b1f96200807222aa17e980a54ff1695c80be7320da39cb7975e6c0dfa`.
- Authenticode signature valid; signer Docker Inc.
- Installed with `/qn /norestart`; MSI exit code 0. This did not install VirtualBox or replace the existing Docker sandbox v0.12.0 plugin.
- Installed executable: `C:\Users\main\AppData\Local\DockerSandboxes\bin\sbx.exe`.
- Verified `sbx version`: `v0.43.0 79805a6e3c6667520dc2da4f6bdeddae9b700969`.
- Local `create devin --help` confirms mountless creation and explicit resource/skills flags.

Authentication history (resolved by user login on 2026-09-17):

- `sbx ls`, `sbx policy ls`, and `sbx mcp ls` return `Not authenticated to Docker`.
- Two `sbx login` device-flow attempts reached browser/device confirmation, then each exited with code 1: `oauth2: access_denied — Global rate limit exceeded` from the authentication provider. Both attempts are terminal, not active authentication waits. A subsequent `sbx ls --json` still returned `Not authenticated to Docker`. Do not reuse either device code or repeatedly issue new codes.
- Authentication status must be checked live before continuing. Do not assume a previously started login process is still running. If it expires, start a fresh login; do not reuse an old code.
- Next authentication action requires the user's participation: retry browser login after the provider restriction clears, or use Docker's documented PAT login (`sbx login --username <docker-id> --password-stdin`) with a token having at least Read scope. The user should enter credentials only in a trusted local terminal, not this chat, command-line arguments, saved scripts, or repository files. Do not extract existing Docker credentials as a workaround. This alternative has not been executed or tested against the current provider restriction and is not guaranteed to succeed. Reference: https://docs.docker.com/ai/sandboxes/workflows/automation/
- No raw Docker/Devin credential files were copied. No model invocation, cloud sandbox, sandbox deletion, policy reset, or host autostart registration was performed.

Current verified gate after user login:

- Authentication now passes; `sbx ls --json` returns an empty sandbox list. The failed device-flow attempts above are historical, not the current blocker. No new login is needed on Windows.
- With no existing sandboxes or registered MCP servers, initialized global `deny-all` policy. No policy reset or allow-all was used.
- Attempted mountless creation: `sbx create --name e-base-machine --cpus 2 --memory 4g --skills off --deny-network '**' devin`. It failed during image preparation with HTTP 500. No sandbox was created or model invoked.
- The daemon log identifies an internal self-connection failure to its Windows `sandboxd/docker.sock`, not an authentication rejection or evidence that the outbound policy needs widening. The official Devin image tag exists.
- Local diagnostics report 13 passes and zero failures, including authentication and virtualization; these diagnostics do not establish successful image pull or VM operation.
- The symptom matches the still-open Windows issue https://github.com/docker/sbx-releases/issues/157. A reporter describes success under WSL2, but this workaround is not locally validated. Do not reset state, delete sockets, restart Docker Desktop, or reboot speculatively.
- Read-only WSL inventory: `docker-desktop` running; `Ubuntu` and `AIAnime-CoDeF-22.04` stopped; all version 2. No existing distro was started or modified. A dedicated WSL environment would be an additional installation decision, not permission to modify the other projects' distros. KVM availability remains unverified.

The legacy Windows fleet must remain stopped throughout migration. Do not run `fleet.ps1 Resume`: its tests still execute on the host. Existing repositories, dirty edits, receipts, and session IDs remain the source to preserve.

## First sandbox acceptance sequence

### Dedicated WSL bootstrap — 2026-09-17

The user approved adding a dedicated WSL environment. Created `EBase-Sandboxes` (WSL2) at `C:\Users\main\AppData\Local\EBaseSandboxes`. Existing `Ubuntu`, `AIAnime-CoDeF-22.04`, and Docker Desktop were not modified or stopped. No Windows reboot or global WSL shutdown was performed.

- Standard and web-download installers produced no progress and were stopped by exact owned process identity before registration. Imported the official Ubuntu 26.04.1 WSL image instead. Its URL and SHA256 came from Microsoft's `https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json`.
- Image: `https://releases.ubuntu.com/26.04.1/ubuntu-26.04.1-wsl-amd64.wsl`; verified SHA256 `48d56724b5c8e60f24893e83e73bbb58c60b3ca22fba3da977075420acd54104`.
- Created non-sudo user `fleet`, member of `kvm`; deployed adjacent `wsl-sandbox.conf` to `/etc/wsl.conf`. Terminated only the new distro to apply settings. Actual mount inspection shows no Windows drive mounts; `/mnt/c` and `/mnt/f` are leftover empty mountpoint directories. WSL's read-only driver mount remains. Windows interop is disabled.
- As `fleet`, opening `/dev/kvm` returned KVM API version 12 and `KVM_CREATE_VM` succeeded. This is prerequisite evidence, not a completed Sandbox microVM acceptance test.
- Installed official `DockerSandboxes-linux-amd64-ubuntu2604.deb` v0.43.0. Verified SHA256 `89e683e0b7c61df0ad149914b7fa938da9f0ca1e97f42e1340b5cf08d2a110c4`; installed 34 packages including required dependencies, without recommended packages. `sbx version` matches native Windows v0.43.0.
- New Linux authentication is required. The first `wsl -d EBase-Sandboxes -u fleet --cd /home/fleet --exec sbx login` produced a device code but then exited with code 1: `oauth2: access_denied — Global rate limit exceeded`. It is no longer waiting; its code must not be reused. Do not automatically loop login attempts. Retry interactively after the provider restriction clears. Do not persist device codes or copy Windows credentials.
- Windows-side deny-all policy does NOT establish Linux-side policy. After Linux login, inspect Linux `sbx ls --json`, `sbx policy ls`, and `sbx mcp ls`, then initialize deny-all only if uninitialized and empty, before the first create. No Linux Sandbox or Devin model has been started.
- Existing global `.wslconfig` limits all WSL to 16GB RAM and 8GB swap. It also emits an unknown `wsl2.autoMemoryReclaim` key warning. The file was not changed. Ten simultaneous 4GiB sandboxes cannot be assumed to fit; measure one first and obtain approval before changing global resources.
- A dedicated distro is administrative separation, not the generated-code isolation boundary. All model-directed code/tests must remain inside the inner mountless Sandboxes.

Resume commands must name `EBase-Sandboxes`, user `fleet`, and a Linux working directory explicitly. Never use the default WSL distro or legacy Windows fleet Resume as a substitute. Bootstrap files remain in the dedicated temporary download folder; no existing data was deleted.

1. Resolve the native Windows internal socket failure or obtain approval for a dedicated WSL installation. Windows authentication and initial policy/MCP inspection are complete. Do not reset global policy or disturb unrelated environments.
2. Create only `e-base-machine`, with 2 vCPU / 4 GiB, shared skills off, and explicit deny-network; omit ALL workspace arguments so no host directory is mounted. The first native Windows attempt failed as recorded above; no guest acceptance checks have run.
3. Before any agent execution, verify actual mounts, network/host reachability, and host-side MCP exposure. The default built-in agent launch is dangerous mode: do not use the default launch as the fleet policy. A guest `exec` launch must explicitly select Normal, fixed scopes, and `swe-2-high`; verify these in actual process arguments/export.
4. Restrict outbound traffic to required Devin authentication/model endpoints. Kits and inherited global rules can add permissions; an added allow rule is not an exclusive allowlist. Do not invent endpoint names or assume NAT is a network policy. MCP is a separate host boundary and must be checked independently.
5. Stage a reviewed, credential-free copy of the machine lane, preserving committed and dirty work with a manifest. Do not copy the whole workspace, `.git/config`, hooks, `.devin`, private materials, or raw old authentication. Old session IDs need a supported resume probe; retain historical reports outside active run scanning if new session IDs are necessary.
6. Execute source tests only inside isolation, with no host Python fallback. Keep untrusted guest reports separate from host-owned verified receipts. Prefer a network-disabled/authentication-free test sandbox so generated tests cannot use the agent's authenticated proxy.
7. Test checkpoint recovery and filesystem persistence after stop/start. STOP and timeout must stop and verify the owned sandbox, not merely kill the host `sbx exec` client. Test remaining guest descendants and an actual restart before enabling long-running operation.
8. Run one bounded SWE-2 turn after the free-tier/model check, verify ownership and exports, then expand gradually toward the ten role identities. Do not claim ten-role migration from a single-sandbox smoke test.

## Remaining engineering

### Ten role environments provisioned — 2026-09-17

All ten named role Sandboxes now exist in dedicated WSL. The additional nine
were created sequentially with 2 CPUs, 4GiB, no workspace argument, skills off
and explicit deny-network `**`, and each was stopped before creating the next.
`.ai/sandbox-registry.json` pins the observed IDs; production remains disabled.
Policy evaluation for `example.com:443` returned explicit deny for every role.
This does not replace live network/mount/recovery checks for each new sandbox.
All ten were verified stopped after provisioning. No model or generated source
execution occurred. Windows/global WSL memory limits were not changed; ten
simultaneous 4GiB VMs are still not admitted under the current 16GB WSL limit.

Read-only source inventory found uncommitted changes in applications (5 paths),
stdlib (4 paths), and devtools (12 paths). Do not use HEAD-only migration for
these roles. Original state hash remains unchanged. Only machine source/history
has been staged so far; provisioning nine environments is not their data migration.

### Actual guest Devin CLI/authentication preflight — 2026-09-17

The Docker login succeeded earlier, but machine's Devin launcher is currently
unauthenticated. Calling `devin --version` triggered the image wrapper's manual
login flow even before processing --version. No code was entered; EOF ended it,
then the VM was stopped. Do not reuse that expired login URL or treat it as an
active login session. No credential files were read/copied and policy unchanged.

Read-only inspection of `/home/agent/.local/bin/devin` identified the image
wrapper and its underlying `devin-cli`. Static underlying CLI version/help
commands (not auth/model commands) worked: version 3000.6.2, build ce8ebcc1;
all required config/model/export/prompt/resume flags are documented. Help now
describes auto, accept-edits, smart and dangerous. Both `--permission-mode normal
version` and `--permission-mode auto version` exited 0. This proves only parser/
version compatibility, NOT the effective permission behavior of a model session;
do not automatically change the fixed mode or claim policy acceptance.

Official Docker documentation describes separate first-run Devin sign-in and
proxy-managed reuse for future Sandboxes:
https://docs.docker.com/ai/sandboxes/agents/devin/
The wrapper validates auth and substitutes proxy-managed credentials before
launching the underlying CLI. Do not bypass that wrapper for model operation or
copy the Windows credential store. A user-driven Devin login and tightly scoped
network/auth readiness still need to be arranged. The default sbx run command
remains dangerous; do not use it for authentication setup.

Evidence: `.ai/sandbox-devin-cli-preflight-20260917.json`. No model calls or
credential changes were made, and machine was stopped after every inspection.

### Remaining dirty source/history imports — 2026-09-17

Applications (5 paths), stdlib (4), and devtools (12) now also have staged
source/history in their registered VMs. All ten role repositories are present.
This supersedes the earlier remaining-source-copy counts below, not their
production-operation limitations.

`import_dirty_guest.py` is a one-shot trusted helper executed only inside each
fresh, quiescent destination VM. It verifies artifact and individual file hashes,
rejects unexpected/link/traversal archive members, checks real parent directories,
clones without inherited hooks/config, and overlays only explicit raw file bytes.
Exact unstaged/untracked status, empty staged diff, tree identity and full fsck
passed for all three. Original HEAD/status and all 21 source hashes were checked
again afterward and unchanged. All ten VMs verified stopped; legacy STOP and
state hash remain unchanged. Evidence manifests/receipt are in
`.ai/sandbox-migration-dirty-{manifest,receipt}-20260917.json`.

Initial strict reparse rejection stopped before artifact creation: source files
carry OneDrive Cloud Files tags, not links. Read-only tag inspection allowed only
0x9000[0-F]01A and rejected LinkType/other tags. Microsoft reference:
https://learn.microsoft.com/ja-jp/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4
The stdlib start emitted a Docker Hub refresh-lock warning; import verification
and stop still succeeded without retry or credential changes.

An independent read-only candidate inventory found all 20 state candidates and
39 role/SHA receipt references reachable from owner lane refs. Seven earlier
bundles were directly checked for their corresponding 16 candidates; remaining
applications/stdlib candidates were reachable from their branch tips before the
new --all exports. No special rescue refs were needed in that inventory.

No ignored metadata, original branch attachment, or old Devin session was
activated. No model/project code ran, and no production cutover occurred.
Fable latest report remains not_run, not external acceptance. Next work must
connect production controller/recovery to guest repositories and resolve the
remaining isolation/admission gates, not call the legacy host Resume command.

### Six additional clean source/history imports — 2026-09-17

Copied coordinator, toolchain, kernel, storage, services and assurance into their
registered role VMs, one at a time. Host exports used Git builtins with hooks and
fsmonitor disabled; no model/project code ran on the host or guest. Guest imports
used empty templates and local bundles, without source Git config or hooks.
Each import verified UUID/stopped-state admission, original HEAD and clean status,
bundle SHA256 after mountless streaming, guest HEAD/tree/clean status, and full
Git fsck. Each VM was stopped and the complete listing verified stopped before
proceeding; final command exited 0 with all ten stopped.

Evidence: `.ai/sandbox-migration-clean-20260917.json` and role-specific local
bundle directories. Original fleet STOP remains present and state hash unchanged.
The first export check warned about an inaccessible default global-ignore file;
the pre-transfer source check used explicit empty core.excludesFile and passed.
Seven roles now have staged source/history, not seven resumed sessions. Remaining
applications/stdlib/devtools have 21 modified/untracked paths total; preserve raw
bytes and unstaged/untracked status, not HEAD-only copies. Ignored metadata and
possibly unreachable historical candidates still need a separate inventory.
No production cutover, model calls, generated-code tests, or external audit ran.

### Actual machine source/history import — 2026-09-17

Created `.ai/sandbox-migration-machine-20260917/` with a complete reachable-ref
Git bundle and separate HEAD archive. Source status was clean (148 tracked files);
repository hooks/fsmonitor and automatic maintenance were disabled for native
metadata/export commands. No source code was executed on the host. Initial
archive invocation had a PowerShell argument-format error; the successful retry
did not overwrite an existing archive. Both artifact SHA256 values matched after
mountless streaming transfer into the guest.

Restored inside `e-base-machine` at `/home/agent/workspace/machine`, using an empty
Git template and no copied local Git config/hooks. Guest HEAD and tree matched
`472781a6c824ec8201d8e23ab06a1e08322be045` and
`1da242ca3584f8f54bb9300e38d8b953e08ac86b`. Guest status was clean, tracked file
count was 148, earlier candidate `78efb0d016597012e471d240e84a7dfac21177bd` was
present, and `git fsck --full` exited successfully. Local receipt JSON records
hashes and scope. All originals remain intact. This is a staged source/history
copy only: ignored `.fleet` metadata, legacy session resume, config migration,
test execution and production cutover are NOT complete. Sandbox stopped afterward.

Production replacement map: `SANDBOX_INTEGRATION.md`. The controller now requires
a recorded sandbox UUID and rejects same-name replacements before execution or
stop. Thirteen contract tests and the real smoke test passed in dedicated Linux
after this change. This is not production runner integration; all host Git and
recovery paths in the map must also move behind the isolation boundary.

### Dedicated WSL recovery and controller work — 2026-09-17

- Previous goal turn classified as progress: real mountless VM creation and network/persistence evidence, not just a plan.
- Added `sbx-headless.sh`, a trusted controller entry point that refuses other users/distros and clears DISPLAY, WAYLAND_DISPLAY, PULSE_SERVER, SSH agent, and session D-Bus variables. Copied to `/home/fleet/sbx-headless.sh`. This reduces ambient desktop integration; it is not yet a proven clipboard-write prohibition. Docker documents text-write separately from image-read: https://docs.docker.com/ai/sandboxes/security/isolation/ . The outer WSL currently has no xclip/wl-copy/xsel executables; absence alone is not a permanent enforcement mechanism.
- Stopped the dedicated sbx daemon, terminated only `EBase-Sandboxes`, then restarted through the headless entry point. Linux authentication remained valid, SSH forwarding remained false, the same sandbox UUID remained, and the marker SHA256 remained identical after guest start. Final sandbox state was `stopped`. Existing other WSL environments were not stopped. This proves clean dedicated-WSL restart recovery, not sudden power-loss or a physical PC reboot.
- Added a separate controller implementation and tests; it is not yet wired into production `fleet.py`. A live smoke helper invokes only a marker hash and bounded sleep, never model-generated code. Keep production fleet STOP in place until full adapter/data migration and all host-boundary gates are verified.
- Validation completed: `test_sandbox_control.py` passed all 11 tests on Windows (fake transport) and dedicated Linux (fake transport). In `/home/fleet/controller-validation`, `python3 sandbox_control_smoke.py` also passed against actual `e-base-machine`: persistent marker hash, 2-second deadline on a 120-second sleep, verified stopped state, and rejection of a later exec without spawning a client. Independent final listing reported the same sandbox stopped. This is real transport evidence, not full ten-role integration or clipboard boundary acceptance.
- Integration contract: trusted per-sandbox STOP path (never reuse fleet-wide STOP, since explicit resume removes the per-sandbox marker), outer fleet-wide admission barrier and cross-process GlobalLock, and new exclusive log paths. Timeout cleanup adds bounded stop/verification time. Route both model execution and all generated-code tests through isolation; wrapping only Devin is insufficient.

### First Linux sandbox evidence — 2026-09-17, after successful user login

- Linux login verified with an initially empty `sbx ls --json`; Linux MCP registry empty. Initialized previously uninitialized Linux global policy to `deny-all`.
- Created `e-base-machine`, ID `40e32a36-d565-4853-a841-fa3bea9ac648`, using 2 CPUs, 4GiB, `--skills off --deny-network '**'`, and no workspace arguments. Official Devin image pull succeeded. This resolves the native Windows creation blocker via the dedicated Linux environment, not via a Windows fix.
- Guest kernel `Linux 7.0.12 x86_64`, user `agent`. Actual mountinfo contained container/runtime mounts and read-only hosts/resolver binds, no host workspace/Windows drive/shared skills mounts. Checked `/mnt/c`, `/mnt/f`, `/host`, `/host_mnt`, `/run/sandbox/source`, `.agents/skills`, and `.devin/skills`: absent. Guest has its own running dockerd/containerd; generated code is not intended to execute in the outer WSL distro.
- `example.com:443` policy explicitly denied; actual proxied curl returned 403. Direct/no-proxy `1.1.1.1:80` returned empty reply. Correlated policy log records both denies, respectively forward and transparent proxy. A timeout alone was not used as proof. Template startup package-update attempts were also denied; no allowed hosts appeared in that log.
- Disabled `ssh.agentForwardingEnabled` and explicitly kept `clipboard.imagePaste=false`; restarted only the dedicated Linux sandbox daemon. Guest process inspection after restart no longer showed the SSH socat bridge. Clipboard text-write capability remains an unresolved host-boundary question; image-read disabled is NOT proof that all clipboard access is disabled. Do not read or overwrite the user's clipboard for a test without authorization.
- Transferred adjacent non-secret `sandbox-persistence-probe.txt` using a tar stream into the guest, without enabling a mount. Initial UNC Copy-Item failed with a Windows authentication error; no credential workaround was attempted. SHA256 before and after restart: `e9764d24a789db2ddaba822680c310b3ce0c9917b5eaf5b77c63ca9cf1043d7d`.
- Created a `sleep 731` test child. `sbx exec -d` unexpectedly kept its client waiting. The first stop was followed by an already-queued inspection exec that restarted the sandbox: this is a controller race to prevent, not a successful stable stop. Drained that client before retesting. Subsequent stop/list reported `stopped`; restart retained the marker and did not retain `sleep 731`; final stop/list again reported `stopped`. Controller must fence new/queued execs before stop and verify final state.
- Final state: only `e-base-machine`, stopped; no model call, source migration, credential copy, fleet Resume, public push, or merge. Host VM process disappearance and actual PC reboot recovery still need stronger evidence; this test covered sandbox stop/start plus dedicated daemon restart only.
- Fable latest-report read and independent agent review were performed; neither is an external acceptance verdict for this configuration.

Earlier authentication/creation gates above describe historical bootstrap steps. They are superseded by this evidence; do not ask for Docker login again without a current authentication failure.

The current fleet launcher is not yet a sandbox adapter. It still launches Devin and tests as local processes. Linux process admission tests are preparation only. Add explicit role/sandbox mapping, guest path/config generation, safe input/output transfer, isolated test and integration gates, and sandbox-aware stop/recovery before switching production operation.

No host folders, clipboard, SSH agent, or private credentials should be shared. Retain per-role histories and backups; never use `rm`, `reset`, or `prune` as a restart operation. Public push, PR approval, merge, release, and paid model fallback remain outside automatic fleet authority.

Fable latest-report was inspected during installation work; it is the earlier preflight-only `not_run` result, not external acceptance of the new sandbox configuration.

## Primary references verified

- https://docs.docker.com/ai/sandboxes/install/
- https://docs.docker.com/ai/sandboxes/agents/devin/
- https://docs.docker.com/ai/sandboxes/usage/
- https://docs.docker.com/ai/sandboxes/architecture/
- https://github.com/docker/sbx-releases
