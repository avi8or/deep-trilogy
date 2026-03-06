"""Tests for the SessionStart hook that captures session_id.

Tests for scripts/hooks/capture-session-id.py

The hook outputs session_id via additionalContext (primary) and also writes
to CLAUDE_ENV_FILE (secondary fallback for bash commands).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts to path for snapshot module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from lib.snapshot import write_snapshot

# Add scripts to path for importing the hook
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "hooks"))
from importlib import import_module


@pytest.fixture
def hook_module():
    """Import the hook module fresh for each test."""
    # Need to import as module since filename has hyphens
    spec = __import__("importlib.util").util.spec_from_file_location(
        "capture_session_id",
        Path(__file__).parent.parent / "scripts" / "hooks" / "capture-session-id.py"
    )
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCaptureSessionIdHook:
    """Test capture-session-id.py hook."""

    def test_outputs_session_id_as_additional_context(self, hook_module, capsys):
        """Valid session_id -> outputs hookSpecificOutput with additionalContext."""
        payload = {"session_id": "test-session-123"}

        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "DEEP_SESSION_ID=test-session-123",
            }
        }

    def test_succeeds_when_claude_env_file_not_set(self, hook_module, capsys):
        """Should succeed and output additionalContext even when CLAUDE_ENV_FILE is not set."""
        payload = {"session_id": "test-session-222"}

        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID=test-session-222" in captured.out

    def test_succeeds_when_claude_env_file_empty_string(self, hook_module, capsys):
        """Should succeed when CLAUDE_ENV_FILE is empty string (bug in Claude Code)."""
        payload = {"session_id": "test-session-333"}

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": ""}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID=test-session-333" in captured.out

    def test_valid_payload_writes_to_env_file(self, tmp_path, hook_module, capsys):
        """Valid JSON with session_id -> writes to CLAUDE_ENV_FILE (secondary)."""
        env_file = tmp_path / "env"
        payload = {"session_id": "abc-123-def"}

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        # Primary: additionalContext output
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID=abc-123-def" in captured.out
        # Secondary: env file
        content = env_file.read_text()
        assert "export DEEP_SESSION_ID=abc-123-def" in content

    def test_invalid_json_succeeds_silently(self, hook_module, capsys):
        """Invalid JSON -> returns 0, no crash, no output."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO("not json")):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == ""  # No output for invalid JSON

    def test_empty_stdin_succeeds_silently(self, hook_module, capsys):
        """Empty stdin -> returns 0, no crash, no output."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO("")):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_missing_session_id_succeeds_silently(self, hook_module, capsys):
        """JSON without session_id -> returns 0, no output."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO('{"other": "data"}')):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_appends_to_existing_env_file(self, tmp_path, hook_module):
        """Appends to existing env file, doesn't overwrite."""
        env_file = tmp_path / "env"
        env_file.write_text("export EXISTING_VAR=value\n")

        payload = {"session_id": "new-session"}

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        content = env_file.read_text()
        assert "EXISTING_VAR=value" in content
        assert "DEEP_SESSION_ID=new-session" in content

    def test_session_id_with_special_characters(self, tmp_path, hook_module, capsys):
        """Session ID with UUID format outputs correctly."""
        env_file = tmp_path / "env"
        payload = {"session_id": "550e8400-e29b-41d4-a716-446655440000"}

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        # Check additionalContext output
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID=550e8400-e29b-41d4-a716-446655440000" in captured.out
        # Check env file
        content = env_file.read_text()
        assert "DEEP_SESSION_ID=550e8400-e29b-41d4-a716-446655440000" in content

    def test_payload_with_extra_fields(self, tmp_path, hook_module, capsys):
        """Payload with extra fields still extracts session_id."""
        env_file = tmp_path / "env"
        payload = {
            "session_id": "my-session",
            "timestamp": "2026-01-26T12:00:00Z",
            "source": "clear",
            "other_field": {"nested": "value"},
        }

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID=my-session" in captured.out
        content = env_file.read_text()
        assert "DEEP_SESSION_ID=my-session" in content

    def test_env_file_write_error_still_outputs_context(self, tmp_path, hook_module, capsys):
        """Write error -> still outputs additionalContext, returns 0."""
        # Point to a directory (can't write to it as a file)
        env_file = tmp_path / "subdir"
        env_file.mkdir()

        payload = {"session_id": "my-session"}

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        # Should succeed and output additionalContext even though env file write failed
        assert result == 0
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID=my-session" in captured.out

    def test_skips_duplicate_session_id(self, tmp_path, hook_module):
        """If session_id already in file, don't write again (multiple plugins)."""
        env_file = tmp_path / "env"
        env_file.write_text("export DEEP_SESSION_ID=abc-123\n")

        payload = {"session_id": "abc-123"}

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        content = env_file.read_text()
        # Should only appear once (not duplicated)
        assert content.count("DEEP_SESSION_ID=abc-123") == 1

    def test_skips_duplicate_transcript_path(self, tmp_path, hook_module):
        """If transcript_path already in file, don't write again."""
        env_file = tmp_path / "env"
        env_file.write_text("export CLAUDE_TRANSCRIPT_PATH=/path/to/transcript.jsonl\n")

        payload = {
            "session_id": "new-session",
            "transcript_path": "/path/to/transcript.jsonl"
        }

        with patch.dict("os.environ", {"CLAUDE_ENV_FILE": str(env_file)}):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        content = env_file.read_text()
        # Session ID should be added, transcript path should not be duplicated
        assert "DEEP_SESSION_ID=new-session" in content
        assert content.count("CLAUDE_TRANSCRIPT_PATH=/path/to/transcript.jsonl") == 1

    def test_skips_output_when_deep_session_id_matches(self, hook_module, capsys):
        """Should not output when DEEP_SESSION_ID already matches session_id."""
        payload = {"session_id": "test-session-123"}

        with patch.dict("os.environ", {"DEEP_SESSION_ID": "test-session-123"}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        # Should NOT output additionalContext since it already matches
        assert captured.out == ""

    def test_outputs_when_deep_session_id_differs(self, hook_module, capsys):
        """Should output when DEEP_SESSION_ID exists but doesn't match."""
        payload = {"session_id": "new-session-456"}

        with patch.dict("os.environ", {"DEEP_SESSION_ID": "old-session-123"}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["hookSpecificOutput"]["additionalContext"] == "DEEP_SESSION_ID=new-session-456"

    def test_outputs_when_deep_session_id_not_set(self, hook_module, capsys):
        """Should output when DEEP_SESSION_ID is not set."""
        payload = {"session_id": "test-session-789"}

        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["hookSpecificOutput"]["additionalContext"] == "DEEP_SESSION_ID=test-session-789"

    def test_includes_plugin_root_when_available(self, hook_module, capsys):
        """Should include DEEP_PLUGIN_ROOT in additionalContext when CLAUDE_PLUGIN_ROOT is set."""
        payload = {"session_id": "test-session-123"}

        with patch.dict("os.environ", {"CLAUDE_PLUGIN_ROOT": "/path/to/plugin"}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "DEEP_SESSION_ID=test-session-123" in context
        assert "DEEP_PLUGIN_ROOT=/path/to/plugin" in context

    def test_omits_plugin_root_when_not_available(self, hook_module, capsys):
        """Should NOT include DEEP_PLUGIN_ROOT when CLAUDE_PLUGIN_ROOT is not set."""
        payload = {"session_id": "test-session-456"}

        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "DEEP_PLUGIN_ROOT" not in context
        assert "DEEP_SESSION_ID=test-session-456" in context

    def test_plugin_root_only_when_session_id_matches(self, hook_module, capsys):
        """Should still output plugin_root even when session_id already matches."""
        payload = {"session_id": "existing-session"}

        with patch.dict("os.environ", {
            "DEEP_SESSION_ID": "existing-session",
            "CLAUDE_PLUGIN_ROOT": "/path/to/plugin",
        }, clear=True):
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                result = hook_module.main()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        context = output["hookSpecificOutput"]["additionalContext"]
        # Session ID matches so it's not in context, but plugin_root is
        assert "DEEP_SESSION_ID" not in context
        assert "DEEP_PLUGIN_ROOT=/path/to/plugin" in context


def _make_valid_snapshot(tmp_path, **overrides):
    """Create a valid snapshot.json in tmp_path and return the path."""
    snap_path = str(tmp_path / "snapshot.json")
    data = {
        "version": 1,
        "plugin": "deep-plan",
        "session_id": "test-sess",
        "updated_at": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
        "resume_step": 5,
        "resume_step_name": "research-complete",
        "completed_artifacts": [],
        "section_progress": {"total": 6, "completed": 2, "current": "section-03"},
        "task_summary": {"total": 22, "completed": 14, "current_task_id": "15"},
        "git_branch": "feature/test",
        "key_decisions": ["use dataclasses"],
        "env_validation": None,
        "hook_errors": [],
    }
    data.update(overrides)
    write_snapshot(snap_path, data)
    return snap_path


def _run_hook(hook_module, session_id="test-123", env=None, cwd=None):
    """Helper to run the hook with optional CWD and env patches."""
    payload = {"session_id": session_id}
    env = env or {}
    patches = [
        patch.dict("os.environ", env, clear=True),
        patch("sys.stdin", StringIO(json.dumps(payload))),
    ]
    if cwd:
        patches.append(patch("os.getcwd", return_value=str(cwd)))
    with patches[0], patches[1]:
        if len(patches) > 2:
            with patches[2]:
                return hook_module.main()
        return hook_module.main()


class TestSnapshotDiscovery:
    """Tests for snapshot.json discovery logic in the SessionStart hook."""

    def test_finds_snapshot_in_cwd(self, hook_module, tmp_path, capsys):
        """Hook finds snapshot.json when it exists directly in CWD."""
        _make_valid_snapshot(tmp_path)

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_SNAPSHOT" in captured.out

    def test_finds_snapshot_via_deep_plan_config_in_cwd(self, hook_module, tmp_path, capsys):
        """Hook reads deep_plan_config.json in CWD, extracts planning_dir, finds snapshot there."""
        planning_dir = tmp_path / "planning"
        planning_dir.mkdir()
        _make_valid_snapshot(planning_dir)

        config = {"planning_dir": str(planning_dir), "plugin_root": "/tmp", "initial_file": "spec.md"}
        (tmp_path / "deep_plan_config.json").write_text(json.dumps(config))

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_SNAPSHOT" in captured.out
        assert str(planning_dir) in captured.out

    def test_finds_snapshot_via_deep_implement_config_in_cwd(self, hook_module, tmp_path, capsys):
        """Hook reads deep_implement_config.json in CWD, extracts state_dir, finds snapshot there."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        _make_valid_snapshot(state_dir)

        config = {"state_dir": str(state_dir)}
        (tmp_path / "deep_implement_config.json").write_text(json.dumps(config))

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_SNAPSHOT" in captured.out

    def test_walks_up_max_3_levels_to_find_config(self, hook_module, tmp_path, capsys):
        """Hook walks up parent directories (max 3 levels) to find config file."""
        # Config is 2 levels above CWD
        planning_dir = tmp_path / "planning"
        planning_dir.mkdir()
        _make_valid_snapshot(planning_dir)

        config = {"planning_dir": str(planning_dir), "plugin_root": "/tmp", "initial_file": "spec.md"}
        (tmp_path / "deep_plan_config.json").write_text(json.dumps(config))

        deep_cwd = tmp_path / "level1" / "level2"
        deep_cwd.mkdir(parents=True)

        _run_hook(hook_module, cwd=deep_cwd)

        captured = capsys.readouterr()
        assert "DEEP_SNAPSHOT" in captured.out

    def test_returns_no_snapshot_beyond_3_levels(self, hook_module, tmp_path, capsys):
        """Hook stops walking after 3 levels; snapshot 4+ levels up is not found."""
        planning_dir = tmp_path / "planning"
        planning_dir.mkdir()
        _make_valid_snapshot(planning_dir)

        config = {"planning_dir": str(planning_dir), "plugin_root": "/tmp", "initial_file": "spec.md"}
        (tmp_path / "deep_plan_config.json").write_text(json.dumps(config))

        deep_cwd = tmp_path / "l1" / "l2" / "l3" / "l4"
        deep_cwd.mkdir(parents=True)

        _run_hook(hook_module, cwd=deep_cwd)

        captured = capsys.readouterr()
        assert "DEEP_SNAPSHOT" not in captured.out

    def test_discovery_completes_quickly(self, hook_module, tmp_path):
        """Snapshot discovery completes in under 100ms even with no snapshot found."""
        start = time.monotonic()
        _run_hook(hook_module, cwd=tmp_path)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1


class TestSnapshotIntegrationInHook:
    """Tests for snapshot data appearing in additionalContext output."""

    def test_outputs_extended_context_with_valid_snapshot(self, hook_module, tmp_path, capsys):
        """Valid snapshot produces DEEP_SNAPSHOT, DEEP_RESUME_STEP, etc."""
        _make_valid_snapshot(tmp_path, resume_step=5, resume_step_name="research")

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "DEEP_RESUME_STEP=5" in context
        assert "DEEP_RESUME_NAME=research" in context
        assert "DEEP_PLUGIN=deep-plan" in context

    def test_outputs_only_session_id_when_snapshot_stale(self, hook_module, tmp_path, capsys):
        """Stale snapshot (missing artifact) -> only DEEP_SESSION_ID output."""
        _make_valid_snapshot(tmp_path, completed_artifacts=["missing-file.md"])

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_SNAPSHOT" not in captured.out
        assert "DEEP_SESSION_ID" in captured.out

    def test_outputs_only_session_id_when_no_snapshot(self, hook_module, tmp_path, capsys):
        """No snapshot found -> existing behavior, only DEEP_SESSION_ID."""
        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID" in captured.out
        assert "DEEP_SNAPSHOT" not in captured.out

    def test_outputs_deep_hook_warning_when_errors_present(self, hook_module, tmp_path, capsys):
        """Snapshot with hook_errors -> DEEP_HOOK_WARNING in additionalContext."""
        errors = [{"hook": "write-section", "error": "parse failed", "timestamp": "t", "artifact": "a"}]
        _make_valid_snapshot(tmp_path, hook_errors=errors)

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_HOOK_WARNING" in captured.out

    def test_clears_hook_errors_after_surfacing(self, hook_module, tmp_path, capsys):
        """After outputting DEEP_HOOK_WARNING, hook_errors are cleared from snapshot."""
        errors = [{"hook": "write-section", "error": "parse failed", "timestamp": "t", "artifact": "a"}]
        snap_path = _make_valid_snapshot(tmp_path, hook_errors=errors)

        _run_hook(hook_module, cwd=tmp_path)

        # Re-read snapshot from disk
        with open(snap_path) as f:
            data = json.load(f)
        assert data["hook_errors"] == []

    def test_multiple_errors_all_surfaced(self, hook_module, tmp_path, capsys):
        """Multiple hook_errors entries are all included in DEEP_HOOK_WARNING."""
        errors = [
            {"hook": "write-section", "error": "parse failed", "timestamp": "t1", "artifact": "sec-01"},
            {"hook": "write-section", "error": "file write failed", "timestamp": "t2", "artifact": "sec-02"},
            {"hook": "other-hook", "error": "something else", "timestamp": "t3", "artifact": "unknown"},
        ]
        _make_valid_snapshot(tmp_path, hook_errors=errors)

        _run_hook(hook_module, cwd=tmp_path)

        captured = capsys.readouterr()
        assert "DEEP_HOOK_WARNING" in captured.out
        # format_resume_context joins last 3 errors with " | "
        output = json.loads(captured.out)
        context = output["hookSpecificOutput"]["additionalContext"]
        warning_line = [l for l in context.split("\n") if "DEEP_HOOK_WARNING" in l][0]
        assert "parse failed" in warning_line
        assert "file write failed" in warning_line
        assert "something else" in warning_line


class TestSnapshotHookBackwardCompatibility:
    """Ensure existing behavior is preserved when snapshot features are added."""

    def test_existing_behavior_unchanged_without_snapshot(self, hook_module, tmp_path, capsys):
        """When no snapshot exists, output is identical to pre-extension behavior."""
        _run_hook(hook_module, cwd=tmp_path, env={"CLAUDE_PLUGIN_ROOT": "/plugin"})

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        context = output["hookSpecificOutput"]["additionalContext"]
        lines = context.split("\n")
        # Should have session_id and plugin_root only
        assert any("DEEP_SESSION_ID=" in l for l in lines)
        assert any("DEEP_PLUGIN_ROOT=" in l for l in lines)
        assert not any("DEEP_SNAPSHOT" in l for l in lines)

    def test_hook_returns_zero_on_snapshot_read_error(self, hook_module, tmp_path, capsys):
        """Corrupt snapshot file does not crash hook; returns 0."""
        (tmp_path / "snapshot.json").write_text("not valid json at all")

        result = _run_hook(hook_module, cwd=tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "DEEP_SESSION_ID" in captured.out

    def test_json_parsing_errors_dont_crash_hook(self, hook_module, tmp_path, capsys):
        """Malformed snapshot JSON is handled gracefully."""
        (tmp_path / "snapshot.json").write_text("{broken")

        result = _run_hook(hook_module, cwd=tmp_path)

        assert result == 0
        assert "DEEP_SNAPSHOT" not in capsys.readouterr().out
