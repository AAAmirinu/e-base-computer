import contextlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
from importlib import resources
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cstyle_compiler import CStyleCompiler
from emulator import EPUEmulator
from epu_challenge import (
    EXPECTED_OUTPUTS,
    NUMERICAL_CHALLENGE_SLUGS,
    OFFICIAL_CHALLENGE_SLUGS,
    official_assembly_for_slug,
    run_challenge,
    run_numerical_suite,
    run_official_suite,
    summarize_numerical_suite,
    summarize_suite,
)
from epu_cli import main
from epu_experiments import get_experiment
from epu_leaderboard import expand_submission_paths, load_leaderboard, select_best_per_participant
from epu_scoring import score_timeline
from epu_spec import spec_payload
from web_playground import PlaygroundHandler, playground_asset_path, run_payload, samples_payload
from web_playground import challenge_payload


class ScoringTests(unittest.TestCase):
    def test_score_counts_steps_and_observations(self) -> None:
        emulator = EPUEmulator()
        emulator.run(
            """
            ECONST ER0, 2
            EPRINT ER0 ; precision=4
            """
        )

        score = score_timeline(emulator.epu.timeline())

        self.assertEqual(score.steps, 2)
        self.assertEqual(score.observations, 1)
        self.assertGreater(score.score, 0)

    def test_refresh_events_do_not_lower_score(self) -> None:
        base = EPUEmulator()
        base.run(
            """
            ECONST ER0, 2
            EPRINT ER0 ; precision=4
            """
        )
        refreshed = EPUEmulator()
        refreshed.run(
            """
            ECONST ER0, 2
            EREFRESH ER0
            EREFRESH ER0
            EPRINT ER0 ; precision=4
            """
        )

        base_score = score_timeline(base.epu.timeline())
        refreshed_score = score_timeline(refreshed.epu.timeline())

        self.assertEqual(refreshed_score.refresh_events, 2)
        self.assertGreater(refreshed_score.score, base_score.score)


