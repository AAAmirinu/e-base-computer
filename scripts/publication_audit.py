"""Audit public-release readiness for the E-base computer repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPECTED_TOTAL_SCORE = 373.1
EXPECTED_CHALLENGES = {"factorial", "e-ladder", "cold-memory", "thermal-degrade", "branching"}


class Audit:
    def __init__(self) -> None:
        self.failures: List[str] = []

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"ok  {label}")
            return
        suffix = f": {detail}" if detail else ""
        print(f"ERR {label}{suffix}")
        self.failures.append(f"{label}{suffix}")

    def require_text(self, path: Path, snippets: Iterable[str]) -> None:
        text = read_text(path)
        for snippet in snippets:
            self.check(
                f"{relative(path)} contains {snippet!r}",
                snippet in text,
            )

    def finish(self) -> int:
        if not self.failures:
            print("publication_audit_ok")
            return 0
        print("\npublication_audit_failed")
        for failure in self.failures:
            print(f"- {failure}")
        return 1


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="publication_audit")
    parser.add_argument("--full", action="store_true", help="also run unit, compile, and JS checks")
    parser.add_argument("--docker", action="store_true", help="also run docker build")
    args = parser.parse_args(argv)

    audit = Audit()
    check_required_files(audit)
    check_public_docs(audit)
    check_packaging(audit)
    check_playground_assets(audit)
    check_challenge_baseline(audit)
    check_github_templates(audit)
    if args.full:
        check_commands(audit)
    if args.docker:
        check_docker_build(audit)
    return audit.finish()


def check_required_files(audit: Audit) -> None:
    required = [
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "pyproject.toml",
        "MANIFEST.in",
        "Dockerfile",
        ".dockerignore",
        ".gitignore",
        ".devcontainer/devcontainer.json",
        ".github/workflows/tests.yml",
        ".github/workflows/pages.yml",
        ".github/workflows/release.yml",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/compiler_challenge.md",
        ".github/ISSUE_TEMPLATE/good_first_experiment.md",
        "docs/compiler_challenge.md",
        "docs/epu_instruction_set.md",
        "docs/playground.md",
        "docs/publish_to_github.md",
        "docs/challenge_kickoff.md",
        "docs/challenge_operations.md",
        "docs/release_checklist.md",
        "docs/release_notes_v0_1.md",
        "docs/assets/playground-challenge.png",
        "examples/compiler_starter/README.md",
        "examples/compiler_starter/emit_baseline_assembly.py",
        "examples/challenges/baseline_submission.json",
        "scripts/finalize_project_urls.py",
        "scripts/make_release_bundle.py",
        "scripts/release_smoke.py",
        "scripts/static_playground_smoke.cjs",
    ]
    for name in required:
        path = ROOT / name
        audit.check(f"{name} exists", path.exists())
        if path.exists() and path.is_file():
            audit.check(f"{name} is not empty", path.stat().st_size > 0)


def check_public_docs(audit: Audit) -> None:
    audit.require_text(
        ROOT / "README.md",
        [
            "docs/assets/playground-challenge.png",
            "Python 3.11",
            "Try the Playground",
            "GitHub Pages版はデモ用",
            "ebase-playground",
            "docker build -t e-base-computer .",
            "GitHub Codespaces",
            "GitHub Pages",
            "Run Official Suite",
            "Copy Program Link",
            "ebase challenge --json",
            "ebase challenge --assembly-dir",
            "emit_baseline_assembly.py",
            "ebase leaderboard",
            "make_release_bundle.py",
            "Issues` -> `New issue` -> `Compiler challenge entry",
            "docs/challenge_kickoff.md",
            "docs/challenge_operations.md",
        ],
    )
    audit.require_text(
        ROOT / "docs" / "compiler_challenge.md",
        ["total_score=373.1", "参加者ワークフロー", "--assembly-dir", "emit_baseline_assembly.py", "factorial.epu", "submission_source", "変更してはいけないもの", "タイブレーク", "ebase leaderboard", "--best-per-participant", "Issues` -> `New issue` -> `Compiler challenge entry"],
    )
    audit.require_text(
        ROOT / "docs" / "challenge_operations.md",
        ["ebase leaderboard", "valid=false", "--best-per-participant", "python -m epu_cli", "--assembly-dir", "公式記録"],
    )
    audit.require_text(
        ROOT / "CHANGELOG.md",
        ["0.1.0", "Initial Public Preview", "ebase spec", "ebase leaderboard", "Copy Program Link", "373.1"],
    )
    audit.require_text(
        ROOT / "docs" / "release_notes_v0_1.md",
        ["E-base Computer v0.1.0", "Run Official Suite", "Good First Contributions", "Known Limits", "Static GitHub Pages", "Copy Program Link", "ebase leaderboard", "finalize_project_urls.py"],
    )
    audit.require_text(
        ROOT / "docs" / "publish_to_github.md",
        ["OWNER/REPO", "project.urls", "finalize_project_urls.py", "make_release_bundle.py", "--playground-url", "docker-smoke", "pages", "ebase leaderboard", "v0.1.0"],
    )
    audit.require_text(
        ROOT / "docs" / "epu_instruction_set.md",
        ["ebase spec --json", "EQUANT", "DEGRADED", "EJGTZ"],
    )
    audit.require_text(
        ROOT / "docs" / "playground.md",
        ["Python 3.11", "/api/challenge", "Copy JSON", "Copy Program Link", "Run Official Suite", "static fallback", "GitHub Pages版はデモ用", "公式チャレンジ提出用JSON", "static_playground_smoke.cjs"],
    )
    audit.require_text(
        ROOT / "examples" / "compiler_starter" / "README.md",
        ["emit_baseline_assembly.py", "generated-assembly", "ebase challenge --assembly-dir", "Safe things to modify", "Do not modify"],
    )
    image = ROOT / "docs" / "assets" / "playground-challenge.png"
    if image.exists():
        audit.check("playground screenshot is PNG", image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


def check_packaging(audit: Audit) -> None:
    audit.require_text(
        ROOT / "pyproject.toml",
        [
            'ebase = "epu_cli:main"',
            'ebase-playground = "web_playground:main"',
            '"epu_challenge"',
            '"epu_leaderboard"',
            '"epu_spec"',
            'e_base_computer_web = ["playground/*"]',
        ],
    )
    audit.require_text(
        ROOT / "MANIFEST.in",
        ["recursive-include docs/assets *.png", "recursive-include examples *.py *.cbase *.epu *.json *.md", "recursive-include src/e_base_computer_web/playground"],
    )
    audit.require_text(ROOT / ".gitignore", ["generated-assembly/"])
    audit.require_text(
        ROOT / "Dockerfile",
        ['CMD ["ebase-playground", "--host", "0.0.0.0", "--port", "8765"]'],
    )
    devcontainer = json.loads(read_text(ROOT / ".devcontainer" / "devcontainer.json"))
    audit.check("devcontainer forwards 8765", 8765 in devcontainer.get("forwardPorts", []))


def check_playground_assets(audit: Audit) -> None:
    source_root = ROOT / "web" / "playground"
    package_root = ROOT / "src" / "e_base_computer_web" / "playground"
    for name in ("index.html", "app.js", "static-runtime.js", "styles.css"):
        source = source_root / name
        packaged = package_root / name
        audit.check(f"packaged playground {name} exists", packaged.exists())
        if source.exists() and packaged.exists():
            audit.check(f"playground {name} is in sync", source.read_bytes() == packaged.read_bytes())
    audit.require_text(source_root / "index.html", ["static-runtime.js", "Run Official Suite", "Copy Program Link", "Copy JSON", "Official Challenge"])
    audit.require_text(source_root / "app.js", ["/api/challenge", "copyChallengeJson", "copyShareLink", "loadSharedState", "runStaticProgram", "demo_only", "sampleDescription"])
    audit.require_text(source_root / "static-runtime.js", ["EBaseStaticRuntime", "runChallengeSuite", "thermal-degrade"])
    index_text = read_text(source_root / "index.html")
    static_index = index_text.find("static-runtime.js")
    app_index = index_text.find("app.js")
    audit.check(
        "static runtime loads before app.js",
        static_index >= 0 and app_index >= 0 and static_index < app_index,
    )


def check_challenge_baseline(audit: Audit) -> None:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SRC))
    try:
        from epu_challenge import OFFICIAL_CHALLENGE_SLUGS, run_official_suite, summarize_suite
        from epu_leaderboard import load_submission
        from epu_spec import spec_payload
        from web_playground import challenge_payload
    except Exception as exc:
        audit.check("challenge modules import", False, str(exc))
        return

    slugs = set(OFFICIAL_CHALLENGE_SLUGS)
    audit.check("official challenge slug set", slugs == EXPECTED_CHALLENGES, repr(slugs))
    try:
        summary = summarize_suite(run_official_suite())
        payload = challenge_payload()
    except Exception as exc:
        audit.check("official challenge executes", False, str(exc))
        return

    audit.check("official challenge correct", summary.get("correct") is True)
    audit.check("official challenge score stable", summary.get("total_score") == EXPECTED_TOTAL_SCORE)
    audit.check("web challenge payload ok", payload.get("ok") is True)
    audit.check("web challenge payload correct", payload.get("correct") is True)
    audit.check("web challenge payload score stable", payload.get("total_score") == EXPECTED_TOTAL_SCORE)
    baseline_entry = load_submission(ROOT / "examples" / "challenges" / "baseline_submission.json")
    audit.check("baseline leaderboard submission valid", baseline_entry.valid)
    audit.check("baseline leaderboard submission score stable", baseline_entry.total_score == EXPECTED_TOTAL_SCORE)
    spec = spec_payload()
    opcodes = {instruction["opcode"] for instruction in spec["instructions"]}  # type: ignore[index]
    audit.check("instruction spec includes E quantization", {"EQOS", "EQUANT", "EDEQ"}.issubset(opcodes))
    audit.check("instruction spec includes control flow", {"EJMP", "EJGTZ", "EHALT"}.issubset(opcodes))


def check_github_templates(audit: Audit) -> None:
    audit.require_text(
        ROOT / ".github" / "ISSUE_TEMPLATE" / "compiler_challenge.md",
        ["ebase challenge --json", "ebase challenge --assembly-dir", "ebase leaderboard", "--best-per-participant", "Generated assembly", "Environment", "Branch or fork URL", "Main diff"],
    )
    audit.require_text(
        ROOT / ".github" / "ISSUE_TEMPLATE" / "good_first_experiment.md",
        ["E digits", "Playground", "python -m epu_cli challenge --json"],
    )
    audit.require_text(
        ROOT / ".github" / "workflows" / "tests.yml",
        ["docker-smoke", "release-smoke", "actions/setup-node@v4", "node-version: \"20\"", "scripts/release_smoke.py", "scripts/static_playground_smoke.cjs", "ebase challenge --json", "--assembly-dir", "/api/challenge"],
    )
    audit.require_text(
        ROOT / ".github" / "workflows" / "pages.yml",
        ["actions/setup-node@v4", "node-version: \"20\"", "scripts/static_playground_smoke.cjs", "upload-pages-artifact", "web/playground", "deploy-pages"],
    )
    audit.require_text(
        ROOT / ".github" / "workflows" / "release.yml",
        ["scripts/release_smoke.py", "python -m build", "twine check", "upload-artifact", "gh release create"],
    )


def check_commands(audit: Audit) -> None:
    commands = [
        ([sys.executable, "-m", "unittest", "discover", "-s", "tests"], "unit tests"),
        ([sys.executable, "-m", "py_compile", "src/epu.py", "src/emulator.py", "src/cstyle_compiler.py", "src/epu_challenge.py", "src/epu_cli.py", "src/epu_leaderboard.py", "src/epu_spec.py", "src/web_playground.py"], "py_compile"),
        ([sys.executable, "-m", "py_compile", "scripts/finalize_project_urls.py"], "release helper py_compile"),
        ([sys.executable, "-m", "py_compile", "scripts/make_release_bundle.py"], "release bundle py_compile"),
        ([sys.executable, "-m", "py_compile", "scripts/release_smoke.py"], "release smoke py_compile"),
        ([sys.executable, "-m", "py_compile", "examples/compiler_starter/emit_baseline_assembly.py"], "compiler starter py_compile"),
        ([sys.executable, "scripts/finalize_project_urls.py", "owner/repo"], "release helper dry run"),
        ([sys.executable, "scripts/finalize_project_urls.py", "owner/repo", "--playground-url", "https://play.example.test/"], "release helper custom playground dry run"),
        ([sys.executable, "scripts/make_release_bundle.py", "--dry-run"], "release bundle dry run"),
        ([sys.executable, "-m", "epu_cli", "challenge", "--json"], "challenge CLI"),
        ([sys.executable, "-m", "epu_cli", "leaderboard", "examples/challenges/baseline_submission.json"], "leaderboard CLI"),
        ([sys.executable, "-m", "epu_cli", "leaderboard", "examples/challenges/*.json"], "leaderboard glob CLI"),
        ([sys.executable, "-m", "epu_cli", "leaderboard", "examples/challenges/*.json", "--best-per-participant"], "leaderboard best CLI"),
        ([sys.executable, "-m", "epu_cli", "spec", "--json"], "spec CLI"),
    ]
    for command, label in commands:
        audit.check(label, run(command))
    check_compiler_starter_command(audit)
    if shutil.which("node"):
        audit.check("source playground JS syntax", run(["node", "--check", "web/playground/app.js"]))
        audit.check("source static runtime JS syntax", run(["node", "--check", "web/playground/static-runtime.js"]))
        audit.check("packaged playground JS syntax", run(["node", "--check", "src/e_base_computer_web/playground/app.js"]))
        audit.check("packaged static runtime JS syntax", run(["node", "--check", "src/e_base_computer_web/playground/static-runtime.js"]))
        audit.check("static playground smoke", run(["node", "scripts/static_playground_smoke.cjs"]))
    else:
        print("skip node checks: node not found")


def check_compiler_starter_command(audit: Audit) -> None:
    with tempfile.TemporaryDirectory(prefix="ebase-starter-audit-") as temp_dir:
        assembly_dir = Path(temp_dir) / "generated-assembly"
        audit.check(
            "compiler starter emits assembly",
            run(
                [
                    sys.executable,
                    "examples/compiler_starter/emit_baseline_assembly.py",
                    "--output",
                    str(assembly_dir),
                ]
            ),
        )
        audit.check(
            "compiler starter assembly scores",
            run(
                [
                    sys.executable,
                    "-m",
                    "epu_cli",
                    "challenge",
                    "--assembly-dir",
                    str(assembly_dir),
                    "--json",
                ]
            ),
        )


def check_docker_build(audit: Audit) -> None:
    if not shutil.which("docker"):
        audit.check("docker executable exists", False)
        return
    audit.check("docker build", run(["docker", "build", "-t", "e-base-computer", "."]))


def run(command: List[str]) -> bool:
    print("+ " + " ".join(command))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0:
        print(completed.stdout)
    return completed.returncode == 0


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
