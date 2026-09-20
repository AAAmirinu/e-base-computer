# Dedicated VM migration — preflight 2026-09-17

Historical VirtualBox proposal, superseded by the user's approved per-role Docker Sandboxes direction. Current installation and acceptance state is in `SANDBOX_HANDOFF.md`. The original preflight below is retained as historical evidence; its pending VirtualBox approval is no longer the next action.

Status: NOT provisioned, NOT migrated, NOT accepted. Windows fleet remains stopped.
The active objective is a working, verified dedicated VM, not merely this plan.

## Host evidence

- Windows 11 Home 10.0.26200; Intel Core i7-14700F; 28 logical CPUs; 96 GiB RAM.
- Free space observed: C: 1,419,284,914,176 bytes; D: 524,332,433,408; F: 146,853,748,736.
- HypervisorPresent=true and vmcompute running. CPU virtualization flags reported false while a hypervisor is active; do not infer that BIOS virtualization is disabled or alter BIOS from this result.
- No Hyper-V management commands, VBoxManage, vmrun, or qemu-system-x86_64 discovered on PATH. Registry query found no VirtualBox/VMware/QEMU installation. This is discovery evidence, not proof that no portable copy exists anywhere.
- Standard client Hyper-V is not supported on Windows Home. Do not use unofficial feature-enablement scripts or disable host security/WSL to work around this.

## Proposed host change requiring confirmation

Install the signed Oracle VirtualBox base package (no Extension Pack) and create a dedicated Linux VM outside OneDrive at `C:\VMs\e-base-devin`.
Initial proposed allocation: 8 vCPU, 24 GiB RAM, dynamically allocated 96 GiB virtual disk. Snapshots and installation media need additional host space; 96 GiB is not a total folder quota.
Use a supported Ubuntu Server LTS image verified against the publisher's checksums. Download exact current versions only after approval and signature/checksum inspection. No automatic host reboot.

Prefer the minimum installation feature set; no bridged-networking, host-only-networking, USB passthrough, or Python API support unless proven necessary and separately explained. The installer still changes host software/drivers. Installation failure or a required reboot is a stop-and-report condition, not permission to force a reboot.

## Isolation acceptance requirements

1. No shared host folders, host drive mounts, clipboard synchronization, drag/drop, USB passthrough, SSH-agent forwarding, or host credential directory copying.
2. No bridged networking. NAT alone is NOT a LAN/host access restriction. Enforce and test an outbound policy blocking host/LAN/private/link-local services while allowing only required model/authentication traffic. DNS and update exceptions must be explicit. Do not claim isolation based on configuration alone.
3. Dedicated non-admin runtime identity inside VM. Provisioning admin credentials must not be available to agents. Devin authentication happens inside the VM with user participation; do not print or export tokens.
4. Separate generated-test execution from model authentication and writable controller state: unprivileged network-disabled test identity/container, no authentication mount, limited writable paths, CPU/memory/process limits. VM containment alone does not stop generated tests from stealing VM-local Devin credentials when both use the same UID.
5. Root-owned systemd service/cgroup must clean up descendants on stop or controller crash. Preserve STOP semantics; explicit resumption only until reboot tests pass. Host startup registration is not yet approved/configured.
6. Keep Windows fleet stopped; Linux admission checks must detect existing CLI processes. Ten-role limit is account-wide in intent, but local process checks cannot detect another PC using the account.
7. Before continuous operation: validate boot, clean stop, parent crash, guest reboot, disk-pressure stop, credential isolation, blocked host/LAN access, and per-role permission holds. Then perform a bounded live round with fixed SWE-2 and free-tier verification, followed by integrated tests including Node cross-runtime checks.

## Saved research state that must be preserved

Observed stopped round 6 with 10 session IDs. Integration HEAD matches saved state: `5f676710e5b2fdadbcb3a3fc421c98ddd1e0af93`.

State SHA-256: `DD72E5B5FFB85AACC78097C05EC9D32F9B3492452BAB885F1740B88E6AA586C3`.
Backup SHA-256: `EE62F064E716A1C9D9881857783BC82BEE282FC164151D29CC7D839A9F4B4D98`.

The integration working tree was clean. Nonempty working-tree inventories were observed for applications, devtools, and stdlib; therefore copying Git commits/bundles alone would lose work. Source files, STOP, configuration and saved state were not changed during preflight.

Migration must export explicit Git refs and candidate ancestry plus reviewed role-owned dirty patches/untracked regular files, with hashes. Preserve rejected/rework history needed for recovery. Exclude credentials, private_materials, environment secrets, Git hooks/configuration, host caches, and unrelated workspace data. Scan reachable history too; an archive of current filenames alone cannot establish absence of secrets.

Restore into new repositories with local-only remotes and disabled pushes. Rebuild Linux executable paths, Python paths, permission scopes, lane origin URLs, and evidence paths. Do not overwrite the Windows original or delete it after transfer.

Native Devin session portability is unproven. ATIF exports and session IDs are not documented import support. Probe supported resume after fresh VM authentication; if new session IDs are necessary, retain research continuity through checked reports and task memory and explicitly report the change. Archive historical exports outside active `runs/`, because `recover_finished()` otherwise restores old session IDs.

Reconcile unfinished integration journals before migration, preserve original evidence, and explicitly remap verified log paths. Windows absolute journal paths are not valid Linux evidence paths. Keep a migration manifest mapping old/new roots and refs, and compare hashes and dirty edits before enabling execution.

## Evidence limits

Portability review identified work required in process admission, settings/config regeneration, session recovery, journal relocation, and process containment. No installer or OS image was downloaded, no VM created, no guest authentication performed, and no model session resumed. Fable latest-report inspection returned the previous preflight-only result (`not_run`); no external audit approval is claimed.

### Linux admission preparation

`check_existing_sessions()` now checks a Linux `ps` process-name listing for `devin` and `devin.exe`, refuses empty/malformed listings, propagates command errors, and rejects unsupported platforms rather than silently admitting a new fleet. The Windows path is unchanged. This is a best-effort local process snapshot, not an account-wide limit, an OS isolation mechanism, or protection against renamed processes/races/hidden processes.

Verification on the bundled Windows Python: 30 targeted tests passed (8 new mocked Linux/Windows admission cases, 12 control-plane tests, 2 existing Windows concurrency tests, 8 permission-recovery tests). No Linux VM is available yet; actual Linux process naming, visibility, and service lifecycle must be validated inside the guest before enabling model execution. These targeted tests do not replace the prior full suite or constitute VM acceptance.

The runtime state SHA-256 above remained unchanged during preparation; STOP remains present, runner lock is released, and no Devin process was observed. Installation and VM creation still await the user's explicit host-driver/install confirmation requested in conversation.

## Primary references

- https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/host-hardware-requirements
- https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/installation.html