class CLITests(unittest.TestCase):
    def test_cli_compile_and_run_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "program.cbase"
            source_path.write_text("let x = 2 * 3;\nprint(x);\n", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["compile", str(source_path)]), 0)
                self.assertEqual(main(["run", str(source_path), "--json"]), 0)

    def test_cli_reports_missing_file_without_traceback(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["run", "missing-file.cbase"]), 1)
        self.assertIn("error:", stderr.getvalue())

    def test_cli_samples_can_list_and_run_experiments(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["samples"]), 0)
            self.assertEqual(main(["samples", "thermal-degrade", "--run", "--json"]), 0)

        text = stdout.getvalue()
        self.assertIn("factorial", text)
        self.assertIn("thermal-degrade", text)

    def test_cli_challenge_runs_official_suite(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["challenge"]), 0)
            self.assertEqual(main(["challenge", "thermal-degrade", "--json"]), 0)

        text = stdout.getvalue()
        self.assertIn("total_score", text)
        self.assertIn("thermal-degrade", text)

    def test_cli_challenge_json_and_unknown_slug(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["challenge", "--json"]), 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["correct"])
        self.assertEqual(len(payload["results"]), len(OFFICIAL_CHALLENGE_SLUGS))

        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["challenge", "missing-sample"]), 1)
        self.assertIn("error:", stderr.getvalue())

    def test_cli_numerical_challenge_reports_accuracy_and_cost(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["challenge", "--suite", "numerical", "--json"]), 0)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["suite"], "numerical")
        self.assertTrue(payload["correct"])
        self.assertEqual(
            [result["slug"] for result in payload["results"]],
            list(NUMERICAL_CHALLENGE_SLUGS),
        )
        self.assertTrue(all(result["accuracy_digits"] >= 8 for result in payload["results"]))
        self.assertTrue(all(result["numerical_score"] >= result["score"]["score"] for result in payload["results"]))

    def test_numerical_submission_is_ranked_by_error_before_cost(self) -> None:
        baseline = summarize_numerical_suite(run_numerical_suite())
        worse_error = json.loads(json.dumps(baseline))
        worse_error["results"][0]["relative_error"] = 1e-8
        worse_error["results"][0]["accuracy_digits"] = 8.0
        worse_error["results"][0]["numerical_score"] += 0.01
        worse_error["total_score"] += 0.01
        with tempfile.TemporaryDirectory() as temp_dir:
            better_path = Path(temp_dir) / "better.json"
            worse_path = Path(temp_dir) / "worse.json"
            better_path.write_text(json.dumps(baseline), encoding="utf-8")
            worse_path.write_text(json.dumps(worse_error), encoding="utf-8")
            entries = load_leaderboard([worse_path, better_path])

        self.assertEqual(entries[0].participant, "better")
        self.assertEqual(entries[0].suite, "numerical")

    def test_cli_challenge_can_score_generated_assembly_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assembly_dir = Path(temp_dir)
            for slug in OFFICIAL_CHALLENGE_SLUGS:
                assembly_dir.joinpath(f"{slug}.epu").write_text(
                    official_assembly_for_slug(slug),
                    encoding="utf-8",
                )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    main(["challenge", "--assembly-dir", str(assembly_dir), "--json"]),
                    0,
                )
            payload = json.loads(stdout.getvalue())

        self.assertTrue(payload["correct"])
        self.assertEqual(payload["total_score"], 373.1)
        self.assertTrue(
            all(result["submission_source"] == "assembly-dir" for result in payload["results"])
        )

    def test_official_assembly_for_slug_rejects_non_challenge_slug(self) -> None:
        with self.assertRaises(ValueError):
            official_assembly_for_slug("missing-sample")

    def test_compiler_starter_emits_baseline_assembly_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assembly_dir = Path(temp_dir) / "generated-assembly"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "examples" / "compiler_starter" / "emit_baseline_assembly.py"),
                    "--output",
                    str(assembly_dir),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
            self.assertIn("next:", completed.stdout)
            for slug in OFFICIAL_CHALLENGE_SLUGS:
                self.assertTrue(assembly_dir.joinpath(f"{slug}.epu").exists())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    main(["challenge", "--assembly-dir", str(assembly_dir), "--json"]),
                    0,
                )
            payload = json.loads(stdout.getvalue())

        self.assertTrue(payload["correct"])
        self.assertEqual(payload["total_score"], 373.1)
        self.assertTrue(
            all(result["submission_source"] == "assembly-dir" for result in payload["results"])
        )

    def test_compiler_starter_emits_numerical_assembly_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assembly_dir = Path(temp_dir) / "generated-numerical"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "examples" / "compiler_starter" / "emit_baseline_assembly.py"),
                    "--suite",
                    "numerical",
                    "--output",
                    str(assembly_dir),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                {path.stem for path in assembly_dir.glob("*.epu")},
                set(NUMERICAL_CHALLENGE_SLUGS),
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    main([
                        "challenge",
                        "--suite",
                        "numerical",
                        "--assembly-dir",
                        str(assembly_dir),
                        "--json",
                    ]),
                    0,
                )
            payload = json.loads(stdout.getvalue())

        self.assertTrue(payload["correct"])
        self.assertTrue(
            all(result["submission_source"] == "assembly-dir" for result in payload["results"])
        )

    def test_assembly_dir_can_override_one_challenge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assembly_dir = Path(temp_dir)
            experiment = get_experiment("factorial")
            assembly = CStyleCompiler().compile(experiment.source).assembly
            assembly_dir.joinpath("factorial.epu").write_text(assembly, encoding="utf-8")

            result = run_challenge("factorial", assembly_dir=assembly_dir)

        self.assertTrue(result.correct)
        self.assertEqual(result.submission_source, "assembly-dir")
        self.assertEqual(result.language, "asm")

    def test_assembly_dir_partial_suite_falls_back_to_official_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assembly_dir = Path(temp_dir)
            experiment = get_experiment("factorial")
            assembly_dir.joinpath("factorial.epu").write_text(
                CStyleCompiler().compile(experiment.source).assembly,
                encoding="utf-8",
            )

            results = run_official_suite(assembly_dir=assembly_dir)
            summary = summarize_suite(results)

        self.assertEqual([result.slug for result in results], list(OFFICIAL_CHALLENGE_SLUGS))
        self.assertTrue(summary["correct"])
        self.assertEqual(summary["total_score"], 373.1)
        self.assertEqual(results[0].submission_source, "assembly-dir")
        self.assertTrue(all(result.submission_source == "official" for result in results[1:]))

    def test_cli_assembly_dir_preserves_max_steps_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assembly_dir = Path(temp_dir)
            assembly_dir.joinpath("e-ladder.epu").write_text(
                "loop:\nEJMP loop\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "challenge",
                        "e-ladder",
                        "--assembly-dir",
                        str(assembly_dir),
                        "--max-steps",
                        "3",
                        "--json",
                    ]
                )

        self.assertEqual(code, 1)
        self.assertIn("error:", stderr.getvalue())

    def test_cli_assembly_dir_reports_missing_directory(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            code = main(["challenge", "--assembly-dir", "missing-generated-assembly", "--json"])

        self.assertEqual(code, 1)
        self.assertIn("assembly-dir is not a directory", stderr.getvalue())

    def test_cli_leaderboard_ranks_challenge_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = summarize_suite(run_official_suite())
            baseline = Path(temp_dir) / "baseline.json"
            broken = Path(temp_dir) / "broken.json"
            baseline.write_text(json.dumps(payload), encoding="utf-8")
            broken_payload = dict(payload)
            broken_payload["total_score"] = 1
            broken.write_text(json.dumps(broken_payload), encoding="utf-8")

            entries = load_leaderboard([broken, baseline])
            self.assertEqual(entries[0].participant, "baseline")
            self.assertTrue(entries[0].valid)
            self.assertFalse(entries[1].valid)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["leaderboard", str(baseline), str(broken)]), 1)
            text = stdout.getvalue()
            self.assertIn("| Rank | Suite | Participant |", text)
            self.assertIn("baseline", text)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["leaderboard", str(baseline), "--json"]), 0)
            ranked = json.loads(stdout.getvalue())
            self.assertEqual(ranked["entries"][0]["participant"], "baseline")

    def test_leaderboard_expands_globs_and_marks_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = summarize_suite(run_official_suite())
            first = Path(temp_dir) / "first.json"
            second = Path(temp_dir) / "second.json"
            first.write_text(json.dumps({"participant": "first", **payload}), encoding="utf-8")
            second.write_text(json.dumps({"participant": "second", **payload}), encoding="utf-8")

            paths = expand_submission_paths([Path(temp_dir) / "*.json"])
            self.assertEqual([path.name for path in paths], ["first.json", "second.json"])
            deduped = expand_submission_paths([Path(temp_dir) / "*.json", first])
            self.assertEqual([path.name for path in deduped], ["first.json", "second.json"])

            entries = load_leaderboard([Path(temp_dir) / "*.json", Path(temp_dir) / "missing.json"])
            self.assertEqual(len(entries), 3)
            self.assertTrue(entries[0].valid)
            self.assertFalse(entries[-1].valid)
            self.assertIn("cannot read file", entries[-1].issues[0])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["leaderboard", str(Path(temp_dir) / "missing.json")]), 1)
            self.assertIn("cannot read file", stdout.getvalue())

    def test_leaderboard_can_keep_best_submission_per_participant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = summarize_suite(run_official_suite())
            better = Path(temp_dir) / "alice-better.json"
            worse = Path(temp_dir) / "alice-worse.json"
            worse_payload = dict(payload)
            worse_payload["participant"] = "alice"
            worse_payload["results"] = list(payload["results"])
            worse_payload["results"][0] = dict(worse_payload["results"][0])
            worse_payload["results"][0]["score"] = dict(worse_payload["results"][0]["score"])
            worse_payload["results"][0]["score"]["score"] += 10
            worse_payload["total_score"] += 10
            better.write_text(json.dumps({"participant": "alice", **payload}), encoding="utf-8")
            worse.write_text(json.dumps(worse_payload), encoding="utf-8")

            entries = load_leaderboard([worse, better], best_per_participant=True)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].source, str(better))

            kept = select_best_per_participant(load_leaderboard([worse, better]))
            self.assertEqual(len(kept), 1)

    def test_cli_spec_outputs_instruction_reference(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["spec", "--json"]), 0)

        payload = json.loads(stdout.getvalue())
        opcodes = {instruction["opcode"] for instruction in payload["instructions"]}
        self.assertIn("EQUANT", opcodes)
        self.assertIn("EPRINT", opcodes)
        self.assertIn("EJGTZ", opcodes)
        self.assertEqual(payload["partition_steps"], [3, 9, 27, 81, 243])


