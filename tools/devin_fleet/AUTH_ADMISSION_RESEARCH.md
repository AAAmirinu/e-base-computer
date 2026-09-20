# Authentication admission research (2026-09-19)

Reviewed official CLI documentation:

- https://docs.devin.ai/cli/reference/commands
- https://docs.devin.ai/cli/enterprise/devin-auth

The commands page documents `devin auth status` but does not specify a
machine-readable success schema, JSON flag for this command, or success
exit-code contract. The explicit `--format json` support documented for
`models list` must not be assumed to apply to `auth status`.

Therefore retain the existing conservative offline classifications:
`not_logged_in`, `unclassified`, and `timeout`. In particular, an unknown
response with exit code zero is not authentication admission. Raw status
output and credentials remain suppressed and are not copied between VMs.

The enterprise auth page is specifically about enterprise accounts and
does not prove the account type or billing of these role VMs. Do not use
its billing claims to replace the fresh Free catalog gate or to authorize
a cloud API route. No API fallback or credential extraction is introduced.

Remaining evidence needed for production: version-specific CLI status
behavior safely classified in-guest, successful user login per role,
fresh exact-model Free catalog, permission and isolation checks. Historical
machine smoke success is not a durable all-role authentication certificate.
No production flag, network rule, credential or runtime session was changed
by this research.
