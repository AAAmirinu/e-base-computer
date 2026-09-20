# Dedicated Linux maintenance entry point

This is not the production scheduler. It has no start, resume, model, merge,
push or publication command. Keep the original Windows fleet STOP in place.
Use only the dedicated `EBase-Sandboxes` distro as `fleet`.

## Status

The following exact command was verified from `/home/fleet/controller-validation`:

```sh
python3 sandbox_driver.py --registry /home/fleet/controller-validation/sandbox-registry.json --root /home/fleet/controller-validation/interruption-evidence-979232ccf9954d10aaf67ddff1f8daf2 status
```

It checks registered UUIDs with `sbx ls` only: no VM start/stop, runtime lock,
repository access, or credential inspection. All ten roles reported stopped.
`stop_requested` describes ONLY the specified root, not the original Windows
fleet or other roots. `resume_available=false` is intentional. Replaced, duplicate,
missing or unrecognized VM identities are reported as mismatches, never repaired.

## Inspect a synchronization receipt

Generic syntax (replace the uppercase placeholders with explicit absolute paths):

```sh
python3 sandbox_driver.py --registry REGISTRY_JSON --root PRIVATE_DRIVER_ROOT inspect-sync --receipt RECEIPT_JSON --operation OPERATION_HEX --evidence NEW_EVIDENCE_DIRECTORY
```

Prerequisites:

- Registry must carry the explicit sandbox backend and original canonical migration
  epoch. The provision-only registry above does not have a production epoch and
  must not be silently converted. Legacy schema-1 sync receipts are not accepted.
- Root must already exist, be private/owned by fleet, and have no symlink ancestor.
  Evidence must be a fresh direct child; old evidence is never overwritten.
- Any STOP directory entry, including a dangling symlink, blocks inspection. The
  command never clears STOP. Choose the original controller root for real recovery;
  do not select a different root to evade a stop request.
- All ten registered VMs must be demonstrably stopped before the runtime lock
  admits inspection. Linux uses the fixed `/tmp/e-base-devin-fleet-global.lock`,
  independent of temporary-directory environment overrides.
- The receipt must identify the target's normal role repository. Nested test probe
  receipts intentionally do not match the normal role repository; test-only
  reinspection scripts provide an explicit probe adapter separately.

Inspection starts the selected VM, checks its recorded commit lineage, worktree,
branch and operation markers, then stops it and writes separate evidence. It is
not a read-only status query. It never replays a merge or authorizes resumption.
An incomplete `checking` record requires inspection; it is not a success receipt.

## Validation and remaining work

Windows trusted sandbox tests: 111 total, 109 passed and two Linux-only skips.
Dedicated Linux driver/runtime tests: all 22 passed, including no-follow input
reads and fixed lock namespace. Live CLI status passed without starting any VM.
CLI inspection against the staged real storage role now passed with a no-op
receipt, after local metadata exclusion was restored. A separate Python process
ran status and inspect-sync, retained original receipt bytes, and reported
verified_applied with replay_permitted=false. A STOP created only in the fresh
test driver root caused a second inspect command to return 2 without creating
evidence; status still worked and reported all ten VMs stopped. This is a
maintenance/no-op test, not production activation or model execution.

Retained evidence root:
`/home/fleet/controller-validation/driver-evidence-89130fb9fa1540eeb11a0d026585fbfd`.
Operation `10bcbc24b9504b69893e09a41890287c`, test epoch
`5ce7b56c-df5f-4a04-926b-4472b845dbfa`, original receipt SHA256
`8a22390bb09bea6ca5dd6d3a224634affcd37211caaee64ae84975d25291898d`.
Observed storage HEAD remained `e7271a6eaca0204c77925ed6e5723412a1c4477e`.
The test-root STOP remains in place, as does the separate original Windows STOP.
The underlying helper also has separate synthetic interruption/reinspection evidence.

Authentication, production-root migration, scheduler/role execution integration,
capacity admission, clipboard boundary and full reboot recovery remain open.
Fable latest report is `not_run`, not external audit acceptance.
