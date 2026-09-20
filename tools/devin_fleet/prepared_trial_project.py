"""Prepare one immutable, inert Git input for a future full-turn trial.

This module does not activate production, register a turn, or run project code.
It only creates and independently inspects a controller-owned input artifact.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from process_control import global_lock_held
from production_registration_candidate import ROOT
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _directory, _file


ARTIFACT = ROOT / "production-candidate-trial-project-v1"
PROJECT = ARTIFACT / "project"
BUNDLE = ARTIFACT / "parent.bundle"
MANIFEST = ARTIFACT / "manifest.json"
PARENT_REF = "refs/heads/main"
ROLE_ENTRY = {
    "title": "Fixed inert arithmetic repair",
    "mission": "Repair the bounded add function without changing its test.",
    "paths": ["add.py"],
    "first_task": "Fix add.py so add(2, 3) returns 5. Do not change the test.",
}
TRIAL_STATE = {
    "round": 0,
    "status": "ready",
    "candidates": {},
    "reports": {},
    "sessions": {},
    "missions": {"machine": ROLE_ENTRY["first_task"]},
    "integration_error": None,
    "integration_commit": None,
    "blocked_roles": {},
    "shared_notes": {},
}
TRIAL_SETTINGS = {"turn_timeout_seconds": 300}
FILES = {
    "README.md": b"# Inert full-turn trial\n\nFix `add` and run the unit test.\n",
    "CHARTER.md": (
        b"# Fixed inert candidate trial\n\n"
        b"Change only add.py. Preserve test_add.py and all controller evidence.\n"
    ),
    "add.py": b"def add(left, right):\n    return left - right\n",
    "roles.json": (json.dumps({"machine": ROLE_ENTRY}, sort_keys=True,
                              separators=(",", ":")) + "\n").encode(),
    "test_add.py": (
        b"import unittest\n\nfrom add import add\n\n\n"
        b"class AddTests(unittest.TestCase):\n"
        b"    def test_adds_two_integers(self):\n"
        b"        self.assertEqual(add(2, 3), 5)\n\n\n"
        b"if __name__ == '__main__':\n    unittest.main()\n"
    ),
}
TASK_REQUEST = {
    "entry": ROLE_ENTRY,
    "state": TRIAL_STATE,
    "settings": TRIAL_SETTINGS,
}
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def _git(*arguments, cwd):
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "E Base Trial Controller",
        "GIT_AUTHOR_EMAIL": "trial-controller@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_NAME": "E Base Trial Controller",
        "GIT_COMMITTER_EMAIL": "trial-controller@example.invalid",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        "LC_ALL": "C",
    }
    completed = subprocess.run(["git", *arguments], cwd=cwd, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30, shell=False)
    if completed.returncode:
        raise RuntimeError("Fixed Git command failed")
    return completed.stdout.decode("ascii", "strict").strip()


def _exclusive(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _identity(path):
    info = path.lstat()
    return {"uid": info.st_uid, "gid": info.st_gid,
            "mode": stat.S_IMODE(info.st_mode)}


def _assert_plain(path, *, directory=False):
    if path.is_symlink():
        raise ValueError("Symbolic links are forbidden in trial artifact")
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise ValueError("Unexpected trial artifact file type")
    if os.name != "nt":
        wanted = 0o700 if directory else 0o600
        if stat.S_IMODE(info.st_mode) != wanted:
            raise ValueError("Private trial artifact mode required")
    return info


def _reject_links(root):
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in directories + filenames:
            if (Path(current) / name).is_symlink():
                raise ValueError("Symbolic links are forbidden in trial artifact")


def _inventory():
    result = []
    for name in sorted(FILES):
        raw = _file(PROJECT / name, 65536)
        result.append({"path": name, "bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest(),
                       "identity": _identity(PROJECT / name)})
    return result


def prepare():
    require_managed_namespace()
    if not global_lock_held("/tmp/e-base-devin-fleet-global.lock"):
        raise ValueError("Global controller lock required")
    _directory(ROOT)
    if ARTIFACT.parent != ROOT or ARTIFACT.resolve(strict=False).parent != ROOT.resolve():
        raise ValueError("Canonical controller artifact path required")
    ARTIFACT.mkdir(mode=0o700)
    _sync_directory(ROOT)
    PROJECT.mkdir(mode=0o700)
    _sync_directory(ARTIFACT)
    for name, raw in FILES.items():
        _exclusive(PROJECT / name, raw)
    # Never retain a mutable .git directory in the inspected artifact. Build the
    # parent in a fresh controller-owned temporary repository, then persist only
    # the bounded source bytes and immutable bundle.
    with tempfile.TemporaryDirectory(prefix="trial-parent-", dir=ROOT) as temporary:
        source = Path(temporary)
        for name, raw in FILES.items():
            (source / name).write_bytes(raw)
        _git("init", "--initial-branch=main", ".", cwd=source)
        _git("add", "--", *sorted(FILES), cwd=source)
        _git("commit", "--no-gpg-sign", "-m", "fixed inert full-turn trial parent", cwd=source)
        head = _git("rev-parse", "--verify", "HEAD", cwd=source)
        tree = _git("rev-parse", "--verify", "HEAD^{tree}", cwd=source)
        if not _HEX40.fullmatch(head) or not _HEX40.fullmatch(tree):
            raise RuntimeError("Unexpected Git object identity")
        temporary_bundle = source / "parent.bundle"
        _git("bundle", "create", str(temporary_bundle), PARENT_REF, cwd=source)
        _exclusive(BUNDLE, temporary_bundle.read_bytes())
    _sync_directory(ARTIFACT)
    bundle_raw = _file(BUNDLE, 16 * 1024 * 1024)
    manifest = {
        "schema": 1,
        "phase": "complete",
        "artifact": str(ARTIFACT),
        "project": str(PROJECT),
        "parent_ref": PARENT_REF,
        "head": head,
        "tree": tree,
        "bundle_sha256": hashlib.sha256(bundle_raw).hexdigest(),
        "bundle_bytes": len(bundle_raw),
        "files": _inventory(),
        "artifact_identity": _identity(ARTIFACT),
        "project_identity": _identity(PROJECT),
        "bundle_identity": _identity(BUNDLE),
        "task_request": TASK_REQUEST,
        "production_admitted": False,
        "activated": False,
        "model_executed": False,
    }
    _exclusive(MANIFEST, _canonical(manifest))
    return inspect()


def inspect():
    require_managed_namespace()
    if ARTIFACT.parent != ROOT or ARTIFACT.resolve(strict=False).parent != ROOT.resolve():
        raise ValueError("Canonical controller artifact path required")
    _assert_plain(ROOT, directory=True)
    _assert_plain(ARTIFACT, directory=True)
    if set(os.listdir(ARTIFACT)) != {"project", "parent.bundle", "manifest.json"}:
        raise ValueError("Exact trial artifact entries required")
    _assert_plain(PROJECT, directory=True)
    _assert_plain(BUNDLE)
    _assert_plain(MANIFEST)
    _reject_links(ARTIFACT)
    raw = _file(MANIFEST, 1048576)
    value = json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    keys = {"schema", "phase", "artifact", "project", "parent_ref", "head", "tree",
            "bundle_sha256", "bundle_bytes", "files", "artifact_identity",
            "project_identity", "bundle_identity", "task_request", "production_admitted",
            "activated", "model_executed"}
    if (type(value) is not dict or set(value) != keys or value.get("schema") != 1
            or value.get("phase") != "complete" or value.get("artifact") != str(ARTIFACT)
            or value.get("project") != str(PROJECT) or value.get("parent_ref") != PARENT_REF
            or not _HEX40.fullmatch(value.get("head", ""))
            or not _HEX40.fullmatch(value.get("tree", ""))
            or not _HEX64.fullmatch(value.get("bundle_sha256", ""))
            or type(value.get("bundle_bytes")) is not int
            or not 0 < value["bundle_bytes"] <= 16 * 1024 * 1024
            or value.get("task_request") != TASK_REQUEST
            or value.get("production_admitted") is not False
            or value.get("activated") is not False
            or value.get("model_executed") is not False):
        raise ValueError("Invalid prepared trial manifest")
    if raw != _canonical(value):
        raise ValueError("Canonical prepared trial manifest required")
    if (value["artifact_identity"] != _identity(ARTIFACT)
            or value["project_identity"] != _identity(PROJECT)
            or value["bundle_identity"] != _identity(BUNDLE)):
        raise ValueError("Trial artifact owner or mode changed")
    if set(os.listdir(PROJECT)) != set(FILES):
        raise ValueError("Exact trial project files required")
    if value.get("files") != _inventory():
        raise ValueError("Trial project content changed")
    bundle_raw = _file(BUNDLE, 16 * 1024 * 1024)
    if (len(bundle_raw) != value["bundle_bytes"]
            or hashlib.sha256(bundle_raw).hexdigest() != value["bundle_sha256"]):
        raise ValueError("Trial parent bundle changed")
    if _git("bundle", "list-heads", str(BUNDLE), cwd=ARTIFACT) != value["head"] + " " + PARENT_REF:
        raise ValueError("Trial parent bundle ref changed")
    return {"verified": True, "artifact": str(ARTIFACT), "project": str(PROJECT),
            "parent_ref": PARENT_REF, "head": value["head"], "tree": value["tree"],
            "bundle_sha256": value["bundle_sha256"], "task_request": TASK_REQUEST,
            "production_admitted": False, "activated": False, "model_executed": False}
