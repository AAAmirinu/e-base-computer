import contextlib
import io
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu_challenge import (
    CHALLENGE_SCHEMA_VERSION,
    NUMERICAL_CHALLENGE_SLUGS,
    NUMERICAL_SCORING_MODEL,
    run_numerical_suite,
    summarize_numerical_suite,
)
from epu_cli import main
from epu_version import SOURCE_VERSION
from web_playground import (
    MAX_REQUEST_BYTES,
    PlaygroundHandler,
    challenge_payload,
    run_payload,
    samples_payload,
)


class PublicPlaygroundCompatibilityTests(unittest.TestCase):
    def test_cli_and_server_publish_the_release_version(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"ebase {SOURCE_VERSION}")
        self.assertEqual(PlaygroundHandler.server_version, f"EBasePlayground/{SOURCE_VERSION}")

    def test_public_sample_and_numerical_suite_surface_is_preserved(self) -> None:
        payload = samples_payload()
        slugs = [sample["slug"] for sample in payload["samples"]]

        self.assertTrue(payload["ok"])
        self.assertEqual(
            slugs[-3:],
            [
                "numerical-polynomial",
                "numerical-cancellation",
                "numerical-recurrence",
            ],
        )
        self.assertEqual(slugs[-3:], list(NUMERICAL_CHALLENGE_SLUGS))

        summary = summarize_numerical_suite(run_numerical_suite())
        self.assertTrue(summary["correct"])
        self.assertEqual(summary["challenge_schema_version"], CHALLENGE_SCHEMA_VERSION)
        self.assertEqual(summary["emulator_version"], SOURCE_VERSION)
        self.assertEqual(summary["scoring_model"], NUMERICAL_SCORING_MODEL)
        self.assertEqual(summary["total_score"], 302.304481)
        self.assertEqual(summary["performance_score"], 302.3)
        self.assertEqual(summary["mean_accuracy_digits"], 11.115)

    def test_challenge_api_preserves_suite_selector_and_errors(self) -> None:
        official = challenge_payload()
        numerical = challenge_payload(suite="numerical")

        self.assertEqual(official["suite"], "official")
        self.assertTrue(official["correct"])
        self.assertEqual(numerical["suite"], "numerical")
        self.assertTrue(numerical["correct"])
        self.assertEqual(
            [result["slug"] for result in numerical["results"]],
            list(NUMERICAL_CHALLENGE_SLUGS),
        )
        with self.assertRaisesRegex(ValueError, "unknown challenge suite"):
            challenge_payload(suite="missing")
        with self.assertRaisesRegex(ValueError, "named challenge"):
            challenge_payload("thermal-degrade", suite="numerical")

    def test_cli_numerical_suite_and_named_guard_are_preserved(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["challenge", "--suite", "numerical", "--json"])
        self.assertEqual(status, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["suite"], "numerical")
        self.assertTrue(payload["correct"])
        self.assertEqual(payload["total_score"], 302.304481)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status = main(["challenge", "thermal-degrade", "--suite", "numerical"])
        self.assertEqual(status, 1)
        self.assertIn("named challenge", stderr.getvalue())

    def test_run_payload_keeps_public_limits_and_high_layer_request(self) -> None:
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
            with self.subTest(request=type(request).__name__):
                payload, status = run_payload(request)
                self.assertIn(status, {400, 413})
                self.assertFalse(payload["ok"])

        payload, status = run_payload(
            {
                "source": "ECONST ER0, 1\nETEMP TEMP",
                "language": "asm",
                "precision": "8",
                "maxSteps": "100",
                "thermal_model": "coupled",
                "aging_model": "aging",
            }
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["models"]["thermal"]["model_id"], "coupled-v1")
        self.assertEqual(payload["models"]["aging"]["model_id"], "aging-v1")

    def test_numeric_overflow_and_deep_nesting_remain_client_errors(self) -> None:
        cases = (
            {"source": "print(1e999);"},
            {"source": "print(" + "(" * 1500 + "1" + ")" * 1500 + ");"},
        )
        for request in cases:
            with self.subTest(source=request["source"][:20]):
                payload, status = run_payload(request)
                self.assertEqual(status, 400)
                self.assertFalse(payload["ok"])


class PublicPlaygroundHttpHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PlaygroundHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def request(self, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
        connection = HTTPConnection(*self.server.server_address)
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_invalid_json_and_request_values_stay_on_client_error_path(self) -> None:
        for body in (
            b"{",
            json.dumps({"source": "print(1);", "precision": "not-a-number"}).encode(),
        ):
            with self.subTest(body=body[:20]):
                status, payload = self.request(
                    "/api/run",
                    body,
                    {"Content-Type": "application/json"},
                )
                self.assertEqual(status, 400)
                self.assertFalse(payload["ok"])

    def test_oversized_content_length_is_rejected_before_body_read(self) -> None:
        status, payload = self.request(
            "/api/run",
            b"",
            {
                "Content-Type": "application/json",
                "Content-Length": str(MAX_REQUEST_BYTES + 1),
            },
        )
        self.assertEqual(status, 413)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
