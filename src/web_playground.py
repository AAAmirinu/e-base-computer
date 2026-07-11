"""Local web playground server for the E-base computer."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from cstyle_compiler import CStyleCompileError, CStyleCompiler
from emulator import EPUEmulator
from epu import EPUError
from epu_challenge import run_challenge, run_official_suite, summarize_suite
from epu_experiments import list_experiments
from epu_scoring import score_timeline


ROOT = Path(__file__).resolve().parents[1]
SOURCE_WEB_ROOT = ROOT / "web" / "playground"


def playground_asset_path(name: str) -> Path:
    """Return a playground asset path from source checkout or packaged data."""

    source_path = SOURCE_WEB_ROOT / name
    if source_path.exists():
        return source_path
    return Path(str(resources.files("e_base_computer_web").joinpath("playground", name)))


class PlaygroundHandler(BaseHTTPRequestHandler):
    server_version = "EBasePlayground/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(playground_asset_path("index.html"), "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send_file(playground_asset_path("app.js"), "text/javascript; charset=utf-8")
            return
        if parsed.path == "/static-runtime.js":
            self._send_file(playground_asset_path("static-runtime.js"), "text/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._send_file(playground_asset_path("styles.css"), "text/css; charset=utf-8")
            return
        if parsed.path == "/api/samples":
            self._send_json(samples_payload())
            return
        if parsed.path == "/api/challenge":
            query = parse_qs(parsed.query)
            name = query.get("name", [None])[0]
            try:
                self._send_json(challenge_payload(name))
            except (KeyError, ValueError, EPUError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            response, status = run_payload(request)
        except Exception as exc:  # pragma: no cover - last-resort HTTP safety net
            response, status = {"ok": False, "error": str(exc)}, 500
        self._send_json(response, status)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_payload(request: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    source = str(request.get("source", ""))
    language = str(request.get("language", "c"))
    precision = int(request.get("precision", 8))
    max_steps = int(request.get("maxSteps", 10_000))
    try:
        if language == "c":
            compiled = CStyleCompiler(precision=precision).compile(source)
            assembly = compiled.assembly
            symbols = compiled.symbols
        elif language == "asm":
            assembly = source
            symbols = {}
        else:
            return {"ok": False, "error": f"unknown language: {language}"}, 400
        emulator = EPUEmulator(max_steps=max_steps)
        result = emulator.run(assembly)
        timeline = emulator.epu.timeline()
        return {
            "ok": True,
            "assembly": assembly,
            "symbols": symbols,
            "output": result.output,
            "halted": result.halted,
            "steps": result.steps,
            "pc": result.pc,
            "score": score_timeline(timeline).to_dict(),
            "timeline": timeline,
            "snapshot": emulator.epu.visual_snapshot(),
        }, 200
    except (CStyleCompileError, EPUError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}, 400


def samples_payload() -> Dict[str, Any]:
    return {
        "ok": True,
        "samples": [experiment.to_dict() for experiment in list_experiments()],
    }


def challenge_payload(name: Optional[str] = None) -> Dict[str, Any]:
    if name:
        return {"ok": True, "challenge": run_challenge(name).to_dict()}
    summary = summarize_suite(run_official_suite())
    summary["ok"] = True
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ebase-playground")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    try:
        server = ThreadingHTTPServer((args.host, args.port), PlaygroundHandler)
    except OSError as exc:
        if exc.errno in {98, 10048}:
            print(
                f"error: {args.host}:{args.port} is already in use; try --port 8766",
                file=sys.stderr,
            )
            return 1
        print(f"error: cannot start playground: {exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[:2]
    print(f"E-base playground: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping playground")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
