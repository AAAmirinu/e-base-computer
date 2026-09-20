"""Retired: model-role VMs must not execute validation or generated source.

Use validation_snapshot_dispatch with the separate credential-free validation
container. Historical synthetic STOP evidence does not authorize this old route.
"""


def main():
    raise RuntimeError('Retired role-VM validation smoke; use credential-free snapshot validation')


if __name__ == '__main__':
    main()
