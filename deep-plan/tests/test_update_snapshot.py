"""Tests for update_snapshot CLI tool."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = str(Path(__file__).resolve().parent.parent / "scripts" / "tools" / "update_snapshot.py")


def run_tool(*args):
    """Run update_snapshot.py with given args and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, SCRIPT_PATH, *args],
        capture_output=True, text=True
    )


def _write_snapshot(path, data):
    """Write a snapshot JSON file directly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _read_snapshot(path):
    """Read and parse a snapshot JSON file."""
    return json.loads(path.read_text())


def _base_snapshot(**overrides):
    """Build a base snapshot dict."""
    snap = {
        "version": 1,
        "plugin": "deep-plan",
        "session_id": "test-123",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "resume_step": 1,
        "resume_step_name": "old-step",
        "completed_artifacts": [],
        "section_progress": None,
        "task_summary": {"total": 10, "completed": 3, "current_task_id": "5"},
        "git_branch": "feature/test",
        "key_decisions": ["decision-1"],
        "env_validation": None,
        "hook_errors": [],
    }
    snap.update(overrides)
    return snap


class TestRequiredArgs:
    def test_required_args_missing(self, tmp_path):
        """Running update_snapshot without required args exits with error code."""
        result = run_tool()
        assert result.returncode != 0

    def test_missing_step(self, tmp_path):
        """Missing --step exits with error."""
        snap_path = str(tmp_path / "snapshot.json")
        result = run_tool("--snapshot-path", snap_path, "--step-name", "test")
        assert result.returncode != 0

    def test_missing_step_name(self, tmp_path):
        """Missing --step-name exits with error."""
        snap_path = str(tmp_path / "snapshot.json")
        result = run_tool("--snapshot-path", snap_path, "--step", "1")
        assert result.returncode != 0


class TestArtifacts:
    def test_artifact_appends_to_completed_artifacts(self, tmp_path):
        """--artifact adds to the list without duplicating."""
        snap_path = tmp_path / "snapshot.json"
        _write_snapshot(snap_path, _base_snapshot(completed_artifacts=["existing.md"]))

        result = run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "2",
            "--step-name", "test-step",
            "--artifact", "new-file.md",
        )
        assert result.returncode == 0

        data = _read_snapshot(snap_path)
        assert "existing.md" in data["completed_artifacts"]
        assert "new-file.md" in data["completed_artifacts"]

    def test_artifact_deduplicates(self, tmp_path):
        """Adding the same artifact twice doesn't create duplicates."""
        snap_path = tmp_path / "snapshot.json"
        _write_snapshot(snap_path, _base_snapshot(completed_artifacts=["file.md"]))

        run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "2",
            "--step-name", "step",
            "--artifact", "file.md",
        )

        data = _read_snapshot(snap_path)
        assert data["completed_artifacts"].count("file.md") == 1

    def test_multiple_artifacts(self, tmp_path):
        """Multiple --artifact flags add all of them."""
        snap_path = tmp_path / "snapshot.json"

        run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "1",
            "--step-name", "step",
            "--artifact", "a.md",
            "--artifact", "b.md",
        )

        data = _read_snapshot(snap_path)
        assert "a.md" in data["completed_artifacts"]
        assert "b.md" in data["completed_artifacts"]


class TestKeyDecisions:
    def test_key_decision_appends(self, tmp_path):
        """--key-decision adds a string to the key_decisions list."""
        snap_path = tmp_path / "snapshot.json"
        _write_snapshot(snap_path, _base_snapshot(key_decisions=["old"]))

        run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "2",
            "--step-name", "step",
            "--key-decision", "new decision",
        )

        data = _read_snapshot(snap_path)
        assert "old" in data["key_decisions"]
        assert "new decision" in data["key_decisions"]


class TestSectionProgress:
    def test_section_progress_updates(self, tmp_path):
        """--section-progress '3/6' sets completed=3, total=6."""
        snap_path = tmp_path / "snapshot.json"

        run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "1",
            "--step-name", "step",
            "--section-progress", "3/6",
        )

        data = _read_snapshot(snap_path)
        assert data["section_progress"]["completed"] == 3
        assert data["section_progress"]["total"] == 6


class TestTaskId:
    def test_task_id_updates(self, tmp_path):
        """--task-id sets task_summary.current_task_id."""
        snap_path = tmp_path / "snapshot.json"
        _write_snapshot(snap_path, _base_snapshot())

        run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "2",
            "--step-name", "step",
            "--task-id", "TASK-05",
        )

        data = _read_snapshot(snap_path)
        assert data["task_summary"]["current_task_id"] == "TASK-05"


class TestSnapshotCreation:
    def test_creates_new_snapshot(self, tmp_path):
        """When snapshot doesn't exist, creates one with required fields."""
        snap_path = tmp_path / "snapshot.json"

        result = run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "1",
            "--step-name", "setup",
        )
        assert result.returncode == 0

        data = _read_snapshot(snap_path)
        assert data["version"] == 1
        assert data["resume_step"] == 1
        assert data["resume_step_name"] == "setup"

    def test_updates_existing_snapshot_preserves_data(self, tmp_path):
        """Existing fields like session_id, git_branch are preserved."""
        snap_path = tmp_path / "snapshot.json"
        _write_snapshot(snap_path, _base_snapshot(
            session_id="keep-me",
            git_branch="feature/keep",
        ))

        run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "5",
            "--step-name", "new-step",
        )

        data = _read_snapshot(snap_path)
        assert data["session_id"] == "keep-me"
        assert data["git_branch"] == "feature/keep"
        assert data["resume_step"] == 5


class TestPathValidation:
    def test_rejects_artifact_with_dotdot(self, tmp_path):
        """--artifact with '..' is rejected."""
        snap_path = tmp_path / "snapshot.json"

        result = run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "1",
            "--step-name", "step",
            "--artifact", "../../../etc/passwd",
        )
        assert result.returncode != 0

    def test_rejects_artifact_with_absolute_path(self, tmp_path):
        """--artifact with absolute path is rejected."""
        snap_path = tmp_path / "snapshot.json"

        result = run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "1",
            "--step-name", "step",
            "--artifact", "/etc/passwd",
        )
        assert result.returncode != 0

    def test_accepts_valid_relative_artifact(self, tmp_path):
        """--artifact with valid relative path is accepted."""
        snap_path = tmp_path / "snapshot.json"

        result = run_tool(
            "--snapshot-path", str(snap_path),
            "--step", "1",
            "--step-name", "step",
            "--artifact", "sections/section-01.md",
        )
        assert result.returncode == 0

        data = _read_snapshot(snap_path)
        assert "sections/section-01.md" in data["completed_artifacts"]
