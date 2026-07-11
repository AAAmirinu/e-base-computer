"""Insert or update pyproject project.urls for the final GitHub repository."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYPROJECT = ROOT / "pyproject.toml"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finalize_project_urls")
    parser.add_argument("repo", help="GitHub repository slug, for example OWNER/REPO")
    parser.add_argument("--path", type=Path, default=DEFAULT_PYPROJECT)
    parser.add_argument("--apply", action="store_true", help="write changes to pyproject.toml")
    parser.add_argument(
        "--playground-url",
        help="override the default GitHub Pages URL, for custom domains or user/org pages",
    )
    args = parser.parse_args(argv)

    try:
        updated = update_pyproject_urls(
            args.path.read_text(encoding="utf-8"),
            args.repo,
            playground_url=args.playground_url,
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    if args.apply:
        args.path.write_text(updated, encoding="utf-8", newline="\n")
        print(f"updated {args.path}")
    else:
        print("dry run: pass --apply to write these project URLs")
        print(project_urls_block(args.repo, playground_url=args.playground_url).rstrip())
    return 0


def update_pyproject_urls(text: str, repo: str, playground_url: str | None = None) -> str:
    validate_repo(repo)
    block = project_urls_block(repo, playground_url=playground_url)
    lines = text.splitlines()
    start = find_section(lines, "[project.urls]")
    if start is not None:
        end = find_next_section(lines, start + 1)
        return "\n".join(lines[:start] + block.rstrip().splitlines() + lines[end:]) + "\n"

    insert_at = find_section(lines, "[project.scripts]")
    if insert_at is None:
        insert_at = find_section(lines, "[tool.setuptools]")
    if insert_at is None:
        raise ValueError("cannot find insertion point before [project.scripts] or [tool.setuptools]")
    prefix = lines[:insert_at]
    suffix = lines[insert_at:]
    if prefix and prefix[-1].strip():
        prefix.append("")
    return "\n".join(prefix + block.rstrip().splitlines() + [""] + suffix) + "\n"


def project_urls_block(repo: str, playground_url: str | None = None) -> str:
    validate_repo(repo)
    owner, name = repo.split("/", 1)
    github = f"https://github.com/{owner}/{name}"
    pages = playground_url or f"https://{owner}.github.io/{name}/"
    return (
        "[project.urls]\n"
        f'Homepage = "{github}"\n'
        f'Repository = "{github}"\n'
        f'Issues = "{github}/issues"\n'
        f'Discussions = "{github}/discussions"\n'
        f'Playground = "{pages}"\n'
    )


def validate_repo(repo: str) -> None:
    if not REPO_RE.fullmatch(repo):
        raise ValueError("repo must look like OWNER/REPO")
    if repo == "OWNER/REPO":
        raise ValueError("replace OWNER/REPO with the real repository slug")


def find_section(lines: List[str], header: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == header:
            return index
    return None


def find_next_section(lines: List[str], start: int) -> int:
    for index in range(start, len(lines)):
        line = lines[index].strip()
        if line.startswith("[") and line.endswith("]"):
            return index
    return len(lines)


if __name__ == "__main__":
    raise SystemExit(main())
