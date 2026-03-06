"""Tests for snapshot module."""

import fcntl
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.lib.snapshot import (
    append_hook_error,
    clear_hook_errors,
    format_resume_context,
    read_snapshot,
    update_snapshot_field,
    validate_snapshot,
    write_snapshot,
)


def _make_snapshot(**overrides):
    """Helper to build a valid snapshot dict with sensible defaults."""
    base = {
        "version": 1,
        "plugin": "deep-plan",
        "session_id": "test-session-123",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "resume_step": 3,
        "resume_step_name": "Read section file",
        "completed_artifacts": [],
        "section_progress": None,
        "task_summary": {"total": 10, "completed": 3, "current_task_id": "7"},
        "git_branch": "feature/test",
        "key_decisions": [],
        "env_validation": None,
        "hook_errors": [],
    }
    base.update(overrides)
    return base


class TestWriteSnapshot:
    def test_writes_valid_json_to_path(self, tmp_path):
        """write_snapshot writes a valid JSON file at the given path."""
        snap_path = str(tmp_path / "snapshot.json")
        data = _make_snapshot()
        write_snapshot(snap_path, data)

        with open(snap_path) as f:
            result = json.load(f)
        assert result["version"] == 1
        assert result["plugin"] == "deep-plan"

    def test_atomic_write_no_corrupt_file_on_partial(self, tmp_path):
        """If write fails mid-operation, no corrupt snapshot.json is left behind."""
        snap_path = str(tmp_path / "snapshot.json")
        data = _make_snapshot()

        # Write a valid snapshot first
        write_snapshot(snap_path, data)

        # Now simulate a failure during write by patching os.replace to raise
        with patch("scripts.lib.snapshot.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                write_snapshot(snap_path, _make_snapshot(resume_step=99))

        # Original file should still be valid
        with open(snap_path) as f:
            result = json.load(f)
        assert result["resume_step"] == 3  # Original value preserved

    def test_acquires_and_releases_flock(self, tmp_path):
        """write_snapshot acquires fcntl.flock on a .lock file before writing
        and releases it after."""
        snap_path = str(tmp_path / "snapshot.json")
        data = _make_snapshot()

        lock_calls = []
        original_flock = fcntl.flock

        def tracking_flock(fd, operation):
            lock_calls.append(operation)
            return original_flock(fd, operation)

        with patch("scripts.lib.snapshot.fcntl.flock", side_effect=tracking_flock):
            write_snapshot(snap_path, data)

        assert fcntl.LOCK_EX in lock_calls
        assert fcntl.LOCK_UN in lock_calls

    def test_creates_parent_directory(self, tmp_path):
        """write_snapshot creates parent directories if they don't exist."""
        snap_path = str(tmp_path / "nested" / "deep" / "snapshot.json")
        data = _make_snapshot()
        write_snapshot(snap_path, data)

        assert os.path.exists(snap_path)

    def test_rejects_dotdot_in_completed_artifacts(self, tmp_path):
        """Paths containing '..' in completed_artifacts are rejected."""
        snap_path = str(tmp_path / "snapshot.json")
        data = _make_snapshot(completed_artifacts=["../etc/passwd", "valid.md"])

        with pytest.raises(ValueError, match="\\.\\."):
            write_snapshot(snap_path, data)

    def test_rejects_absolute_paths_in_completed_artifacts(self, tmp_path):
        """Absolute paths in completed_artifacts are rejected."""
        snap_path = str(tmp_path / "snapshot.json")
        data = _make_snapshot(completed_artifacts=["/etc/passwd", "valid.md"])

        with pytest.raises(ValueError, match="absolute"):
            write_snapshot(snap_path, data)


class TestReadSnapshot:
    def test_reads_valid_snapshot(self, tmp_path):
        """read_snapshot returns parsed dict for a valid snapshot JSON file."""
        snap_path = str(tmp_path / "snapshot.json")
        data = _make_snapshot()
        write_snapshot(snap_path, data)

        result = read_snapshot(snap_path)
        assert isinstance(result, dict)
        assert result["version"] == 1

    def test_returns_none_for_missing_file(self, tmp_path):
        """read_snapshot returns None when the file does not exist."""
        result = read_snapshot(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_returns_none_for_corrupt_json(self, tmp_path):
        """read_snapshot returns None for invalid/corrupt JSON content."""
        snap_path = tmp_path / "snapshot.json"
        snap_path.write_text("{ not valid json !!!")
        assert read_snapshot(str(snap_path)) is None

    def test_returns_none_for_non_dict_json(self, tmp_path):
        """read_snapshot returns None when JSON parses to non-dict."""
        snap_path = tmp_path / "snapshot.json"
        snap_path.write_text('["array", "not", "dict"]')
        assert read_snapshot(str(snap_path)) is None

    def test_sanitizes_dotdot_paths(self, tmp_path):
        """read_snapshot strips entries with '..' from completed_artifacts."""
        snap_path = tmp_path / "snapshot.json"
        data = _make_snapshot()
        data["completed_artifacts"] = ["valid.md", "../sneaky.txt", "also/valid.md"]
        snap_path.write_text(json.dumps(data))

        result = read_snapshot(str(snap_path))
        assert result is not None
        assert "../sneaky.txt" not in result["completed_artifacts"]
        assert "valid.md" in result["completed_artifacts"]
        assert "also/valid.md" in result["completed_artifacts"]


class TestValidateSnapshot:
    def test_returns_true_when_all_artifacts_exist(self, tmp_path):
        """Returns True when every path in completed_artifacts exists on disk."""
        planning_dir = str(tmp_path)
        (tmp_path / "file1.md").write_text("content")
        (tmp_path / "file2.md").write_text("content")

        # Set updated_at to future so artifacts are "older"
        updated_at = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        snapshot = _make_snapshot(
            completed_artifacts=["file1.md", "file2.md"],
            updated_at=updated_at,
        )
        assert validate_snapshot(snapshot, planning_dir) is True

    def test_returns_false_when_artifact_missing(self, tmp_path):
        """Returns False when any completed_artifact file is missing."""
        planning_dir = str(tmp_path)
        (tmp_path / "file1.md").write_text("content")

        updated_at = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        snapshot = _make_snapshot(
            completed_artifacts=["file1.md", "missing.md"],
            updated_at=updated_at,
        )
        assert validate_snapshot(snapshot, planning_dir) is False

    def test_returns_false_when_artifact_newer_than_snapshot(self, tmp_path):
        """Returns False when an artifact's mtime is newer than updated_at."""
        planning_dir = str(tmp_path)
        artifact = tmp_path / "file1.md"
        artifact.write_text("content")

        # Set updated_at to the past
        updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        snapshot = _make_snapshot(
            completed_artifacts=["file1.md"],
            updated_at=updated_at,
        )
        assert validate_snapshot(snapshot, planning_dir) is False

    def test_returns_true_when_artifact_mtime_equals_updated_at(self, tmp_path):
        """Returns True when artifact mtime exactly equals updated_at."""
        planning_dir = str(tmp_path)
        artifact = tmp_path / "file1.md"
        artifact.write_text("content")

        # Set updated_at to match the file's mtime
        mtime = os.path.getmtime(str(artifact))
        updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        snapshot = _make_snapshot(
            completed_artifacts=["file1.md"],
            updated_at=updated_at,
        )
        assert validate_snapshot(snapshot, planning_dir) is True

    def test_returns_true_for_empty_artifacts_list(self, tmp_path):
        """Returns True when completed_artifacts is an empty list."""
        snapshot = _make_snapshot(completed_artifacts=[])
        assert validate_snapshot(snapshot, str(tmp_path)) is True

    def test_returns_false_for_version_mismatch(self, tmp_path):
        """Returns False when snapshot version != 1."""
        snapshot = _make_snapshot(version=2, completed_artifacts=[])
        assert validate_snapshot(snapshot, str(tmp_path)) is False


class TestUpdateSnapshotField:
    def test_updates_single_field(self, tmp_path):
        """Updates one field in an existing snapshot file."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot(resume_step=1))

        update_snapshot_field(snap_path, resume_step=5)

        result = read_snapshot(snap_path)
        assert result["resume_step"] == 5

    def test_updates_multiple_fields_atomically(self, tmp_path):
        """Updates multiple fields in a single read-modify-write cycle."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot())

        update_snapshot_field(snap_path, resume_step=10, resume_step_name="New step")

        result = read_snapshot(snap_path)
        assert result["resume_step"] == 10
        assert result["resume_step_name"] == "New step"

    def test_acquires_flock_during_update(self, tmp_path):
        """Acquires fcntl.flock during the read-modify-write cycle."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot())

        lock_calls = []
        original_flock = fcntl.flock

        def tracking_flock(fd, operation):
            lock_calls.append(operation)
            return original_flock(fd, operation)

        with patch("scripts.lib.snapshot.fcntl.flock", side_effect=tracking_flock):
            update_snapshot_field(snap_path, resume_step=5)

        assert fcntl.LOCK_EX in lock_calls
        assert fcntl.LOCK_UN in lock_calls

    def test_creates_snapshot_if_missing(self, tmp_path):
        """Creates a new snapshot with defaults + provided fields if file doesn't exist."""
        snap_path = str(tmp_path / "snapshot.json")
        update_snapshot_field(snap_path, resume_step=1, plugin="deep-plan")

        result = read_snapshot(snap_path)
        assert result is not None
        assert result["resume_step"] == 1

    def test_preserves_existing_fields(self, tmp_path):
        """Fields not specified in the update are preserved as-is."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot(
            resume_step=3, git_branch="feature/test"
        ))

        update_snapshot_field(snap_path, resume_step=5)

        result = read_snapshot(snap_path)
        assert result["resume_step"] == 5
        assert result["git_branch"] == "feature/test"


class TestAppendHookError:
    def test_appends_to_empty_list(self, tmp_path):
        """Appends an error entry when hook_errors is empty."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot(hook_errors=[]))

        append_hook_error(snap_path, hook="capture-session-id", error="timeout", artifact="setup.py")

        result = read_snapshot(snap_path)
        assert len(result["hook_errors"]) == 1
        assert result["hook_errors"][0]["hook"] == "capture-session-id"

    def test_appends_to_existing_list(self, tmp_path):
        """Appends an error entry to an existing hook_errors list."""
        snap_path = str(tmp_path / "snapshot.json")
        existing = [{"hook": "old", "error": "err", "timestamp": "t", "artifact": "a"}]
        write_snapshot(snap_path, _make_snapshot(hook_errors=existing))

        append_hook_error(snap_path, hook="new-hook", error="new-err", artifact="b.py")

        result = read_snapshot(snap_path)
        assert len(result["hook_errors"]) == 2
        assert result["hook_errors"][1]["hook"] == "new-hook"

    def test_error_entry_has_required_fields(self, tmp_path):
        """Each error entry contains hook, error, timestamp, artifact fields."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot())

        append_hook_error(snap_path, hook="h", error="e", artifact="a")

        result = read_snapshot(snap_path)
        entry = result["hook_errors"][0]
        assert "hook" in entry
        assert "error" in entry
        assert "timestamp" in entry
        assert "artifact" in entry

    def test_acquires_lock_during_append(self, tmp_path):
        """Uses fcntl.flock during the read-modify-write cycle."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot())

        lock_calls = []
        original_flock = fcntl.flock

        def tracking_flock(fd, operation):
            lock_calls.append(operation)
            return original_flock(fd, operation)

        with patch("scripts.lib.snapshot.fcntl.flock", side_effect=tracking_flock):
            append_hook_error(snap_path, hook="h", error="e", artifact="a")

        assert fcntl.LOCK_EX in lock_calls


class TestClearHookErrors:
    def test_clears_all_entries(self, tmp_path):
        """Clears all entries from the hook_errors list."""
        snap_path = str(tmp_path / "snapshot.json")
        errors = [{"hook": "h", "error": "e", "timestamp": "t", "artifact": "a"}]
        write_snapshot(snap_path, _make_snapshot(hook_errors=errors))

        clear_hook_errors(snap_path)

        result = read_snapshot(snap_path)
        assert result["hook_errors"] == []

    def test_noop_if_already_empty(self, tmp_path):
        """No-op when hook_errors is already an empty list."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot(hook_errors=[]))

        clear_hook_errors(snap_path)

        result = read_snapshot(snap_path)
        assert result["hook_errors"] == []

    def test_preserves_other_fields(self, tmp_path):
        """All non-hook_errors snapshot fields remain unchanged."""
        snap_path = str(tmp_path / "snapshot.json")
        errors = [{"hook": "h", "error": "e", "timestamp": "t", "artifact": "a"}]
        write_snapshot(snap_path, _make_snapshot(
            hook_errors=errors, resume_step=7, git_branch="main"
        ))

        clear_hook_errors(snap_path)

        result = read_snapshot(snap_path)
        assert result["hook_errors"] == []
        assert result["resume_step"] == 7
        assert result["git_branch"] == "main"


class TestFormatResumeContext:
    def test_returns_correct_key_value_pairs(self):
        """Returns dict with expected DEEP_* keys."""
        snapshot = _make_snapshot(
            session_id="sess-1",
            resume_step=3,
            resume_step_name="Read section",
            plugin="deep-plan",
            git_branch="feature/test",
            task_summary={"total": 10, "completed": 3, "current_task_id": "7"},
            section_progress={"total": 6, "completed": 2, "current": "section-03"},
        )
        result = format_resume_context(snapshot, snapshot_path="/tmp/snapshot.json")

        assert result["DEEP_SESSION_ID"] == "sess-1"
        assert result["DEEP_RESUME_STEP"] == "3"
        assert result["DEEP_RESUME_NAME"] == "Read section"
        assert result["DEEP_PLUGIN"] == "deep-plan"
        assert result["DEEP_BRANCH"] == "feature/test"
        assert result["DEEP_SNAPSHOT"] == "/tmp/snapshot.json"
        assert "DEEP_PROGRESS" in result

    def test_caps_key_decisions_at_5(self):
        """Only the last 5 key_decisions are included in output."""
        decisions = [f"decision-{i}" for i in range(10)]
        snapshot = _make_snapshot(key_decisions=decisions)
        result = format_resume_context(snapshot)

        assert "DEEP_KEY_DECISIONS" in result
        included = result["DEEP_KEY_DECISIONS"]
        assert included.count("decision-") <= 5
        assert "decision-9" in included  # Last one should be there
        assert "decision-0" not in included  # First ones dropped

    def test_caps_hook_errors_at_3(self):
        """Only the last 3 hook_errors are included in DEEP_HOOK_WARNING."""
        errors = [
            {"hook": f"hook-{i}", "error": f"err-{i}", "timestamp": "t", "artifact": "a"}
            for i in range(5)
        ]
        snapshot = _make_snapshot(hook_errors=errors)
        result = format_resume_context(snapshot)

        warning = result.get("DEEP_HOOK_WARNING", "")
        assert "hook-4" in warning  # Last
        assert "hook-3" in warning
        assert "hook-2" in warning
        assert "hook-0" not in warning  # Dropped

    def test_minimal_output_for_sparse_snapshot(self):
        """Returns minimal key set when optional fields are None/empty."""
        snapshot = _make_snapshot(
            section_progress=None,
            env_validation=None,
            hook_errors=[],
            key_decisions=[],
        )
        result = format_resume_context(snapshot)

        assert "DEEP_SESSION_ID" in result
        assert "DEEP_RESUME_STEP" in result
        assert "DEEP_HOOK_WARNING" not in result

    def test_includes_hook_warning_when_errors_present(self):
        """DEEP_HOOK_WARNING key is present when hook_errors is non-empty."""
        errors = [{"hook": "h", "error": "e", "timestamp": "t", "artifact": "a"}]
        snapshot = _make_snapshot(hook_errors=errors)
        result = format_resume_context(snapshot)

        assert "DEEP_HOOK_WARNING" in result


class TestFileLocking:
    def test_concurrent_writes_no_corruption(self, tmp_path):
        """Two threads writing concurrently don't produce corrupt JSON."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot(resume_step=0))

        errors = []

        def writer(step):
            try:
                for i in range(10):
                    update_snapshot_field(snap_path, resume_step=step * 100 + i)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        # File should be valid JSON
        result = read_snapshot(snap_path)
        assert result is not None
        assert isinstance(result["resume_step"], int)

    def test_lock_file_in_same_directory(self, tmp_path):
        """Lock file (snapshot.lock) is created in the same directory as snapshot.json."""
        snap_path = str(tmp_path / "snapshot.json")
        write_snapshot(snap_path, _make_snapshot())

        lock_path = tmp_path / "snapshot.lock"
        assert lock_path.exists()

    def test_lock_released_after_operation(self, tmp_path):
        """Subsequent operations succeed after a previous one completes."""
        snap_path = str(tmp_path / "snapshot.json")

        write_snapshot(snap_path, _make_snapshot(resume_step=1))
        write_snapshot(snap_path, _make_snapshot(resume_step=2))
        write_snapshot(snap_path, _make_snapshot(resume_step=3))

        result = read_snapshot(snap_path)
        assert result["resume_step"] == 3
