"""Opt-in live transport smoke test; no model or project code is invoked."""
from pathlib import Path
import tempfile

from process_control import GlobalLock
from sandbox_control import SandboxController, SandboxFenced


def main():
    with GlobalLock(), tempfile.TemporaryDirectory(prefix="e-base-sbx-smoke-") as work:
        root = Path(work)
        controller = SandboxController("e-base-machine", root / "STOP",
            sandbox_id="40e32a36-d565-4853-a841-fa3bea9ac648")
        controller.resume()
        try:
            result = controller.execute(
                ["sha256sum", "/home/agent/workspace/sandbox-persistence-probe.txt"],
                cwd="/home/agent/workspace", log_path=root / "hash.log", timeout=30,
            )
            assert result.returncode == 0
            assert "e9764d24a789db2ddaba822680c310b3ce0c9917b5eaf5b77c63ca9cf1043d7d" in (
                root / "hash.log").read_text()
            try:
                controller.execute(["sleep", "120"], cwd="/home/agent/workspace",
                                   log_path=root / "timeout.log", timeout=2)
            except SandboxFenced:
                pass
            else:
                raise AssertionError("Expected timeout fence")
            assert controller.fenced and (root / "STOP").exists()
            try:
                controller.execute(["true"], cwd="/home/agent/workspace",
                                   log_path=root / "rejected.log", timeout=5)
            except SandboxFenced:
                pass
            else:
                raise AssertionError("Fenced call was admitted")
            assert not (root / "rejected.log").exists()
            print("live_smoke_passed: persistence, timeout stop, post-stop rejection")
        finally:
            controller.stop()


if __name__ == "__main__":
    main()