class ChallengeTests(unittest.TestCase):
    def test_official_challenges_are_correct_and_scored(self) -> None:
        results = run_official_suite()
        summary = summarize_suite(results)

        self.assertTrue(summary["correct"])
        self.assertGreater(summary["total_score"], 0)
        self.assertGreaterEqual(len(results), 5)
        self.assertEqual(
            [result.slug for result in results],
            list(OFFICIAL_CHALLENGE_SLUGS),
        )
        self.assertEqual(set(EXPECTED_OUTPUTS), set(OFFICIAL_CHALLENGE_SLUGS))

    def test_thermal_challenge_records_degradation(self) -> None:
        result = run_challenge("thermal-degrade")

        self.assertTrue(result.correct)
        self.assertGreaterEqual(result.score.degraded_events, 1)

    def test_numerical_challenges_are_correct_and_expose_error_metrics(self) -> None:
        results = run_numerical_suite()
        summary = summarize_numerical_suite(results)

        self.assertTrue(summary["correct"])
        self.assertEqual([result.slug for result in results], list(NUMERICAL_CHALLENGE_SLUGS))
        self.assertGreater(summary["performance_score"], 0)
        self.assertGreater(summary["mean_accuracy_digits"], 8)


class SpecTests(unittest.TestCase):
    def test_spec_payload_covers_public_instruction_surface(self) -> None:
        payload = spec_payload()
        opcodes = {instruction["opcode"] for instruction in payload["instructions"]}
        expected = {
            "ECONST",
            "EDIGITS",
            "EMOV",
            "EADD",
            "ESUB",
            "EMUL",
            "ESHIFT",
            "EALLOC",
            "ELOAD",
            "ESTORE",
            "EQOS",
            "EQUANT",
            "EOBS",
            "EPRINT",
            "EJMP",
            "EHALT",
        }

        self.assertTrue(expected.issubset(opcodes))
        self.assertEqual(payload["registers"], {"ER": 16, "EP": 8})


