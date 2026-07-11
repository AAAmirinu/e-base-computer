"""Emit baseline EPU assembly files for the compiler challenge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from epu_challenge import OFFICIAL_CHALLENGE_SLUGS, official_assembly_for_slug


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emit_baseline_assembly")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "generated-assembly",
        help="directory that will receive <slug>.epu files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing .epu files",
    )
    args = parser.parse_args(argv)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    skipped: list[Path] = []
    for slug in OFFICIAL_CHALLENGE_SLUGS:
        path = output / f"{slug}.epu"
        if path.exists() and not args.force:
            skipped.append(path)
            continue
        path.write_text(official_assembly_for_slug(slug).rstrip() + "\n", encoding="utf-8")
        written.append(path)

    for path in written:
        print(f"wrote {path}")
    for path in skipped:
        print(f"skip existing {path}; pass --force to overwrite")
    print(f"assembly_dir: {output}")
    print(f"next: python -m epu_cli challenge --assembly-dir {output} --json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
