"""Command line interface for the E-base computer toolkit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, Optional

from cstyle_compiler import CStyleCompiler, compile_source
from emulator import EPUEmulator
from epu import EPUError
from epu_challenge import (
    run_challenge,
    run_numerical_suite,
    run_official_suite,
    summarize_numerical_suite,
    summarize_suite,
)
from epu_experiments import get_experiment, list_experiments
from epu_leaderboard import format_leaderboard_markdown, leaderboard_payload, load_leaderboard
from epu_scoring import score_timeline
from epu_spec import grouped_specs, spec_payload


EXAMPLE_SOURCE = """let n = 5;
let acc = 1;

while (n > 1) {
    acc = acc * n;
    n = n - 1;
}

print(acc);
"""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ebase", description="E-base computer tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="compile C-like source to EPU assembly")
    compile_parser.add_argument("file", type=Path)
    compile_parser.add_argument("--precision", type=int, default=8)

    run_parser = subparsers.add_parser("run", help="run C-like source or EPU assembly")
    run_parser.add_argument("file", type=Path)
    run_parser.add_argument("--language", choices=["c", "asm"], default="c")
    run_parser.add_argument("--precision", type=int, default=8)
    run_parser.add_argument("--max-steps", type=int, default=10_000)
    run_parser.add_argument("--json", action="store_true", help="emit JSON result")

    demo_parser = subparsers.add_parser("demo", help="print a starter C-like program")
    demo_parser.add_argument("--run", action="store_true", help="also compile and run the demo")

    samples_parser = subparsers.add_parser("samples", help="list, show, or run built-in experiments")
    samples_parser.add_argument("name", nargs="?")
    samples_parser.add_argument("--run", action="store_true", help="run the selected experiment")
    samples_parser.add_argument("--json", action="store_true", help="emit JSON")

    challenge_parser = subparsers.add_parser("challenge", help="run official challenge scoring")
    challenge_parser.add_argument("name", nargs="?", help="optional sample slug")
    challenge_parser.add_argument("--max-steps", type=int, default=10_000)
    challenge_parser.add_argument(
        "--suite",
        choices=["official", "numerical"],
        default="official",
        help="challenge suite to run (default: official)",
    )
    challenge_parser.add_argument(
        "--assembly-dir",
        type=Path,
        help="directory containing generated <challenge-slug>.epu files to score",
    )
    challenge_parser.add_argument("--json", action="store_true", help="emit JSON")

    leaderboard_parser = subparsers.add_parser(
        "leaderboard",
        help="rank one or more ebase challenge JSON submissions",
    )
    leaderboard_parser.add_argument("files", nargs="+", type=Path)
    leaderboard_parser.add_argument(
        "--best-per-participant",
        action="store_true",
        help="keep only the best valid ranking entry per participant name",
    )
    leaderboard_parser.add_argument("--json", action="store_true", help="emit JSON")

    spec_parser = subparsers.add_parser("spec", help="print the EPU instruction reference")
    spec_parser.add_argument("--json", action="store_true", help="emit JSON")

    args = parser.parse_args(argv)

    try:
        if args.command == "compile":
            source = args.file.read_text(encoding="utf-8")
            compiled = compile_source(source, precision=args.precision)
            sys.stdout.write(compiled.assembly)
            return 0

        if args.command == "run":
            source = args.file.read_text(encoding="utf-8")
            if args.language == "c":
                compiled = CStyleCompiler(precision=args.precision).compile(source)
                assembly = compiled.assembly
            else:
                assembly = source
            emulator = EPUEmulator(max_steps=args.max_steps)
            result = emulator.run(assembly)
            payload = {
                "output": result.output,
                "halted": result.halted,
                "steps": result.steps,
                "pc": result.pc,
                "score": score_timeline(emulator.epu.timeline()).to_dict(),
            }
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                for key, value in result.output.items():
                    print(f"{key}: {value}")
                score = payload["score"]
                assert isinstance(score, dict)
                print(
                    "score: "
                    f"{score['score']} "
                    f"(steps={score['steps']}, max_temp={score['max_temperature']}, "
                    f"observations={score['observations']}, degraded={score['degraded_events']})"
                )
            return 0

        if args.command == "demo":
            print(EXAMPLE_SOURCE)
            if args.run:
                compiled = CStyleCompiler().compile(EXAMPLE_SOURCE)
                result = EPUEmulator().run(compiled.assembly)
                print("ASSEMBLY:")
                print(compiled.assembly)
                print("OUTPUT:")
                for key, value in result.output.items():
                    print(f"{key}: {value}")
            return 0

        if args.command == "samples":
            if args.name is None:
                experiments = [experiment.to_dict() for experiment in list_experiments()]
                if args.json:
                    print(json.dumps({"samples": experiments}, indent=2, ensure_ascii=False))
                else:
                    for experiment in experiments:
                        print(f"{experiment['slug']}: {experiment['title']} [{experiment['language']}]")
                return 0

            experiment = get_experiment(args.name)
            if not args.run:
                if args.json:
                    print(json.dumps(experiment.to_dict(), indent=2, ensure_ascii=False))
                else:
                    print(experiment.source)
                return 0

            assembly = (
                CStyleCompiler().compile(experiment.source).assembly
                if experiment.language == "c"
                else experiment.source
            )
            emulator = EPUEmulator()
            result = emulator.run(assembly)
            payload = {
                "experiment": experiment.to_dict(),
                "assembly": assembly,
                "output": result.output,
                "steps": result.steps,
                "score": score_timeline(emulator.epu.timeline()).to_dict(),
            }
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                for key, value in result.output.items():
                    print(f"{key}: {value}")
                print(f"score: {payload['score']['score']}")
            return 0

        if args.command == "challenge":
            if args.name and args.suite != "official":
                raise ValueError("a named challenge cannot be combined with --suite")
            if args.name:
                result = run_challenge(
                    args.name,
                    max_steps=args.max_steps,
                    assembly_dir=args.assembly_dir,
                )
                payload = result.to_dict()
            else:
                runner = run_numerical_suite if args.suite == "numerical" else run_official_suite
                summarizer = (
                    summarize_numerical_suite
                    if args.suite == "numerical"
                    else summarize_suite
                )
                payload = summarizer(
                    runner(
                        max_steps=args.max_steps,
                        assembly_dir=args.assembly_dir,
                    )
                )
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            elif args.name:
                print_challenge_result(payload)
            else:
                assert isinstance(payload["results"], list)
                for result in payload["results"]:
                    assert isinstance(result, dict)
                    print_challenge_result(result)
                print(f"total_score: {payload['total_score']}")
                print(f"correct: {payload['correct']}")
            return 0

        if args.command == "leaderboard":
            entries = load_leaderboard(
                args.files,
                best_per_participant=args.best_per_participant,
            )
            if args.json:
                print(json.dumps(leaderboard_payload(entries), indent=2, ensure_ascii=False))
            else:
                print(format_leaderboard_markdown(entries))
            return 0 if all(entry.valid for entry in entries) else 1

        if args.command == "spec":
            if args.json:
                print(json.dumps(spec_payload(), indent=2, ensure_ascii=False))
            else:
                for group, specs in grouped_specs().items():
                    print(f"[{group}]")
                    for spec in specs:
                        operands = " " + ", ".join(spec.operands) if spec.operands else ""
                        print(f"  {spec.opcode}{operands}")
                        print(f"    {spec.summary}")
                    print()
            return 0
    except (OSError, ValueError, KeyError, EPUError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 2


def print_challenge_result(result: Dict[str, object]) -> None:
    score = result["score"]
    assert isinstance(score, dict)
    numerical = (
        f" numerical_score={result['numerical_score']} "
        f"accuracy_digits={result['accuracy_digits']}"
        if "numerical_score" in result
        else ""
    )
    print(
        f"{result['slug']}: correct={result['correct']} "
        f"score={score['score']} steps={result['steps']} "
        f"assembly_lines={result['assembly_lines']} max_temp={score['max_temperature']}"
        f"{numerical}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
