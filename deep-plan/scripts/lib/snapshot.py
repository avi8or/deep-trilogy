"""Snapshot module for session state persistence.

Provides atomic read, write, and validate operations for snapshot JSON files.
Used by both deep-plan and deep-implement for fast resume after /clear or compaction.
"""

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_VERSION = 1
LOCK_FILENAME = "snapshot.lock"

_DEFAULT_SNAPSHOT = {
    "version": SNAPSHOT_VERSION,
    "plugin": "",
    "session_id": "",
    "updated_at": "",
    "resume_step": 0,
    "resume_step_name": "",
    "completed_artifacts": [],
    "section_progress": None,
    "task_summary": {"total": 0, "completed": 0, "current_task_id": ""},
    "git_branch": "",
    "key_decisions": [],
    "env_validation": None,
    "hook_errors": [],
}


def _lock_path(snapshot_path: str) -> str:
    """Return the lock file path for a given snapshot path."""
    return os.path.join(os.path.dirname(snapshot_path), LOCK_FILENAME)


def _validate_artifact_paths(paths: list[str]) -> None:
    """Raise ValueError if any artifact path is unsafe."""
    for p in paths:
        if ".." in Path(p).parts:
            raise ValueError(f"Path contains '..': {p}")
        if os.path.isabs(p):
            raise ValueError(f"Path is absolute: {p}")


def _sanitize_artifact_paths(paths: list[str]) -> list[str]:
    """Strip unsafe paths silently (for read path)."""
    safe = []
    for p in paths:
        if ".." in Path(p).parts:
            continue
        if os.path.isabs(p):
            continue
        safe.append(p)
    return safe


def _atomic_write(snapshot_path: str, data: dict) -> None:
    """Write data to snapshot_path atomically using tmp+rename."""
    dir_path = os.path.dirname(snapshot_path)
    os.makedirs(dir_path, exist_ok=True)

    # Validate artifact paths before writing
    artifacts = data.get("completed_artifacts", [])
    if artifacts:
        _validate_artifact_paths(artifacts)

    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd = tempfile.NamedTemporaryFile(
            mode="w", dir=dir_path, suffix=".tmp", delete=False
        )
        tmp_path = tmp_fd.name
        json.dump(data, tmp_fd, indent=2)
        tmp_fd.flush()
        os.fsync(tmp_fd.fileno())
        tmp_fd.close()
        tmp_fd = None
        os.replace(tmp_path, snapshot_path)
        tmp_path = None
    finally:
        if tmp_fd is not None:
            tmp_fd.close()
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _with_lock(snapshot_path: str, fn):
    """Execute fn while holding an exclusive flock on the snapshot lock file."""
    dir_path = os.path.dirname(snapshot_path)
    os.makedirs(dir_path, exist_ok=True)
    lock_file = _lock_path(snapshot_path)

    lock_fd = open(lock_file, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        lock_fd.close()


def write_snapshot(snapshot_path: str, data: dict) -> None:
    """Atomic write with fcntl.flock.

    Validates artifact paths, acquires exclusive lock, writes atomically.
    """
    def do_write():
        _atomic_write(snapshot_path, data)

    _with_lock(snapshot_path, do_write)


def read_snapshot(snapshot_path: str) -> dict | None:
    """Read and parse snapshot. Returns None if missing or corrupt."""
    try:
        with open(snapshot_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    if "completed_artifacts" in data and isinstance(data["completed_artifacts"], list):
        data["completed_artifacts"] = _sanitize_artifact_paths(
            data["completed_artifacts"]
        )

    return data


def validate_snapshot(snapshot: dict, planning_dir: str) -> bool:
    """Verify snapshot is current against disk state."""
    if snapshot.get("version") != SNAPSHOT_VERSION:
        return False

    artifacts = snapshot.get("completed_artifacts", [])
    if not artifacts:
        return True

    try:
        updated_at = datetime.fromisoformat(snapshot["updated_at"])
        # Ensure timezone-aware for comparison
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return False

    for rel_path in artifacts:
        full_path = os.path.join(planning_dir, rel_path)
        if not os.path.exists(full_path):
            return False
        mtime = os.path.getmtime(full_path)
        file_time = datetime.fromtimestamp(mtime, tz=timezone.utc)
        if file_time > updated_at:
            return False

    return True


def update_snapshot_field(snapshot_path: str, **fields) -> None:
    """Read-modify-write with locking. Always updates updated_at to now."""
    def do_update():
        existing = None
        try:
            with open(snapshot_path) as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        if existing is None or not isinstance(existing, dict):
            existing = dict(_DEFAULT_SNAPSHOT)

        existing.update(fields)
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(snapshot_path, existing)

    _with_lock(snapshot_path, do_update)


def append_hook_error(
    snapshot_path: str, hook: str, error: str, artifact: str
) -> None:
    """Append error entry to hook_errors list with locking."""
    def do_append():
        existing = None
        try:
            with open(snapshot_path) as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = None

        if not isinstance(existing, dict):
            existing = dict(_DEFAULT_SNAPSHOT)

        errors = existing.get("hook_errors", [])
        errors.append({
            "hook": hook,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "artifact": artifact,
        })
        existing["hook_errors"] = errors
        _atomic_write(snapshot_path, existing)

    _with_lock(snapshot_path, do_append)


def clear_hook_errors(snapshot_path: str) -> None:
    """Set hook_errors to empty list. Lock -> read -> modify -> write -> unlock."""
    update_snapshot_field(snapshot_path, hook_errors=[])


def format_resume_context(snapshot: dict, snapshot_path: str = "") -> dict[str, str]:
    """Format snapshot into key=value pairs for additionalContext output."""
    result = {
        "DEEP_SESSION_ID": snapshot.get("session_id", ""),
        "DEEP_RESUME_STEP": str(snapshot.get("resume_step", 0)),
        "DEEP_RESUME_NAME": snapshot.get("resume_step_name", ""),
        "DEEP_PLUGIN": snapshot.get("plugin", ""),
        "DEEP_BRANCH": snapshot.get("git_branch", ""),
    }

    if snapshot_path:
        result["DEEP_SNAPSHOT"] = snapshot_path

    # Build progress string
    task = snapshot.get("task_summary") or {}
    section = snapshot.get("section_progress")
    parts = []
    if task.get("total"):
        parts.append(f"{task.get('completed', 0)}/{task['total']} tasks")
    if section and section.get("total"):
        parts.append(f"{section.get('completed', 0)}/{section['total']} sections")
    if parts:
        result["DEEP_PROGRESS"] = ", ".join(parts)

    # Key decisions (last 5)
    decisions = snapshot.get("key_decisions", [])
    if decisions:
        last_5 = decisions[-5:]
        result["DEEP_KEY_DECISIONS"] = "; ".join(last_5)

    # Hook errors (last 3)
    errors = snapshot.get("hook_errors", [])
    if errors:
        last_3 = errors[-3:]
        warnings = [f"[{e['hook']}] {e['error']}" for e in last_3]
        result["DEEP_HOOK_WARNING"] = " | ".join(warnings)

    return result
