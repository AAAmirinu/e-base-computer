"""Fail-closed checks for versioned E-base release metadata and artifacts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import tarfile
from typing import Iterable, List
from zipfile import ZipFile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}


class ReleaseVerificationError(ValueError):
    """Raised when release metadata or an artifact is inconsistent."""


def load_project(root: Path) -> tuple[str, str]:
    with (root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle).get("project", {})
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        raise ReleaseVerificationError("pyproject project.name is missing")
    if not isinstance(version, str) or not version:
        raise ReleaseVerificationError("pyproject project.version is missing")
    return name, version


def release_notes_path(root: Path, version: str) -> Path:
    parts = version.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        raise ReleaseVerificationError(f"unsupported release version: {version}")
    return root / "docs" / f"release_notes_v{parts[0]}_{parts[1]}.md"


def verify_metadata(root: Path, tag: str | None = None) -> tuple[str, str, Path]:
    name, version = load_project(root)
    expected_tag = f"v{version}"
    if tag is not None and tag != expected_tag:
        raise ReleaseVerificationError(
            f"release tag {tag!r} does not match package version {version!r}; "
            f"expected {expected_tag!r}"
        )

    source_version_path = root / "src" / "epu_version.py"
    namespace: dict[str, object] = {}
    exec(compile(source_version_path.read_text(encoding="utf-8"), str(source_version_path), "exec"), namespace)
    if namespace.get("SOURCE_VERSION") != version:
        raise ReleaseVerificationError("src/epu_version.py SOURCE_VERSION does not match pyproject")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version} - " not in changelog:
        raise ReleaseVerificationError(f"CHANGELOG has no dated {version} heading")

    notes = release_notes_path(root, version)
    expected_heading = f"# E-base Computer v{version} Release Notes"
    if not notes.exists() or expected_heading not in notes.read_text(encoding="utf-8"):
        raise ReleaseVerificationError(f"release notes are missing heading: {expected_heading}")
    return name, version, notes


def _exactly_one(paths: Iterable[Path], description: str) -> Path:
    matches = list(paths)
    if len(matches) != 1:
        raise ReleaseVerificationError(
            f"expected exactly one {description}, found {len(matches)}: "
            + ", ".join(path.name for path in matches)
        )
    return matches[0]


def _wheel_metadata(wheel: Path) -> dict[str, str]:
    with ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ReleaseVerificationError(f"wheel has {len(metadata_names)} METADATA files")
        text = archive.read(metadata_names[0]).decode("utf-8")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key, value)
    return fields


def _is_sensitive_archive_name(name: str, *, allow_egg_info: bool = False) -> bool:
    path = Path(name)
    lowered_parts = [part.lower() for part in path.parts]
    if not allow_egg_info and any(part.endswith(".egg-info") for part in lowered_parts):
        return True
    if any(part in {".ai", ".agents", ".codex", ".git", "private_materials"} for part in lowered_parts):
        return True
    lowered_name = path.name.lower()
    if lowered_name == ".env" or (lowered_name.startswith(".env.") and lowered_name != ".env.example"):
        return True
    return path.suffix.lower() in SENSITIVE_SUFFIXES


def verify_artifacts(dist: Path, project_name: str, version: str) -> List[Path]:
    normalized = project_name.replace("-", "_")
    wheel = _exactly_one(dist.glob(f"{normalized}-{version}-*.whl"), "wheel")
    sdist = _exactly_one(
        list(dist.glob(f"{normalized}-{version}.tar.gz"))
        + list(dist.glob(f"{project_name}-{version}.tar.gz")),
        "sdist",
    )
    source_zip = _exactly_one(dist.glob(f"{project_name}-{version}-source.zip"), "source ZIP")

    metadata = _wheel_metadata(wheel)
    if metadata.get("Name") != project_name or metadata.get("Version") != version:
        raise ReleaseVerificationError(
            f"wheel metadata mismatch: Name={metadata.get('Name')!r}, Version={metadata.get('Version')!r}"
        )

    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = archive.getnames()
    with ZipFile(source_zip) as archive:
        source_names = archive.namelist()
    for description, names, allow_egg_info in (
        ("sdist", sdist_names, True),
        ("source ZIP", source_names, False),
    ):
        if any(_is_sensitive_archive_name(name, allow_egg_info=allow_egg_info) for name in names):
            raise ReleaseVerificationError(f"{description} contains excluded or sensitive paths")
    expected_prefix = f"{project_name}-{version}/"
    if not source_names or any(not name.startswith(expected_prefix) for name in source_names):
        raise ReleaseVerificationError(f"source ZIP entries must be rooted at {expected_prefix}")

    return [wheel, sdist, source_zip]


def write_checksums(artifacts: Iterable[Path], output: Path) -> None:
    lines = []
    for artifact in sorted(artifacts, key=lambda path: path.name):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact.name}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_release")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tag", help="tag to require, for example v0.2.0")
    parser.add_argument("--dist", type=Path, help="distribution directory to verify")
    parser.add_argument("--write-checksums", type=Path, help="write SHA-256 list after artifact verification")
    args = parser.parse_args(argv)

    try:
        root = args.root.resolve()
        name, version, notes = verify_metadata(root, args.tag)
        print(f"project: {name}")
        print(f"version: {version}")
        print(f"release notes: {notes.relative_to(root).as_posix()}")
        if args.write_checksums is not None and args.dist is None:
            raise ReleaseVerificationError("--write-checksums requires --dist")
        if args.dist is not None:
            artifacts = verify_artifacts(args.dist.resolve(), name, version)
            for artifact in artifacts:
                print(f"verified: {artifact}")
            if args.write_checksums is not None:
                output = args.write_checksums.resolve()
                write_checksums(artifacts, output)
                print(f"checksums: {output}")
    except (OSError, ReleaseVerificationError, tarfile.TarError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
