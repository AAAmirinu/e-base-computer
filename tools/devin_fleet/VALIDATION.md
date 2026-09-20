# Reboot and permission-control validation — 2026-09-15

Historical validation below describes the original host runner. For the newer dedicated WSL and mountless microVM work, see `SANDBOX_HANDOFF.md`. On 2026-09-17 the new sandbox controller passed 11 mock transport tests on Windows and Linux and a real single-sandbox timeout/stop/persistence smoke test. The production ten-role runner remains unconverted and stopped; these results do not authorize its host-code execution path.

Result: 87 tests passed in 95.774 seconds with the bundled Windows Python.

```powershell
& 'C:\Users\main\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -m unittest discover -s tools/devin_fleet -p 'test_*.py' -v
```

The tests cover:

- Existing driver policies, ownership, model identity, same-session permission recovery, and local Git workflows: 42.
- Atomic state writes, backup recovery, corrupt-original preservation, and integration-journal validation: 21.
- Actual process locks, child/grandchild STOP, timeout, and large combined output without pipe deadlock: 7.
- Actual Git integration recovery before/after fast-forward, changed evidence/unknown HEAD refusal, and interrupted-session receipt recovery: 5.
- Start/Resume/STOP races, hold recovery from older state, explicit retry without permission changes, coordinator hold, and unaffected-worker progress: 12.

The first full driver regression run exposed one obsolete test mock after the audit runner changed to supervised execution. The mock was updated to intercept that execution boundary; the full suite above passed afterward. No Devin or generated guest code is executed by these tests. Windows process-tree tests needed permission to terminate only their own test-created Python children; sandbox-restricted termination was not counted as a pass.

PowerShell wrapper AST parsing passed. The actual fleet's `StopAndWait` returned with the global runner lock released. A direct `run --cycles 1` while STOP remained set exited without launching Devin and created a valid state backup.

## Actual runtime handoff snapshot

- Round: 6; status: stopped; STOP: present; global runner lock: not held.
- Devin processes observed: 0.
- Retained session identities: 10.
- Retained candidates: 7 integrated locally, 13 pending.
- `state.json.bak`: present.
- The earlier devtools failure remains in state as diagnostic evidence, not erased by stopping.
- No remote push, PR, merge to a public branch, release, or Windows autostart registration was performed in this maintenance pass.

## Limits and remaining gates

This is process/fault-injection testing, not an actual PC reboot or power-loss test. The new control flow has not yet run another live ten-role model round. Fable MCP was used in preflight mode; no external live audit verdict was obtained.

CLI `normal` is explicitly selected; `auto` is its alias in installed CLI 3000.10.21, not Smart. Scope-prefix rules are not an OS sandbox. The host Python runner executes generated tests outside Devin's approval system. Orphaned/detached test children are not fully contained without OS isolation. A dedicated environment with no personal credentials is recommended before long unattended operation; none has been provisioned here.

The runtime remains stopped pending the user's choice of execution isolation. The safe manual lifecycle and permission-hold review procedure are in README.md.
