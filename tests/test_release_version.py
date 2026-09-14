from pathlib import Path
import hashlib
import io
import sys
import tarfile
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_release import (
    ReleaseVerificationError,
    verify_artifacts,
    verify_metadata,
    write_checksums,
)


class ReleaseVersionTests(unittest.TestCase):
    def make_project(self, root: Path, version: str = "0.2.0") -> None:
        root.joinpath("src").mkdir(parents=True)
        root.joinpath("docs").mkdir()
        root.joinpath("pyproject.toml").write_text(
            f'[project]\nname = "e-base-computer"\nversion = "{version}"\n',
            encoding="utf-8",
        )
        root.joinpath("src", "epu_version.py").write_text(
            f'SOURCE_VERSION = "{version}"\n',
            encoding="utf-8",
        )
        root.joinpath("CHANGELOG.md").write_text(
            f"## {version} - 2026-09-04\n",
            encoding="utf-8",
        )
        root.joinpath("docs", "release_notes_v0_2.md").write_text(
            f"# E-base Computer v{version} Release Notes\n",
            encoding="utf-8",
        )

    def make_artifacts(self, dist: Path, *, sensitive_source: bool = False) -> list[Path]:
        dist.mkdir()
        wheel = dist / "e_base_computer-0.2.0-py3-none-any.whl"
        with ZipFile(wheel, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(
                "e_base_computer-0.2.0.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: e-base-computer\nVersion: 0.2.0\n",
            )

        sdist = dist / "e_base_computer-0.2.0.tar.gz"
        payload = b"hello"
        with tarfile.open(sdist, "w:gz") as archive:
            info = tarfile.TarInfo("e_base_computer-0.2.0/README.md")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
            egg = tarfile.TarInfo("e_base_computer-0.2.0/src/e_base_computer.egg-info/PKG-INFO")
            egg.size = len(payload)
            archive.addfile(egg, io.BytesIO(payload))

        source = dist / "e-base-computer-0.2.0-source.zip"
        with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("e-base-computer-0.2.0/README.md", "hello")
            if sensitive_source:
                archive.writestr("e-base-computer-0.2.0/.codex/session.json", "{}")
        return [wheel, sdist, source]

    def test_metadata_requires_exact_tag_and_matching_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.make_project(root)
            name, version, notes = verify_metadata(root, "v0.2.0")
            self.assertEqual((name, version), ("e-base-computer", "0.2.0"))
            self.assertEqual(notes.name, "release_notes_v0_2.md")
            with self.assertRaises(ReleaseVerificationError):
                verify_metadata(root, "v0.2")

    def test_artifacts_and_checksums_are_version_locked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dist = Path(temp_dir) / "dist"
            expected = self.make_artifacts(dist)
            artifacts = verify_artifacts(dist, "e-base-computer", "0.2.0")
            self.assertEqual(set(artifacts), set(expected))

            checksums = dist / "SHA256SUMS.txt"
            write_checksums(artifacts, checksums)
            lines = checksums.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            for artifact in artifacts:
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                self.assertIn(f"{digest}  {artifact.name}", lines)

    def test_source_zip_rejects_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dist = Path(temp_dir) / "dist"
            self.make_artifacts(dist, sensitive_source=True)
            with self.assertRaises(ReleaseVerificationError):
                verify_artifacts(dist, "e-base-computer", "0.2.0")


if __name__ == "__main__":
    unittest.main()
