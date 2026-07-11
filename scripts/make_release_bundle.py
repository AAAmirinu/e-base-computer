"""Create a clean source bundle for manual GitHub publishing."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable, List
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
EXCLUDED_DIRS = {
    ".agents",
    ".ai",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "generated-assembly",
    "private_materials",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_release_bundle")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="project root to bundle",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="zip file to write; defaults to dist/<project>-<version>-source.zip",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned bundle path and file count without writing",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    output = args.output.resolve() if args.output else default_output_path(root)
    files = list(iter_bundle_files(root))

    if args.dry_run:
        print(f"bundle: {output}")
        print(f"files: {len(files)}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    create_bundle(root, output, files)
    print(f"created {output}")
    print(f"files: {len(files)}")
    return 0


def default_output_path(root: Path) -> Path:
    metadata = project_metadata(root)
    name = normalize_archive_name(str(metadata.get("name", "e-base-computer")))
    version = normalize_archive_name(str(metadata.get("version", "0.0.0")))
    return root / "dist" / f"{name}-{version}-source.zip"


def project_metadata(root: Path) -> dict[str, object]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    if isinstance(project, dict):
        return project
    return {}


def normalize_archive_name(value: str) -> str:
    chars = []
    for char in value:
        if char.isalnum() or char in ".-_":
            chars.append(char)
        else:
            chars.append("-")
    return "".join(chars).strip(".-_") or "bundle"


def iter_bundle_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        if should_exclude(relative):
            continue
        yield path


def should_exclude(relative: Path) -> bool:
    parts = relative.parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    posix = relative.as_posix()
    if relative.name in EXCLUDED_NAMES:
        return True
    return relative.suffix in EXCLUDED_SUFFIXES


def create_bundle(root: Path, output: Path, files: Iterable[Path]) -> None:
    prefix = output.stem.removesuffix("-source")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = ZipInfo(f"{prefix}/{relative}", DEFAULT_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            if path.stat().st_mode & 0o111:
                info.external_attr = 0o755 << 16
            else:
                info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


if __name__ == "__main__":
    raise SystemExit(main())