class WebPayloadTests(unittest.TestCase):
    def test_packaged_playground_assets_are_available(self) -> None:
        index = playground_asset_path("index.html")
        script = playground_asset_path("app.js")
        static_runtime = playground_asset_path("static-runtime.js")
        styles = playground_asset_path("styles.css")
        packaged_index = resources.files("e_base_computer_web").joinpath(
            "playground", "index.html"
        )

        self.assertTrue(index.exists())
        self.assertTrue(script.exists())
        self.assertTrue(static_runtime.exists())
        self.assertTrue(styles.exists())
        self.assertTrue(packaged_index.is_file())
        self.assertIn("E Digit Ladder", index.read_text(encoding="utf-8"))

    def test_source_and_packaged_assets_stay_in_sync(self) -> None:
        source_root = ROOT / "web" / "playground"
        package_root = ROOT / "src" / "e_base_computer_web" / "playground"

        for name in ("index.html", "app.js", "static-runtime.js", "styles.css"):
            self.assertEqual(
                (source_root / name).read_text(encoding="utf-8"),
                (package_root / name).read_text(encoding="utf-8"),
                name,
            )

    def test_run_payload_compiles_and_returns_timeline(self) -> None:
        payload, status = run_payload(
            {
                "source": "let x = 5; print(x);",
                "language": "c",
                "precision": 8,
                "maxSteps": 1000,
            }
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["output"], {"OUT0": 5.0})
        self.assertIn("timeline", payload)
        self.assertIn("score", payload)

    def test_samples_payload_shape(self) -> None:
        payload = samples_payload()
        samples = payload["samples"]

        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(len(samples), 4)
        self.assertTrue(all(sample["slug"] and sample["source"] for sample in samples))

    def test_challenge_payload_shape(self) -> None:
        payload = challenge_payload()

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["correct"])
        self.assertEqual(payload["total_score"], 373.1)
        self.assertEqual(len(payload["results"]), len(OFFICIAL_CHALLENGE_SLUGS))

        single = challenge_payload("thermal-degrade")
        self.assertTrue(single["ok"])
        self.assertTrue(single["challenge"]["correct"])
        self.assertEqual(single["challenge"]["slug"], "thermal-degrade")

        numerical = challenge_payload(suite="numerical")
        self.assertTrue(numerical["ok"])
        self.assertEqual(numerical["suite"], "numerical")
        self.assertEqual(len(numerical["results"]), len(NUMERICAL_CHALLENGE_SLUGS))

    def test_run_payload_reports_compile_error(self) -> None:
        payload, status = run_payload({"source": "x = 1;", "language": "c"})

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_run_payload_rejects_malformed_input_without_raising(self) -> None:
        cases = (
            [],
            {"source": "print(1);", "precision": "not-a-number"},
            {"source": "print(1);", "maxSteps": "not-a-number"},
            {"source": ["print(1);"]},
            {"source": "x" * 100_001},
            {"source": "print(1);", "precision": 13},
            {"source": "print(1);", "maxSteps": 0},
        )

        for request in cases:
            with self.subTest(request=request):
                payload, status = run_payload(request)
                self.assertIn(status, {400, 413})
                self.assertFalse(payload["ok"])

    def test_run_payload_rejects_numeric_overflow_and_deep_nesting(self) -> None:
        cases = (
            {"source": "print(1e999);"},
            {"source": "print(" + "(" * 1500 + "1" + ")" * 1500 + ");"},
        )

        for request in cases:
            with self.subTest(source=request["source"][:20]):
                payload, status = run_payload(request)
                self.assertEqual(status, 400)
                self.assertFalse(payload["ok"])


class WebHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PlaygroundHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_invalid_json_and_request_values_return_client_errors(self) -> None:
        cases = (
            b"{",
            json.dumps({"source": "print(1);", "precision": "not-a-number"}).encode(),
        )

        for body in cases:
            with self.subTest(body=body[:20]):
                connection = HTTPConnection(*self.server.server_address)
                connection.request(
                    "POST",
                    "/api/run",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                payload = json.loads(response.read())
                connection.close()

                self.assertEqual(response.status, 400)
                self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
