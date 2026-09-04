"""Public package and runtime version helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


PACKAGE_NAME = "e-base-computer"
SOURCE_VERSION = "0.2.0"


def package_version() -> str:
    """Return installed metadata when available, with a source-tree fallback."""

    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return SOURCE_VERSION


__version__ = package_version()
