"""Command-line boundary for read-only EPU calibration residual evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional

from epu_calibration import CalibrationDataError, evaluate_calibration_file


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ebase-calibrate")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    args = parser.parse_args(argv)
    try:
        payload = evaluate_calibration_file(args.dataset)
    except (CalibrationDataError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
