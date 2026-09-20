"""Live, opt-in repository transport check with synthetic guest data only."""
from pathlib import Path
import tempfile
import uuid

from process_control import GlobalLock
from sandbox_control import SandboxController
from sandbox_repository import GuestRepository, GuestRepositoryError


def main():
    with GlobalLock(), tempfile.TemporaryDirectory(prefix="e-base-repo-smoke-") as work:
        root = Path(work)
        controller = SandboxController("e-base-machine", root / "STOP",
            sandbox_id="40e32a36-d565-4853-a841-fa3bea9ac648")
        controller.resume()
        guest_root = "/home/agent/workspace/repo-probe-" + uuid.uuid4().hex
        try:
            result = controller.execute(["mkdir", guest_root],
                cwd="/home/agent/workspace", log_path=root / "mkdir.log", timeout=30)
            assert result.returncode == 0
            repo = GuestRepository(controller, guest_root, root / "operations")
            repo.git("init", "--quiet")
            assert repo.git("rev-parse", "--is-inside-work-tree").strip() == "true"
            repo.write_bytes("context.json", b'{"probe":1}\n')
            assert repo.read_bytes("context.json") == b'{"probe":1}\n'
            repo.write_bytes("context.json", b'{"probe":2}\n')
            assert repo.read_bytes("context.json") == b'{"probe":2}\n'
            repo.write_bytes("empty", b'')
            assert repo.read_bytes("empty") == b''
            binary = bytes(range(256)) * 128
            repo.write_bytes("binary", binary)
            assert repo.read_bytes("binary") == binary
            result = controller.execute(["ln", guest_root + "/context.json", guest_root + "/old-link"],
                cwd=guest_root, log_path=root / "hardlink.log", timeout=30)
            assert result.returncode == 0
            repo.write_bytes("context.json", b'{"probe":3}\n')
            assert repo.read_bytes("old-link") == b'{"probe":2}\n'
            assert repo.git("-c", "alias.mode=!stat -c %a context.json", "mode").strip() == "600"
            # Git may execute helpers; demonstrate that even such execution
            # observes the inner VM kernel, not the WSL controller kernel.
            guest_kernel = repo.git("-c", "alias.probe=!uname -r", "probe").strip()
            import platform
            assert guest_kernel and guest_kernel != platform.release()
            marker = GuestRepository(controller, "/home/agent/workspace", root / "marker")
            assert marker.read_bytes("sandbox-persistence-probe.txt", max_bytes=1024) == (
                b"E-base sandbox acceptance marker v1. Non-secret test data.\n")
            try:
                marker.read_bytes("../outside", max_bytes=1024)
            except ValueError:
                pass
            else:
                raise AssertionError("Traversal not rejected")
            for command, relative in ((["ln", "-s", "/etc/os-release", guest_root + "/link"], "link"),
                                      (["mkfifo", guest_root + "/pipe"], "pipe")):
                result = controller.execute(command, cwd=guest_root,
                    log_path=root / (relative + ".log"), timeout=30)
                assert result.returncode == 0
                try:
                    repo.read_bytes(relative, max_bytes=1024)
                except GuestRepositoryError:
                    assert controller.fenced
                else:
                    raise AssertionError("Non-regular or symlink read accepted")
                controller.resume()
                try:
                    repo.write_bytes(relative, b"must not replace special files")
                except GuestRepositoryError:
                    assert controller.fenced
                else:
                    raise AssertionError("Special file write accepted")
                controller.resume()
            print("repository_live_smoke_passed: Git/helper, read/write/replace, empty file, traversal/symlink/FIFO refusal")
        finally:
            controller.stop()


if __name__ == "__main__":
    main()
