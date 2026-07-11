"""Build and smoke-test a wheel release in a fresh virtual environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    temp_name = tempfile.mkdtemp(prefix="ebase-smoke-")
    try:
        temp = Path(temp_name)
        dist = temp / "dist"
        venv = temp / "venv"
        installed_cwd = temp / "installed-cwd"
        installed_cwd.mkdir()
        run([sys.executable, "scripts/publication_audit.py"])
        run([sys.executable, "-m", "pip", "install", "-e", "."])
        run([sys.executable, "scripts/finalize_project_urls.py", "owner/repo"])
        run([sys.executable, "scripts/finalize_project_urls.py", "owner/repo", "--playground-url", "https://play.example.test/"])
        bundle = temp / "e-base-computer-source.zip"
        run([sys.executable, "scripts/make_release_bundle.py", "--output", str(bundle)])
        assert bundle.exists()
        starter_assembly_dir = temp / "starter-generated-assembly"
        run(
            [
                sys.executable,
                "examples/compiler_starter/emit_baseline_assembly.py",
                "--output",
                str(starter_assembly_dir),
            ]
        )
        starter_challenge = run_json(
            [
                sys.executable,
                "-m",
                "epu_cli",
                "challenge",
                "--assembly-dir",
                str(starter_assembly_dir),
                "--json",
            ]
        )
        assert starter_challenge["correct"]
        assert starter_challenge["total_score"] == 373.1
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
        if shutil.which("node"):
            run(["node", "scripts/static_playground_smoke.cjs"])
        run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist)])
        wheel = next(dist.glob("*.whl"))
        run([sys.executable, "-m", "venv", str(venv)])
        python = venv_python(venv)
        scripts = python.parent
        ebase = scripts / executable_name("ebase")
        playground = scripts / executable_name("ebase-playground")
        run([str(python), "-m", "pip", "install", str(wheel)])
        assert playground.exists()
        run([str(ebase), "samples"], cwd=installed_cwd)
        run([str(ebase), "samples", "thermal-degrade", "--run", "--json"], cwd=installed_cwd)
        challenge = run_json([str(ebase), "challenge", "--json"], cwd=installed_cwd)
        assert challenge["correct"]
        assert challenge["total_score"] == 373.1
        baseline = installed_cwd / "baseline_submission.json"
        baseline.write_text(
            json.dumps({"participant": "release-smoke-baseline", **challenge}, indent=2),
            encoding="utf-8",
        )
        second = installed_cwd / "baseline_submission_copy.json"
        second.write_text(baseline.read_text(encoding="utf-8"), encoding="utf-8")
        run([str(ebase), "challenge", "thermal-degrade", "--json"], cwd=installed_cwd)
        run([str(ebase), "leaderboard", str(baseline)], cwd=installed_cwd)
        run([str(ebase), "leaderboard", str(installed_cwd / "*.json")], cwd=installed_cwd)
        run([str(ebase), "leaderboard", str(installed_cwd / "*.json"), "--best-per-participant"], cwd=installed_cwd)
        run([str(ebase), "leaderboard", str(baseline), "--json"], cwd=installed_cwd)
        run([str(ebase), "spec", "--json"], cwd=installed_cwd)
        assembly_dir = installed_cwd / "generated-assembly"
        assembly_dir.mkdir()
        assembly_dir.joinpath("e-ladder.epu").write_text(
            "\n".join(
                [
                    "ECONST ER0, 12.5",
                    "ECONST ER1, 4.25",
                    "EMUL ER2, ER0, ER1",
                    "ENORM ER2",
                    "ESHIFT ER3, ER2, 1",
                    "EOBS OUT0, ER3 ; precision=8",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        run(
            [str(ebase), "challenge", "e-ladder", "--assembly-dir", str(assembly_dir), "--json"],
            cwd=installed_cwd,
        )
        program = installed_cwd / "factorial.cbase"
        program.write_text(
            "let n = 5;\nlet acc = 1;\nwhile (n > 1) { acc = acc * n; n = n - 1; }\nprint(acc);\n",
            encoding="utf-8",
        )
        run([str(ebase), "run", str(program), "--json"], cwd=installed_cwd)
        smoke_playground(python, installed_cwd)
    finally:
        try:
            shutil.rmtree(temp_name)
        except OSError as exc:
            if os.name != "nt":
                raise
            print(f"warning: could not remove temporary smoke directory: {exc}", file=sys.stderr)
    print("release_smoke_ok")
    return 0


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def run_json(command: list[str], cwd: Path = ROOT) -> dict[str, object]:
    print("+ " + " ".join(command))
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return json.loads(completed.stdout)


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def executable_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def smoke_playground(python: Path, cwd: Path) -> None:
    port = 8780
    process = subprocess.Popen(
        [str(python), "-m", "web_playground", "--port", str(port)],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(port)
        index = http_get(port, "/")
        assert "E Digit Ladder" in index
        assert "Copy Program Link" in index
        assert "static-runtime.js" in index
        static_runtime = http_get(port, "/static-runtime.js")
        assert "EBaseStaticRuntime" in static_runtime
        assert "runChallengeSuite" in static_runtime
        samples = json.loads(http_get(port, "/api/samples"))
        assert samples["ok"]
        assert any(sample["slug"] == "thermal-degrade" for sample in samples["samples"])
        challenge = json.loads(http_get(port, "/api/challenge"))
        assert challenge["ok"]
        assert challenge["correct"]
        assert challenge["total_score"] == 373.1
        thermal = json.loads(http_get(port, "/api/challenge?name=thermal-degrade"))
        assert thermal["ok"]
        assert thermal["challenge"]["slug"] == "thermal-degrade"
        response = json.loads(
            http_post(
                port,
                "/api/run",
                {
                    "source": "let x = 5; print(x);",
                    "language": "c",
                    "precision": 8,
                    "maxSteps": 1000,
                },
            )
        )
        assert response["ok"]
        assert response["output"] == {"OUT0": 5.0}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_for_server(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            http_get(port, "/")
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("playground server did not become ready")


def http_get(port: int, path: str) -> str:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.read().decode("utf-8")


def http_post(port: int, path: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
