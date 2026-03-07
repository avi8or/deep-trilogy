"""Tests for discover-session.py — the /deep-resume discovery script."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Import the module under test
_tools_dir = str(Path(__file__).parent.parent.parent / "scripts" / "tools")
sys.path.insert(0, _tools_dir)
import importlib

discover_session = importlib.import_module("discover-session")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(plugin="deep-implement", resume_step=5, **overrides):
    """Build a valid snapshot dict."""
    base = {
        "version": 1,
        "plugin": plugin,
        "session_id": "test-session-123",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "resume_step": resume_step,
        "resume_step_name": "section-05-overlay-buttons",
        "completed_artifacts": [],
        "section_progress": {"total": 10, "completed": 4, "current": "section-05"},
        "task_summary": {"total": 50, "completed": 30, "current_task_id": "42"},
        "git_branch": "feature/image-rotation",
        "key_decisions": ["Used canvas API for rendering"],
        "env_validation": None,
        "hook_errors": [],
    }
    base.update(overrides)
    return base


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


# ---------------------------------------------------------------------------
# read_snapshot / validate_snapshot
# ---------------------------------------------------------------------------


class TestReadSnapshot:
    def test_reads_valid_snapshot(self, tmp_path):
        snap = _make_snapshot()
        snap_path = tmp_path / "snapshot.json"
        _write_json(snap_path, snap)

        result = discover_session.read_snapshot(str(snap_path))
        assert result is not None
        assert result["plugin"] == "deep-implement"

    def test_returns_none_for_missing_file(self, tmp_path):
        result = discover_session.read_snapshot(str(tmp_path / "nope.json"))
        assert result is None

    def test_returns_none_for_corrupt_json(self, tmp_path):
        bad = tmp_path / "snapshot.json"
        bad.write_text("{not valid json")
        assert discover_session.read_snapshot(str(bad)) is None

    def test_returns_none_for_non_dict(self, tmp_path):
        snap_path = tmp_path / "snapshot.json"
        snap_path.write_text('"just a string"')
        assert discover_session.read_snapshot(str(snap_path)) is None


class TestValidateSnapshot:
    def test_valid_snapshot_no_artifacts(self, tmp_path):
        snap = _make_snapshot(completed_artifacts=[])
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is True

    def test_rejects_wrong_version(self, tmp_path):
        snap = _make_snapshot(version=99)
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is False

    def test_valid_with_fresh_artifacts(self, tmp_path):
        artifact = tmp_path / "claude-spec.md"
        _touch(artifact)

        snap = _make_snapshot(
            completed_artifacts=["claude-spec.md"],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is True

    def test_rejects_stale_snapshot(self, tmp_path):
        artifact = tmp_path / "claude-spec.md"
        _touch(artifact)

        snap = _make_snapshot(
            completed_artifacts=["claude-spec.md"],
            updated_at="2020-01-01T00:00:00+00:00",
        )
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is False

    def test_rejects_missing_artifact(self, tmp_path):
        snap = _make_snapshot(
            completed_artifacts=["does-not-exist.md"],
        )
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is False

    def test_skips_unsafe_paths(self, tmp_path):
        snap = _make_snapshot(
            completed_artifacts=["../../etc/passwd", "/absolute/path"],
        )
        # Unsafe paths are skipped, so an empty safe list passes
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is True

    def test_rejects_missing_updated_at(self, tmp_path):
        snap = _make_snapshot(completed_artifacts=["file.md"])
        del snap["updated_at"]
        _touch(tmp_path / "file.md")
        assert discover_session.validate_snapshot(snap, str(tmp_path)) is False


# ---------------------------------------------------------------------------
# discover_configs
# ---------------------------------------------------------------------------


class TestDiscoverConfigs:
    def test_finds_snapshot_in_cwd(self, tmp_path):
        _write_json(tmp_path / "snapshot.json", _make_snapshot())
        results = discover_session.discover_configs(tmp_path)
        assert any(r["type"] == "snapshot" for r in results)

    def test_finds_config_in_cwd(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        results = discover_session.discover_configs(tmp_path)
        configs = [r for r in results if r["type"] == "config"]
        assert len(configs) == 1
        assert configs[0]["plugin"] == "deep-plan"

    def test_finds_config_in_parent(self, tmp_path):
        _write_json(tmp_path / "deep_implement_config.json", {"sections_dir": "/x"})
        child = tmp_path / "subdir"
        child.mkdir()
        results = discover_session.discover_configs(child)
        configs = [r for r in results if r["type"] == "config"]
        assert len(configs) == 1
        assert configs[0]["depth"] == 1

    def test_finds_implementation_subdir(self, tmp_path):
        impl_dir = tmp_path / "implementation"
        impl_dir.mkdir()
        _write_json(impl_dir / "deep_implement_config.json", {"sections_dir": "/x"})
        results = discover_session.discover_configs(tmp_path)
        configs = [r for r in results if r["type"] == "config"]
        assert len(configs) == 1
        assert "implementation" in configs[0]["path"]

    def test_returns_empty_when_nothing_found(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        results = discover_session.discover_configs(empty)
        assert results == []

    def test_finds_multiple_plugins(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        impl_dir = tmp_path / "implementation"
        impl_dir.mkdir()
        _write_json(impl_dir / "deep_implement_config.json", {"sections_dir": "/x"})
        results = discover_session.discover_configs(tmp_path)
        plugins = {r["plugin"] for r in results if r["type"] == "config"}
        assert "deep-plan" in plugins
        assert "deep-implement" in plugins

    def test_depth_ordering(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        child = tmp_path / "a" / "b"
        child.mkdir(parents=True)
        results = discover_session.discover_configs(child)
        configs = [r for r in results if r["type"] == "config"]
        assert configs[0]["depth"] == 2


# ---------------------------------------------------------------------------
# try_snapshot_resume
# ---------------------------------------------------------------------------


class TestTrySnapshotResume:
    def test_returns_found_for_valid_snapshot(self, tmp_path):
        snap = _make_snapshot()
        snap_path = tmp_path / "snapshot.json"
        _write_json(snap_path, snap)

        result = discover_session.try_snapshot_resume(str(snap_path))
        assert result is not None
        assert result["status"] == "found"
        assert result["source"] == "snapshot"
        assert result["plugin"] == "deep-implement"
        assert result["resume_step"] == 5

    def test_returns_none_for_missing_snapshot(self, tmp_path):
        result = discover_session.try_snapshot_resume(str(tmp_path / "nope.json"))
        assert result is None

    def test_returns_none_for_unknown_plugin(self, tmp_path):
        snap = _make_snapshot(plugin="unknown-plugin")
        _write_json(tmp_path / "snapshot.json", snap)
        result = discover_session.try_snapshot_resume(str(tmp_path / "snapshot.json"))
        assert result is None

    def test_includes_progress_string(self, tmp_path):
        snap = _make_snapshot()
        _write_json(tmp_path / "snapshot.json", snap)
        result = discover_session.try_snapshot_resume(str(tmp_path / "snapshot.json"))
        assert "30/50 tasks" in result["progress"]
        assert "4/10 sections" in result["progress"]

    def test_enriches_from_implement_config(self, tmp_path):
        snap = _make_snapshot(plugin="deep-implement")
        _write_json(tmp_path / "snapshot.json", snap)
        _write_json(tmp_path / "deep_implement_config.json", {
            "sections_dir": "/path/to/sections",
            "target_dir": "/path/to/target",
        })
        result = discover_session.try_snapshot_resume(str(tmp_path / "snapshot.json"))
        assert result["sections_dir"] == "/path/to/sections"
        assert result["target_dir"] == "/path/to/target"

    def test_stale_snapshot_still_returned_with_flag(self, tmp_path):
        artifact = tmp_path / "claude-spec.md"
        _touch(artifact)
        snap = _make_snapshot(
            plugin="deep-plan",
            completed_artifacts=["claude-spec.md"],
            updated_at="2020-01-01T00:00:00+00:00",
        )
        _write_json(tmp_path / "snapshot.json", snap)
        result = discover_session.try_snapshot_resume(str(tmp_path / "snapshot.json"))
        assert result is not None
        assert result["snapshot_valid"] is False


# ---------------------------------------------------------------------------
# scan_plan_artifacts
# ---------------------------------------------------------------------------


class TestScanPlanArtifacts:
    def test_fresh_start(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["status"] == "found"
        assert result["plugin"] == "deep-plan"
        assert result["resume_step"] == 6
        assert result["resume_step_name"] == "fresh start"

    def test_research_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-research.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 8
        assert "research" in result["resume_step_name"]

    def test_interview_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-research.md")
        _touch(tmp_path / "claude-interview.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 10

    def test_spec_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-interview.md")
        _touch(tmp_path / "claude-spec.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 11

    def test_plan_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-interview.md")
        _touch(tmp_path / "claude-spec.md")
        _touch(tmp_path / "claude-plan.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 12

    def test_reviews_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-spec.md")
        _touch(tmp_path / "claude-plan.md")
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        _touch(reviews / "gemini-review.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 14

    def test_tdd_plan_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-interview.md")
        _touch(tmp_path / "claude-spec.md")
        _touch(tmp_path / "claude-plan.md")
        _touch(tmp_path / "claude-integration-notes.md")
        _touch(tmp_path / "claude-plan-tdd.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 17

    def test_sections_complete(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-plan-tdd.md")
        sections = tmp_path / "sections"
        sections.mkdir()
        _touch(sections / "index.md")
        _touch(sections / "section-01-setup.md")
        _touch(sections / "section-02-core.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["complete"] is True
        assert result["resume_step"] is None

    def test_prerequisite_check_tdd_missing(self, tmp_path):
        """Sections index exists but TDD plan is missing — resume at step 16."""
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        sections = tmp_path / "sections"
        sections.mkdir()
        _touch(sections / "index.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 16
        assert "prerequisite" in result["resume_step_name"]

    def test_prerequisite_check_spec_missing(self, tmp_path):
        """Plan exists but spec is missing — resume at step 10."""
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-plan.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 10
        assert "prerequisite" in result["resume_step_name"]

    def test_prerequisite_check_interview_missing(self, tmp_path):
        """Spec exists but interview is missing — resume at step 9."""
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-spec.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert result["resume_step"] == 9
        assert "prerequisite" in result["resume_step_name"]

    def test_progress_string_shows_artifact_count(self, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-research.md")
        _touch(tmp_path / "claude-interview.md")
        _touch(tmp_path / "claude-spec.md")
        result = discover_session.scan_plan_artifacts(str(tmp_path / "deep_plan_config.json"))
        assert "3/6" in result["progress"]


# ---------------------------------------------------------------------------
# scan_implement_artifacts
# ---------------------------------------------------------------------------


class TestScanImplementArtifacts:
    @pytest.fixture
    def impl_config(self, tmp_path):
        """Create a standard deep-implement config."""
        state_dir = tmp_path / "implementation"
        state_dir.mkdir()
        config = {
            "sections_dir": str(tmp_path / "sections"),
            "target_dir": str(tmp_path / "target"),
            "state_dir": str(state_dir),
            "sections": [
                "section-01-setup",
                "section-02-core",
                "section-03-ui",
                "section-04-tests",
            ],
            "sections_state": {},
        }
        config_path = state_dir / "deep_implement_config.json"
        _write_json(config_path, config)
        return config_path, config

    def test_new_session(self, impl_config):
        config_path, _ = impl_config
        result = discover_session.scan_implement_artifacts(str(config_path))
        assert result["status"] == "found"
        assert result["plugin"] == "deep-implement"
        assert result["complete"] is False
        assert result["resume_section"] == "section-01-setup"
        assert result["resume_sub_step"] == "implement"
        assert "0/4" in result["progress"]

    def test_partial_completion(self, tmp_path):
        state_dir = tmp_path / "implementation"
        state_dir.mkdir()
        config = {
            "sections_dir": str(tmp_path / "sections"),
            "target_dir": str(tmp_path / "target"),
            "sections": ["section-01-setup", "section-02-core", "section-03-ui"],
            "sections_state": {
                "section-01-setup": {"status": "complete", "commit_hash": "abc123"},
                "section-02-core": {"status": "complete", "commit_hash": "def456"},
                "section-03-ui": {"status": "in_progress"},
            },
        }
        config_path = state_dir / "deep_implement_config.json"
        _write_json(config_path, config)

        result = discover_session.scan_implement_artifacts(str(config_path))
        assert result["complete"] is False
        assert "2/3" in result["progress"]
        assert result["resume_section"] == "section-03-ui"

    def test_all_complete(self, tmp_path):
        state_dir = tmp_path / "implementation"
        state_dir.mkdir()
        config = {
            "sections_dir": str(tmp_path / "sections"),
            "target_dir": str(tmp_path / "target"),
            "sections": ["section-01-setup", "section-02-core"],
            "sections_state": {
                "section-01-setup": {"status": "complete", "commit_hash": "abc123"},
                "section-02-core": {"status": "complete", "commit_hash": "def456"},
            },
        }
        _write_json(state_dir / "deep_implement_config.json", config)

        result = discover_session.scan_implement_artifacts(str(state_dir / "deep_implement_config.json"))
        assert result["complete"] is True
        assert result["resume_step"] is None

    def test_sub_step_review(self, impl_config):
        config_path, _ = impl_config
        state_dir = config_path.parent
        cr_dir = state_dir / "code_review"
        cr_dir.mkdir()
        _touch(cr_dir / "section-01-diff.md")

        result = discover_session.scan_implement_artifacts(str(config_path))
        assert result["resume_sub_step"] == "review"

    def test_sub_step_interview(self, impl_config):
        config_path, _ = impl_config
        state_dir = config_path.parent
        cr_dir = state_dir / "code_review"
        cr_dir.mkdir()
        _touch(cr_dir / "section-01-diff.md")
        _touch(cr_dir / "section-01-review.md")

        result = discover_session.scan_implement_artifacts(str(config_path))
        assert result["resume_sub_step"] == "interview"

    def test_sub_step_apply_fixes(self, impl_config):
        config_path, _ = impl_config
        state_dir = config_path.parent
        cr_dir = state_dir / "code_review"
        cr_dir.mkdir()
        _touch(cr_dir / "section-01-diff.md")
        _touch(cr_dir / "section-01-review.md")
        _touch(cr_dir / "section-01-interview.md")

        result = discover_session.scan_implement_artifacts(str(config_path))
        assert result["resume_sub_step"] == "apply_fixes"

    def test_corrupt_config_returns_error(self, tmp_path):
        bad = tmp_path / "deep_implement_config.json"
        bad.write_text("{broken json")
        result = discover_session.scan_implement_artifacts(str(bad))
        assert result["status"] == "error"

    def test_incomplete_without_commit_hash(self, tmp_path):
        """A section with status=complete but no commit_hash is not counted."""
        state_dir = tmp_path / "implementation"
        state_dir.mkdir()
        config = {
            "sections_dir": str(tmp_path / "sections"),
            "target_dir": str(tmp_path / "target"),
            "sections": ["section-01-setup"],
            "sections_state": {
                "section-01-setup": {"status": "complete"},
            },
        }
        _write_json(state_dir / "deep_implement_config.json", config)

        result = discover_session.scan_implement_artifacts(str(state_dir / "deep_implement_config.json"))
        assert result["complete"] is False
        assert "0/1" in result["progress"]


# ---------------------------------------------------------------------------
# scan_project_artifacts
# ---------------------------------------------------------------------------


class TestScanProjectArtifacts:
    def test_fresh_start(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {
            "session_created_at": datetime.now(timezone.utc).isoformat(),
        })
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        assert result["status"] == "found"
        assert result["plugin"] == "deep-project"
        assert result["resume_step"] == 1

    def test_interview_complete(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {})
        _touch(tmp_path / "deep_project_interview.md")
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        assert result["resume_step"] == 2

    def test_manifest_created(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {})
        _touch(tmp_path / "deep_project_interview.md")
        _touch(tmp_path / "project-manifest.md")
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        assert result["resume_step"] == 4

    def test_split_dirs_no_specs(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {})
        _touch(tmp_path / "project-manifest.md")
        (tmp_path / "01-backend").mkdir()
        (tmp_path / "02-frontend").mkdir()
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        assert result["resume_step"] == 6
        assert "0/2" in result["progress"]

    def test_partial_specs(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {})
        (tmp_path / "01-backend").mkdir()
        (tmp_path / "02-frontend").mkdir()
        _touch(tmp_path / "01-backend" / "spec.md")
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        assert result["resume_step"] == 6
        assert "1/2" in result["progress"]

    def test_all_specs_complete(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {})
        (tmp_path / "01-backend").mkdir()
        (tmp_path / "02-frontend").mkdir()
        _touch(tmp_path / "01-backend" / "spec.md")
        _touch(tmp_path / "02-frontend" / "spec.md")
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        assert result["complete"] is True

    def test_ignores_invalid_dir_names(self, tmp_path):
        _write_json(tmp_path / "deep_project_session.json", {})
        (tmp_path / "01-backend").mkdir()
        (tmp_path / ".git").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "not-a-split").mkdir()
        result = discover_session.scan_project_artifacts(str(tmp_path / "deep_project_session.json"))
        # Only 01-backend should be detected
        assert result["resume_step"] == 6
        assert "0/1" in result["progress"]


# ---------------------------------------------------------------------------
# main (integration via subprocess)
# ---------------------------------------------------------------------------


class TestMainIntegration:
    @pytest.fixture
    def script_path(self):
        return Path(__file__).parent.parent.parent / "scripts" / "tools" / "discover-session.py"

    @pytest.fixture
    def plugin_root(self):
        return Path(__file__).parent.parent

    def _run(self, script_path, plugin_root, cwd, timeout=10):
        result = subprocess.run(
            ["uv", "run", "--project", str(plugin_root), str(script_path), "--cwd", str(cwd)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result

    def test_not_found(self, script_path, plugin_root, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = self._run(script_path, plugin_root, empty)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "not_found"

    def test_finds_snapshot(self, script_path, plugin_root, tmp_path):
        snap = _make_snapshot(plugin="deep-plan")
        _write_json(tmp_path / "snapshot.json", snap)
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})

        result = self._run(script_path, plugin_root, tmp_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "found"
        assert data["source"] == "snapshot"
        assert data["plugin"] == "deep-plan"

    def test_falls_back_to_artifact_scan(self, script_path, plugin_root, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-research.md")
        _touch(tmp_path / "claude-interview.md")

        result = self._run(script_path, plugin_root, tmp_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "found"
        assert data["source"] == "artifact-scan"
        assert data["plugin"] == "deep-plan"
        assert data["resume_step"] == 10

    def test_multiple_plugins_detected(self, script_path, plugin_root, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        impl_dir = tmp_path / "implementation"
        impl_dir.mkdir()
        _write_json(impl_dir / "deep_implement_config.json", {
            "sections_dir": "/x",
            "target_dir": "/y",
            "sections": [],
            "sections_state": {},
        })

        result = self._run(script_path, plugin_root, tmp_path)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "multiple"
        assert len(data["sessions"]) == 2

    def test_finds_config_in_parent(self, script_path, plugin_root, tmp_path):
        _write_json(tmp_path / "deep_plan_config.json", {"planning_dir": str(tmp_path)})
        _touch(tmp_path / "claude-spec.md")
        _touch(tmp_path / "claude-interview.md")

        child = tmp_path / "subdir"
        child.mkdir()

        result = self._run(script_path, plugin_root, child)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "found"
        assert data["plugin"] == "deep-plan"
