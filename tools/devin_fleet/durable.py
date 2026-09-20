"""Crash-resilient driver receipts, not a substitute for backups or an OS sandbox.

Callers must serialize writers (the fleet's process lock does this). File fsync and
same-directory replacement limit torn checkpoints; Windows does not expose a
portable directory fsync and storage hardware may still lose writes on power loss.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid


class RecoveryError(RuntimeError):
    """Evidence is absent, inconsistent, or ambiguous; require human inspection."""


def _replace(source, destination, attempts=6):
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            retryable = (getattr(exc, "winerror", None) in (5, 32, 33)
                         or exc.errno in (errno.EACCES, errno.EBUSY))
            if not retryable or attempt == attempts - 1:
                raise
            time.sleep(min(0.05 * 2 ** attempt, 0.4))


def _sync_directory(directory):
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_bytes(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path, value):
    # Serialize before touching the old checkpoint; forbid non-standard NaN/Infinity.
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _atomic_bytes(path, payload)


def _valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def validate_state(value):
    if not isinstance(value, dict):
        raise RecoveryError("State must be an object")
    if type(value.get("round")) is not int or value["round"] < 0:
        raise RecoveryError("State round must be a nonnegative integer")
    if value.get("status") not in {"ready", "running", "checkpoint", "stopped", "paused", "recovering", "drained"}:
        raise RecoveryError("Unknown state status")
    for field in ("candidates", "reports", "sessions"):
        if not isinstance(value.get(field), dict):
            raise RecoveryError("Missing or invalid state " + field)
    if any(not isinstance(role, str) or not role or not isinstance(session, str) or not session
           for role, session in value["sessions"].items()):
        raise RecoveryError("Invalid session map")
    if any(not isinstance(role, str) or not isinstance(report, dict)
           for role, report in value["reports"].items()):
        raise RecoveryError("Invalid report map")
    for commit, candidate in value["candidates"].items():
        if (not _valid_hash(commit) or not isinstance(candidate, dict)
                or not isinstance(candidate.get("role"), str) or not candidate["role"]
                or candidate.get("status") not in {"pending", "integrated", "rejected", "needs_rework", "superseded"}
                or ("base" in candidate and not _valid_hash(candidate["base"]))):
            raise RecoveryError("Invalid candidate receipt")
    for field in ("missions", "checkpoints", "last_decision", "blocked_roles"):
        if field in value and not isinstance(value[field], dict):
            raise RecoveryError("Invalid state " + field)
    return value


def _load_valid(path, validator):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"),
                           parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        validator(value)
        return value
    except (OSError, UnicodeError, ValueError, TypeError, RecoveryError) as exc:
        raise RecoveryError(f"Invalid checkpoint {path}: {exc}") from exc


def _backup_path(path):
    return Path(str(path) + ".bak")


def write_state(path, state, validator=validate_state):
    """Save current valid state as backup before installing the next checkpoint.

    An invalid primary is never overwritten here: call read_state for explicit
    recovery first. This avoids replacing a useful backup with corrupt bytes.
    """
    path = Path(path)
    validator(state)
    if path.exists():
        old = _load_valid(path, validator)
        atomic_write_json(_backup_path(path), old)
    atomic_write_json(path, state)
    if not _backup_path(path).exists():
        atomic_write_json(_backup_path(path), state)


def read_state(path, validator=validate_state):
    """Recover only a schema-valid backup; leave unique corrupt evidence intact.

    Recovery is observable through the returned state's recovery metadata and
    preserved evidence file. Both invalid files cause a fail-closed exception.
    """
    path = Path(path)
    try:
        return _load_valid(path, validator)
    except RecoveryError as original:
        try:
            recovered = _load_valid(_backup_path(path), validator)
        except RecoveryError as backup_error:
            raise RecoveryError(f"Primary and backup unavailable; no automatic reset. {original}; {backup_error}") from original
        evidence = None
        if path.exists():
            evidence = Path(str(path) + ".corrupt-" + uuid.uuid4().hex)
            # Copy bytes durably rather than rename: the primary remains present
            # until the recovered checkpoint has been atomically installed.
            _atomic_bytes(evidence, path.read_bytes())
        recovered["recovery"] = {"source": str(_backup_path(path)),
                                 "corrupt_evidence": str(evidence) if evidence else None,
                                 "reason": str(original)}
        validator(recovered)
        atomic_write_json(path, recovered)
        return recovered


def validate_integration_journal(value):
    if (not isinstance(value, dict) or value.get("version") != 1
            or value.get("phase") not in {"validated", "applied", "complete"}
            or not _valid_hash(value.get("before")) or not _valid_hash(value.get("target"))
            or value["before"] == value["target"]
            or type(value.get("round")) is not int or value["round"] < 0
            or not isinstance(value.get("selected"), list) or not value["selected"]
            or any(not _valid_hash(commit) for commit in value["selected"])
            or len(set(value["selected"])) != len(value["selected"])
            or not isinstance(value.get("validation_log"), str)
            or not Path(value["validation_log"]).is_absolute()
            or not isinstance(value.get("validation_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["validation_sha256"]) is None):
        raise RecoveryError("Invalid integration journal")
    return value


def write_integration_journal(path, before, target, selected, round_number, validation_log):
    """Record a tested target BEFORE updating the integration ref.

    An unfinished transaction must be reconciled, never replaced by a later gate.
    validation_log must already be durably saved by the caller.
    """
    path = Path(path)
    if path.exists() and _load_valid(path, validate_integration_journal)["phase"] != "complete":
        raise RecoveryError("Unfinished integration journal must be recovered first")
    validation_log = Path(validation_log).resolve()
    record = {"version": 1, "phase": "validated", "round": round_number,
              "before": before, "target": target, "selected": list(selected),
              "validation_log": str(validation_log),
              "validation_sha256": hashlib.sha256(validation_log.read_bytes()).hexdigest()}
    validate_integration_journal(record)
    atomic_write_json(path, record)
    return record


def integration_recovery(path, current_head, worktree_clean):
    """Plan ref-safe recovery; never modify Git or infer acceptance from ancestry.

    apply: HEAD is before; caller may reapply exact tested target after verifying
    ancestry. finalize: HEAD is target; update candidate states without rerunning
    models or merging again. complete: prior receipt is finished, no action.
    """
    path = Path(path)
    if not path.exists():
        return None
    record = _load_valid(path, validate_integration_journal)
    if record["phase"] == "complete":
        return {"action": "complete", "journal": record}
    if not worktree_clean:
        raise RecoveryError("Integration worktree is dirty; preserve and inspect before recovery")
    try:
        digest = hashlib.sha256(Path(record["validation_log"]).read_bytes()).hexdigest()
    except OSError as exc:
        raise RecoveryError("Integration validation evidence is unavailable") from exc
    if digest != record["validation_sha256"]:
        raise RecoveryError("Integration validation evidence changed")
    if current_head == record["target"]:
        return {"action": "finalize", "journal": record}
    if current_head == record["before"] and record["phase"] == "validated":
        return {"action": "apply", "journal": record}
    raise RecoveryError("Integration HEAD disagrees with journal; refusing automatic ref changes")


def advance_integration_journal(path, phase):
    record = _load_valid(path, validate_integration_journal)
    if (record["phase"], phase) not in {("validated", "applied"), ("applied", "complete")}:
        raise RecoveryError("Invalid integration journal transition")
    record["phase"] = phase
    atomic_write_json(path, record)
    return record
