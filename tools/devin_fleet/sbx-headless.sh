#!/bin/sh
# Trusted controller entry point inside EBase-Sandboxes, never an agent tool.
# No ambient desktop, SSH-agent, or Windows executable integration.
set -eu
if [ "$(id -un)" != fleet ] || [ "${WSL_DISTRO_NAME:-}" != EBase-Sandboxes ]; then
    echo 'Refusing non-dedicated user or distro' >&2
    exit 64
fi
unset DISPLAY WAYLAND_DISPLAY PULSE_SERVER SSH_AUTH_SOCK SSH_AGENT_PID
unset DBUS_SESSION_BUS_ADDRESS
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
/usr/bin/python3 -I /usr/local/libexec/e-base-managed-cli-guard.py
exec /usr/bin/sbx "$@"
