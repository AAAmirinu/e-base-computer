from pathlib import Path
import contextlib
import io
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from finalize_project_urls import main, project_urls_block, update_pyproject_urls
from make_release_bundle import create_bundle, iter_bundle_files, should_exclude


class FinalizeProjectUrlsTests(unittest.TestCase):
    def test_project_urls_block_contains_github_and_pages_urls(self) -> None:
        block = project_urls_block("openai/e-base-computer")

        self.assertIn('Homepage = "https://github.com/openai/e-base-computer"', block)
        self.assertIn('Issues = "https://github.com/openai/e-base-computer/issues"', block)
        self.assertIn('Playground = "https://openai.github.io/e-base-computer/"', block)

    def test_update_pyproject_urls_inserts_before_project_scripts(self) -> None:
        text = """[project]
name = "demo"

[project.scripts]
demo = "demo:main"
"""
        updated = update_pyproject_urls(text, "owner/repo")

        self.assertLess(updated.index("[project.urls]"), updated.index("[project.scripts]"))
        self.assertIn('Repository = "https://github.com/owner/repo"', updated)

    def test_update_pyproject_urls_replaces_existing_block(self) -> None:
        text = """[project]
name = "demo"

[project.urls]
Homepage = "https://example.test/old"

[project.scripts]
demo = "demo:main"
"""
        updated = update_pyproject_urls(text, "owner/repo")

        self.assertNotIn("example.test", updated)
        self.assertEqual(updated.count("[project.urls]"), 1)

    def test_update_pyproject_urls_accepts_custom_playground_url(self) -> None:
        text = """[project]
name = "demo"

[project.scripts]
demo = "demo:main"
"""
        updated = update_pyproject_urls(
            text,
            "owner/repo",
            playground_url="https://play.example.test/",
        )

        self.assertIn('Playground = "https://play.example.test/"', updated)

    def test_main_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pyproject.toml"
            original = "[project]\nname = \"demo\"\n\n[project.scripts]\ndemo = \"demo:main\"\n"
            path.write_text(original, encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["owner/repo", "--path", str(path)]), 0)

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_main_rejects_placeholder_repo(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["OWNER/REPO"]), 1)


class MakeReleaseBundleTests(unittest.TestCase):
    def test_iter_bundle_files_keeps_public_assets_and_excludes_generated_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root.joinpath("README.md").write_text("hello", encoding="utf-8")
            root.joinpath(".github", "workflows").mkdir(parents=True)
            root.joinpath(".github", "workflows", "tests.yml").write_text("name: tests", encoding="utf-8")
            root.joinpath(".git").mkdir()
            root.joinpath(".git", "config").write_text("[core]", encoding="utf-8")
            root.joinpath("dist").mkdir()
            root.joinpath("dist", "old.zip").write_text("old", encoding="utf-8")
            root.joinpath("generated-assembly").mkdir()
            root.joinpath("generated-assembly", "factorial.epu").write_text("generated", encoding="utf-8")
            root.joinpath("src").mkdir()
            root.joinpath("src", "module.pyc").write_bytes(b"cache")

            names = {path.relative_to(root).as_posix() for path in iter_bundle_files(root)}

            self.assertIn("README.md", names)
            self.assertIn(".github/workflows/tests.yml", names)
            self.assertNotIn(".git/config", names)
            self.assertNotIn("dist/old.zip", names)
            self.assertNotIn("generated-assembly/factorial.epu", names)
            self.assertNotIn("src/module.pyc", names)

    def test_should_exclude_internal_agent_artifacts(self) -> None:
        self.assertTrue(should_exclude(Path(".ai/audits/packet.json")))
        self.assertTrue(should_exclude(Path(".ai/fable-auditor/project-policy.json")))
        self.assertTrue(should_exclude(Path(".agents/config.json")))

    def test_create_bundle_uses_clean_top_level_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root.joinpath("README.md").write_text("hello", encoding="utf-8")
            output = root / "dist" / "e-base-computer-0.1.0-source.zip"
            files = list(iter_bundle_files(root))

            create_bundle(root, output, files)

            import zipfile

            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["e-base-computer-0.1.0/README.md"])


if __name__ == "__main__":
    unittest.main()
