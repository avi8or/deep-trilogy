"""Tests for setup-planning-session.py script."""

import sys
import pytest
import subprocess
import json
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from lib.snapshot import write_snapshot


class TestSetupPlanningSession:
    """Tests for setup-planning-session.py script."""

    @pytest.fixture
    def script_path(self):
        """Return path to setup-planning-session.py."""
        return Path(__file__).parent.parent / "scripts" / "checks" / "setup-planning-session.py"

    @pytest.fixture
    def plugin_root(self):
        """Return path to plugin root."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def run_script(self, script_path, plugin_root, tmp_path):
        """Factory fixture to run setup-planning-session.py."""
        def _run(file_path: str, timeout=10, extra_args=None, env_overrides=None):
            """Run the script with given file path."""
            env = os.environ.copy()
            env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
            # Default session ID for tests (tasks written to tmp_path/.claude/tasks/)
            env["DEEP_SESSION_ID"] = "test-session-default"
            env["HOME"] = str(tmp_path)  # Isolate task writes to tmp_path
            if env_overrides:
                env.update(env_overrides)

            cmd = [
                "uv", "run", str(script_path),
                "--file", file_path,
                "--plugin-root", str(plugin_root),
            ]
            if extra_args:
                cmd.extend(extra_args)

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result
        return _run

    # --- Basic input validation tests ---

    def test_requires_file_arg(self, script_path, plugin_root):
        """Should fail when --file is not provided."""
        result = subprocess.run(
            ["uv", "run", str(script_path), "--plugin-root", str(plugin_root)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "required" in result.stderr.lower() or "--file" in result.stderr

    def test_requires_plugin_root_arg(self, script_path, tmp_path):
        """Should fail when --plugin-root is not provided."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = subprocess.run(
            ["uv", "run", str(script_path), "--file", str(spec_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "required" in result.stderr.lower() or "--plugin-root" in result.stderr

    def test_rejects_directory_input(self, run_script, tmp_path):
        """Should fail when a directory is passed instead of a file."""
        result = run_script(str(tmp_path))

        assert result.returncode == 1
        output = json.loads(result.stdout)

        assert output["success"] is False
        assert output["mode"] == "error"
        assert "directory" in output["error"].lower()

    # --- New session tests ---

    def test_new_session_with_existing_spec(self, run_script, tmp_path):
        """Should return new mode for existing spec with no planning files."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# My Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["success"] is True
        assert output["mode"] == "new"
        assert output["planning_dir"] == str(tmp_path)
        assert output["initial_file"] == str(spec_file)
        # New sessions start at step 6 (codebase research decision)
        assert output["resume_from_step"] == 6
        # Check for tasks_written (fixture provides DEEP_SESSION_ID)
        assert "tasks_written" in output
        assert output["tasks_written"] > 0  # Should write 21 workflow tasks

    def test_fails_with_nonexistent_spec(self, run_script, tmp_path):
        """Should fail if spec file doesn't exist."""
        spec_file = tmp_path / "nonexistent.md"

        result = run_script(str(spec_file))

        assert result.returncode == 1
        output = json.loads(result.stdout)

        assert output["success"] is False
        assert "not found" in output["error"].lower()

    def test_fails_with_empty_spec(self, run_script, tmp_path):
        """Should fail if spec file is empty."""
        spec_file = tmp_path / "empty.md"
        spec_file.write_text("")  # Empty file

        result = run_script(str(spec_file))

        assert result.returncode == 1
        output = json.loads(result.stdout)

        assert output["success"] is False
        assert "empty" in output["error"].lower()

    # --- Resume detection tests ---

    def test_detects_resume_from_research_file(self, run_script, tmp_path):
        """Should detect resume when claude-research.md exists."""
        (tmp_path / "claude-research.md").write_text("# Research")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 8  # After research, resume at interview

    def test_detects_resume_from_interview_file(self, run_script, tmp_path):
        """Should detect resume when claude-interview.md exists."""
        (tmp_path / "claude-interview.md").write_text("# Interview")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 10  # After interview, resume at write spec

    def test_detects_resume_from_plan_file(self, run_script, tmp_path):
        """Should detect resume when claude-plan.md exists (with prerequisites)."""
        # Include prerequisites: interview -> spec -> plan
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 12  # After plan, resume at context check

    def test_detects_complete_workflow(self, run_script, tmp_path):
        """Should detect complete when ALL sections are written (with prerequisites)."""
        # Include all prerequisites
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Index defines one section with SECTION_MANIFEST block, and that section exists
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
END_MANIFEST -->

# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        (sections_dir / "section-01-setup.md").write_text("# Section 1")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["mode"] == "complete"
        # Section progress details are no longer in output (simplified)
        # Just verify mode is correct

    def test_detects_partial_sections(self, run_script, tmp_path):
        """Should detect resume at step 19 when sections are partially complete (with prerequisites)."""
        # Include all prerequisites
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Index defines 3 sections with SECTION_MANIFEST block, but only 1 is complete
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
section-02-api
section-03-tests
END_MANIFEST -->

# Index

## Sections

| Section | Depends On |
|---------|------------|
| section-01-setup | - |
| section-02-api | section-01 |
| section-03-tests | section-02 |
"""
        (sections_dir / "index.md").write_text(index_content)
        (sections_dir / "section-01-setup.md").write_text("# Section 1")
        # section-02 and section-03 are NOT created
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["mode"] == "resume"
        # Step 19 = Write section files (index exists, need to write remaining sections)
        assert output["resume_from_step"] == 19
        # Section progress details are in the message, not separate field
        assert "1/3" in output["message"]

    # --- Session config tests ---

    def test_creates_session_config(self, run_script, tmp_path, plugin_root):
        """Should create session config file in planning directory."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        # Verify JSON output is valid
        json.loads(result.stdout)

        # Config file should exist (config_created no longer in output)
        config_path = tmp_path / "deep_plan_config.json"
        assert config_path.exists()

        # Config should have required session keys
        import json as json_module
        config = json_module.loads(config_path.read_text())
        assert config["plugin_root"] == str(plugin_root)
        assert config["planning_dir"] == str(tmp_path)
        assert config["initial_file"] == str(spec_file)

        # Config should also include global config settings (copied from plugin's config.json)
        assert "context" in config
        assert "check_enabled" in config["context"]
        assert "models" in config
        assert "external_review" in config

    # --- Task writing tests ---

    def test_writes_tasks_when_session_id_set(self, run_script, tmp_path, monkeypatch):
        """Should write task files when DEEP_SESSION_ID is set."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        # Create a temp tasks directory
        tasks_dir = tmp_path / ".claude" / "tasks" / "test-session"
        tasks_dir.mkdir(parents=True)

        # Monkeypatch home to tmp_path
        result = run_script(
            str(spec_file),
            env_overrides={
                "DEEP_SESSION_ID": "test-session",
                "HOME": str(tmp_path),
            }
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should have written 21 workflow tasks
        assert output["tasks_written"] == 21
        assert output["task_list_id"] == "test-session"
        assert "task_write_error" not in output
        assert "task_write_warning" not in output

    def test_fails_when_no_session_id(self, run_script, tmp_path):
        """Should fail when no session ID available."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        # Clear both session ID sources
        result = run_script(str(spec_file), env_overrides={
            "DEEP_SESSION_ID": "",  # Empty to unset
            "CLAUDE_CODE_TASK_LIST_ID": "",  # Empty to unset
        })

        assert result.returncode == 1
        output = json.loads(result.stdout)

        # Should fail with no_task_list mode
        assert output["success"] is False
        assert output["mode"] == "no_task_list"
        assert "error" in output
        assert "error_details" in output
        assert "troubleshooting" in output["error_details"]

    # --- Files found tests ---

    def test_includes_files_found(self, run_script, tmp_path):
        """Should include files_found summary in output."""
        (tmp_path / "claude-research.md").write_text("# Research")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert "files_found" in output
        assert "claude-research.md" in output["files_found"]

    # --- Message tests ---

    def test_message_for_new_session(self, run_script, tmp_path):
        """Should have appropriate message for new session."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert "new" in output["message"].lower()

    def test_message_for_resume_session(self, run_script, tmp_path):
        """Should have appropriate message for resume session."""
        (tmp_path / "claude-plan.md").write_text("# Plan")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert "resum" in output["message"].lower()
        assert str(output["resume_from_step"]) in output["message"]

    # --- Path handling tests ---

    def test_relative_path_converted_to_absolute(self, run_script, tmp_path):
        """Should convert relative paths to absolute."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        # Note: This is tricky to test since we can't control cwd easily
        # Just verify output has absolute paths
        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert Path(output["planning_dir"]).is_absolute()
        assert Path(output["initial_file"]).is_absolute()

    # --- Missing prerequisite detection tests ---

    def test_missing_tdd_plan_when_index_exists(self, run_script, tmp_path):
        """Should detect missing claude-plan-tdd.md when sections/index.md exists.

        This catches the case where Claude skipped step 16 (TDD approach)
        but created the section index anyway.
        """
        # Create files that exist AFTER step 16, but NOT claude-plan-tdd.md
        (tmp_path / "claude-plan.md").write_text("# Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
END_MANIFEST -->
# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should resume at step 16 to create the missing TDD plan
        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 16
        assert "MISSING PREREQUISITE" in output["message"]
        assert "claude-plan-tdd.md" in output["message"]
        assert "OVERWRITE" in output["message"]
        assert "sections/" in output["message"]

    def test_missing_tdd_plan_when_section_files_exist(self, run_script, tmp_path):
        """Should detect missing claude-plan-tdd.md when section files exist but no index."""
        (tmp_path / "claude-plan.md").write_text("# Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        (sections_dir / "section-01-setup.md").write_text("# Section 1")
        # No index.md, no claude-plan-tdd.md
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should resume at step 16 to create the missing TDD plan
        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 16
        assert "MISSING PREREQUISITE" in output["message"]
        assert "OVERWRITE" in output["message"]

    def test_missing_plan_when_reviews_exist(self, run_script, tmp_path):
        """Should detect missing claude-plan.md when reviews exist."""
        reviews_dir = tmp_path / "reviews"
        reviews_dir.mkdir()
        (reviews_dir / "iteration-1-gemini.md").write_text("# Review")
        # No claude-plan.md
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should resume at step 11 to create the missing plan
        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 11
        assert "MISSING PREREQUISITE" in output["message"]
        assert "claude-plan.md" in output["message"]
        assert "OVERWRITE" in output["message"]
        assert "reviews/" in output["message"]

    def test_missing_spec_when_plan_exists(self, run_script, tmp_path):
        """Should detect missing claude-spec.md when plan exists."""
        (tmp_path / "claude-plan.md").write_text("# Plan")
        # No claude-spec.md
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should resume at step 10 to create the missing spec
        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 10
        assert "MISSING PREREQUISITE" in output["message"]
        assert "claude-spec.md" in output["message"]
        assert "OVERWRITE" in output["message"]
        assert "claude-plan.md" in output["message"]

    def test_missing_interview_when_spec_exists(self, run_script, tmp_path):
        """Should detect missing claude-interview.md when spec exists."""
        (tmp_path / "claude-spec.md").write_text("# Spec")
        # No claude-interview.md
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should resume at step 9 to create the missing interview
        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 9
        assert "MISSING PREREQUISITE" in output["message"]
        assert "claude-interview.md" in output["message"]
        assert "OVERWRITE" in output["message"]
        assert "claude-spec.md" in output["message"]

    def test_all_prerequisites_present(self, run_script, tmp_path):
        """Should resume normally when all prerequisites are present."""
        # Create all files in order
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
END_MANIFEST -->
# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should resume at step 19 (section writing) since all prereqs exist
        assert output["mode"] == "resume"
        assert output["resume_from_step"] == 19
        assert "MISSING PREREQUISITE" not in output["message"]


class TestSectionTasksIntegration:
    """Tests for section tasks integration in setup-planning-session.py."""

    @pytest.fixture
    def script_path(self):
        """Return path to setup-planning-session.py."""
        return Path(__file__).parent.parent / "scripts" / "checks" / "setup-planning-session.py"

    @pytest.fixture
    def plugin_root(self):
        """Return path to plugin root."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def run_script(self, script_path, plugin_root, tmp_path):
        """Factory fixture to run setup-planning-session.py."""
        def _run(file_path: str, timeout=10, env_overrides=None):
            """Run the script with given file path."""
            env = os.environ.copy()
            env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
            # Default session ID for tests (tasks written to tmp_path/.claude/tasks/)
            env["DEEP_SESSION_ID"] = "test-session-default"
            env["HOME"] = str(tmp_path)  # Isolate task writes to tmp_path
            if env_overrides:
                env.update(env_overrides)

            cmd = [
                "uv", "run", str(script_path),
                "--file", file_path,
                "--plugin-root", str(plugin_root),
            ]

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result
        return _run

    def test_writes_section_tasks_when_index_exists(self, run_script, tmp_path):
        """Should write section tasks when sections/index.md exists."""
        # Create all prerequisites for sections
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Index with 2 sections
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
section-02-api
END_MANIFEST -->
# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(
            str(spec_file),
            env_overrides={"DEEP_SESSION_ID": "test-session", "HOME": str(tmp_path)}
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # With INSERT behavior:
        # 18 workflow tasks (up to generate-section-tasks) + 1 batch + 2 sections + 2 (final + output) = 23
        assert output["tasks_written"] == 23

        # Verify batch and section task files exist at new positions
        tasks_dir = tmp_path / ".claude" / "tasks" / "test-session"
        assert (tasks_dir / "19.json").exists()  # batch-1 (INSERT position)
        assert (tasks_dir / "20.json").exists()  # section-01
        assert (tasks_dir / "21.json").exists()  # section-02
        assert (tasks_dir / "22.json").exists()  # Final Verification (shifted)
        assert (tasks_dir / "23.json").exists()  # Output Summary (shifted)

        # Verify batch task content
        task_19 = json.loads((tasks_dir / "19.json").read_text())
        assert task_19["subject"] == "Run batch 1 section subagents"
        assert task_19["status"] == "in_progress"

        # Verify section tasks (all in_progress, parallel within batch)
        task_20 = json.loads((tasks_dir / "20.json").read_text())
        assert "section-01-setup" in task_20["subject"]
        assert task_20["status"] == "in_progress"

        task_21 = json.loads((tasks_dir / "21.json").read_text())
        assert "section-02-api" in task_21["subject"]
        assert task_21["status"] == "in_progress"

        # Verify shifted tasks
        task_22 = json.loads((tasks_dir / "22.json").read_text())
        assert "Final Verification" in task_22["subject"]

        task_23 = json.loads((tasks_dir / "23.json").read_text())
        assert "Output Summary" in task_23["subject"]

    def test_no_section_tasks_when_no_index(self, run_script, tmp_path):
        """Should NOT write section tasks when sections/index.md doesn't exist."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(
            str(spec_file),
            env_overrides={"DEEP_SESSION_ID": "test-session", "HOME": str(tmp_path)}
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should have only 21 workflow tasks (no sections)
        assert output["tasks_written"] == 21

        # No section task files
        tasks_dir = tmp_path / ".claude" / "tasks" / "test-session"
        assert not (tasks_dir / "22.json").exists()

    def test_section_tasks_reflect_completed_status(self, run_script, tmp_path):
        """Section tasks for written files should have completed status."""
        # Create all prerequisites
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Index with 3 sections
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
section-02-api
section-03-tests
END_MANIFEST -->
# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        # Only first section is written
        (sections_dir / "section-01-setup.md").write_text("# Section 1")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(
            str(spec_file),
            env_overrides={"DEEP_SESSION_ID": "test-session", "HOME": str(tmp_path)}
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # With INSERT behavior:
        # 18 workflow + 1 batch + 3 sections + 2 (final + output) = 24 tasks
        assert output["tasks_written"] == 24

        # Verify statuses at new positions
        tasks_dir = tmp_path / ".claude" / "tasks" / "test-session"
        task_19 = json.loads((tasks_dir / "19.json").read_text())
        task_20 = json.loads((tasks_dir / "20.json").read_text())
        task_21 = json.loads((tasks_dir / "21.json").read_text())
        task_22 = json.loads((tasks_dir / "22.json").read_text())

        # Batch task is in_progress (not all sections complete)
        assert task_19["subject"] == "Run batch 1 section subagents"
        assert task_19["status"] == "in_progress"
        # Section-01 is completed (file exists)
        assert task_20["status"] == "completed"
        # Sections 02-03 are in_progress (parallel, within active batch)
        assert task_21["status"] == "in_progress"
        assert task_22["status"] == "in_progress"

    def test_no_section_tasks_on_invalid_index(self, run_script, tmp_path):
        """Should not write section tasks when index.md is invalid."""
        # Create prerequisites
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Invalid index - no SECTION_MANIFEST block
        (sections_dir / "index.md").write_text("# Index\n\nNo manifest here")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(
            str(spec_file),
            env_overrides={"DEEP_SESSION_ID": "test-session", "HOME": str(tmp_path)}
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should still succeed overall
        assert output["success"] is True

        # Should only have 21 workflow tasks (no section tasks due to invalid index)
        assert output["tasks_written"] == 21

    def test_section_tasks_with_multiple_batches(self, run_script, tmp_path):
        """Should write section tasks across multiple batches (>7 sections)."""
        # Create all prerequisites
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Index with 10 sections (batch 1: 7, batch 2: 3)
        index_content = """<!-- SECTION_MANIFEST
section-01-one
section-02-two
section-03-three
section-04-four
section-05-five
section-06-six
section-07-seven
section-08-eight
section-09-nine
section-10-ten
END_MANIFEST -->
# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(
            str(spec_file),
            env_overrides={"DEEP_SESSION_ID": "test-session", "HOME": str(tmp_path)}
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # With INSERT behavior:
        # 18 workflow + 2 batches + 10 sections + 2 (final + output) = 32 total
        assert output["tasks_written"] == 32

        # Verify batch and section task files at new positions
        tasks_dir = tmp_path / ".claude" / "tasks" / "test-session"
        # Positions: 19=batch-1, 20-26=sections 1-7, 27=batch-2, 28-30=sections 8-10, 31=final, 32=output
        for i in range(19, 33):
            assert (tasks_dir / f"{i}.json").exists()

        # Batch 1 (position 19) should be in_progress (ready to work on)
        task_19 = json.loads((tasks_dir / "19.json").read_text())
        assert task_19["subject"] == "Run batch 1 section subagents"
        assert task_19["status"] == "in_progress"

        # All sections in batch 1 (positions 20-26) should be in_progress (parallel)
        for pos in range(20, 27):
            task = json.loads((tasks_dir / f"{pos}.json").read_text())
            assert task["status"] == "in_progress", f"Position {pos} should be in_progress"

        # Batch 2 (position 27) should be pending (batch 1 not complete)
        task_27 = json.loads((tasks_dir / "27.json").read_text())
        assert task_27["subject"] == "Run batch 2 section subagents"
        assert task_27["status"] == "pending"

        # All sections in batch 2 (positions 28-30) should be pending
        for pos in range(28, 31):
            task = json.loads((tasks_dir / f"{pos}.json").read_text())
            assert task["status"] == "pending", f"Position {pos} should be pending"

        # Final Verification at position 31
        task_31 = json.loads((tasks_dir / "31.json").read_text())
        assert "Final Verification" in task_31["subject"]

        # Output Summary at position 32
        task_32 = json.loads((tasks_dir / "32.json").read_text())
        assert "Output Summary" in task_32["subject"]

    def test_complete_workflow_no_section_tasks(self, run_script, tmp_path):
        """Complete workflow should not write section tasks (all sections written)."""
        # Create all prerequisites
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec")
        (tmp_path / "claude-plan.md").write_text("# Plan")
        (tmp_path / "claude-plan-tdd.md").write_text("# TDD Plan")
        sections_dir = tmp_path / "sections"
        sections_dir.mkdir()
        # Index with 2 sections, both written
        index_content = """<!-- SECTION_MANIFEST
section-01-setup
section-02-api
END_MANIFEST -->
# Index
"""
        (sections_dir / "index.md").write_text(index_content)
        (sections_dir / "section-01-setup.md").write_text("# Section 1")
        (sections_dir / "section-02-api.md").write_text("# Section 2")
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(
            str(spec_file),
            env_overrides={"DEEP_SESSION_ID": "test-session", "HOME": str(tmp_path)}
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Workflow is complete
        assert output["mode"] == "complete"

        # generate_section_tasks_to_write returns empty when complete
        # So total is 21 workflow + 0 section = 21
        assert output["tasks_written"] == 21


class TestConflictDetection:
    """Tests for conflict detection with CLAUDE_CODE_TASK_LIST_ID."""

    @pytest.fixture
    def script_path(self):
        """Return path to setup-planning-session.py."""
        return Path(__file__).parent.parent / "scripts" / "checks" / "setup-planning-session.py"

    @pytest.fixture
    def plugin_root(self):
        """Return path to plugin root."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def run_script(self, script_path, plugin_root, tmp_path):
        """Factory fixture to run setup-planning-session.py."""
        def _run(file_path: str, timeout=10, extra_args=None, env_overrides=None):
            """Run the script with given file path."""
            env = os.environ.copy()
            env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
            # Default session ID for tests (tasks written to tmp_path/.claude/tasks/)
            env["DEEP_SESSION_ID"] = "test-session-default"
            env["HOME"] = str(tmp_path)  # Isolate task writes to tmp_path
            if env_overrides:
                env.update(env_overrides)

            cmd = [
                "uv", "run", str(script_path),
                "--file", file_path,
                "--plugin-root", str(plugin_root),
            ]
            if extra_args:
                cmd.extend(extra_args)

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result
        return _run

    def test_conflict_when_user_task_list_has_tasks(self, run_script, tmp_path):
        """Should return conflict when CLAUDE_CODE_TASK_LIST_ID has existing tasks."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        # Create existing tasks in user-specified task list
        tasks_dir = tmp_path / ".claude" / "tasks" / "my-shared-list"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "1.json").write_text(json.dumps({
            "id": "1",
            "subject": "Existing Task",
            "status": "pending"
        }))

        result = run_script(
            str(spec_file),
            env_overrides={
                "CLAUDE_CODE_TASK_LIST_ID": "my-shared-list",
                "HOME": str(tmp_path),
            }
        )

        assert result.returncode == 1  # Should fail
        output = json.loads(result.stdout)

        assert output["success"] is False
        assert output["mode"] == "conflict"
        assert "conflict" in output
        assert output["conflict"]["existing_task_count"] == 1
        assert "--force" in output["message"]

    def test_force_overwrites_existing_tasks(self, run_script, tmp_path):
        """Should overwrite existing tasks when --force is used."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        # Create existing tasks in user-specified task list
        tasks_dir = tmp_path / ".claude" / "tasks" / "my-shared-list"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "1.json").write_text(json.dumps({
            "id": "1",
            "subject": "Existing Task",
            "status": "pending"
        }))

        result = run_script(
            str(spec_file),
            extra_args=["--force"],
            env_overrides={
                "CLAUDE_CODE_TASK_LIST_ID": "my-shared-list",
                "HOME": str(tmp_path),
            }
        )

        assert result.returncode == 0  # Should succeed with --force
        output = json.loads(result.stdout)

        assert output["success"] is True
        assert output["tasks_written"] == 21  # Workflow tasks written

    def test_no_conflict_with_session_id(self, run_script, tmp_path):
        """Should NOT conflict when using DEEP_SESSION_ID (resume scenario)."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        # Create existing tasks in session-based task list
        tasks_dir = tmp_path / ".claude" / "tasks" / "sess-123"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "1.json").write_text(json.dumps({
            "id": "1",
            "subject": "Existing Task",
            "status": "pending"
        }))

        result = run_script(
            str(spec_file),
            env_overrides={
                "DEEP_SESSION_ID": "sess-123",
                "HOME": str(tmp_path),
            }
        )

        assert result.returncode == 0  # Should succeed (no conflict for session-based)
        output = json.loads(result.stdout)

        assert output["success"] is True
        assert "conflict" not in output


class TestSnapshotIntegration:
    """Tests for snapshot-aware resume detection in setup-planning-session.py."""

    @pytest.fixture
    def script_path(self):
        return Path(__file__).parent.parent / "scripts" / "checks" / "setup-planning-session.py"

    @pytest.fixture
    def plugin_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def run_script(self, script_path, plugin_root, tmp_path):
        def _run(file_path: str, extra_args=None, env_overrides=None):
            env = os.environ.copy()
            env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
            env["DEEP_SESSION_ID"] = "test-session-snap"
            env["HOME"] = str(tmp_path)
            if env_overrides:
                env.update(env_overrides)
            cmd = [
                "uv", "run", str(script_path),
                "--file", file_path,
                "--plugin-root", str(plugin_root),
            ]
            if extra_args:
                cmd.extend(extra_args)
            return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
        return _run

    def _write_valid_snapshot(self, planning_dir, **overrides):
        """Write a valid snapshot.json in the planning dir."""
        snap_path = str(planning_dir / "snapshot.json")
        data = {
            "version": 1,
            "plugin": "deep-plan",
            "session_id": "test-session-snap",
            "updated_at": datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
            "resume_step": 12,
            "resume_step_name": "context-check-review",
            "completed_artifacts": [],
            "section_progress": None,
            "task_summary": {"total": 21, "completed": 6, "current_task_id": "7"},
            "git_branch": "",
            "key_decisions": [],
            "env_validation": None,
            "hook_errors": [],
        }
        data.update(overrides)
        write_snapshot(snap_path, data)
        return snap_path

    def test_falls_back_to_file_scan_when_no_snapshot(self, run_script, tmp_path):
        """No snapshot -> backward compatible, file-scan based detection."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")
        (tmp_path / "claude-research.md").write_text("# Research")

        result = run_script(str(spec_file))
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True
        # File scan should detect research file
        assert output["resume_from_step"] == 8

    def test_writes_snapshot_after_successful_setup(self, run_script, tmp_path):
        """After setup completes, snapshot.json should exist."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")

        result = run_script(str(spec_file))
        assert result.returncode == 0

        snap_path = tmp_path / "snapshot.json"
        assert snap_path.exists()
        with open(snap_path) as f:
            snap = json.load(f)
        assert snap["version"] == 1
        assert snap["plugin"] == "deep-plan"
        assert snap["resume_step"] == 6  # New session starts at step 6

    def test_snapshot_flag_uses_snapshot_resume_step(self, run_script, tmp_path):
        """--snapshot flag with valid snapshot uses its resume_step."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")
        # Create files that would make file-scan return step 8
        (tmp_path / "claude-research.md").write_text("# Research")
        # But snapshot says step 12
        snap_path = self._write_valid_snapshot(tmp_path, resume_step=12)

        result = run_script(str(spec_file), extra_args=["--snapshot", snap_path])
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True
        assert output["resume_from_step"] == 12

    def test_falls_back_when_snapshot_stale(self, run_script, tmp_path):
        """Stale snapshot (missing artifact) falls back to file scan."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")
        (tmp_path / "claude-research.md").write_text("# Research")
        # Snapshot lists a missing artifact
        self._write_valid_snapshot(
            tmp_path,
            resume_step=14,
            completed_artifacts=["nonexistent-file.md"],
        )

        result = run_script(str(spec_file))
        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Should fall back to file scan, which detects research
        assert output["resume_from_step"] == 8

    def test_auto_discovers_snapshot_without_flag(self, run_script, tmp_path):
        """Valid snapshot in planning dir is used without --snapshot flag."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")
        # Snapshot says step 12, no --snapshot flag needed
        self._write_valid_snapshot(tmp_path, resume_step=12)

        result = run_script(str(spec_file))
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["resume_from_step"] == 12

    def test_writes_snapshot_for_resume_session(self, run_script, tmp_path):
        """Resume session writes snapshot with correct resume_step."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")
        (tmp_path / "claude-research.md").write_text("# Research")
        (tmp_path / "claude-interview.md").write_text("# Interview")

        result = run_script(str(spec_file))
        assert result.returncode == 0

        snap_path = tmp_path / "snapshot.json"
        assert snap_path.exists()
        with open(snap_path) as f:
            snap = json.load(f)
        # File scan finds research + interview -> step 10
        assert snap["resume_step"] == 10
        assert "claude-research.md" in snap["completed_artifacts"]
        assert "claude-interview.md" in snap["completed_artifacts"]

    def test_snapshot_and_file_scan_agree(self, run_script, tmp_path):
        """Snapshot resume_step matches file-scan inferred step."""
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Spec")
        (tmp_path / "claude-research.md").write_text("# Research")
        (tmp_path / "claude-interview.md").write_text("# Interview")
        (tmp_path / "claude-spec.md").write_text("# Spec doc")
        # Snapshot matches what file-scan would find (step 11)
        self._write_valid_snapshot(tmp_path, resume_step=11, resume_step_name="spec complete")

        result = run_script(str(spec_file))
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["resume_from_step"] == 11


class TestEnvValidationCaching:
    """Tests for env validation caching via snapshot."""

    @pytest.fixture
    def setup_mod(self):
        """Import the setup-planning-session module."""
        checks_path = str(Path(__file__).parent.parent / "scripts" / "checks")
        if checks_path not in sys.path:
            sys.path.insert(0, checks_path)
        from importlib import import_module
        return import_module("setup-planning-session")

    def _clear_env_keys(self, monkeypatch):
        """Clear all env validation keys."""
        for key in [
            "GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
        ]:
            monkeypatch.delenv(key, raising=False)

    def test_compute_env_key_hash_deterministic(self, setup_mod, monkeypatch):
        """Same env var set always produces the same hash."""
        self._clear_env_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        hash1 = setup_mod.compute_env_key_hash()
        hash2 = setup_mod.compute_env_key_hash()
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_compute_env_key_hash_differs_with_different_keys(self, setup_mod, monkeypatch):
        """Different env var combinations produce different hashes."""
        self._clear_env_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        hash_without_openrouter = setup_mod.compute_env_key_hash()

        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        hash_with_openrouter = setup_mod.compute_env_key_hash()

        assert hash_without_openrouter != hash_with_openrouter

    def test_compute_env_key_hash_ignores_values(self, setup_mod, monkeypatch):
        """Hash only depends on which keys are SET, not their values."""
        self._clear_env_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "value-a")
        hash_a = setup_mod.compute_env_key_hash()

        monkeypatch.setenv("GEMINI_API_KEY", "completely-different-value")
        hash_b = setup_mod.compute_env_key_hash()

        assert hash_a == hash_b

    def test_compute_env_key_hash_empty_string_treated_as_unset(self, setup_mod, monkeypatch):
        """Env var set to empty string is treated as unset."""
        self._clear_env_keys(monkeypatch)
        hash_none = setup_mod.compute_env_key_hash()

        monkeypatch.setenv("GEMINI_API_KEY", "")
        hash_empty = setup_mod.compute_env_key_hash()

        assert hash_none == hash_empty

    def test_should_skip_when_cache_valid(self, setup_mod):
        """Returns True when snapshot has valid env_validation matching session and hash."""
        snapshot = {
            "env_validation": {
                "validated": True,
                "session_id": "session-123",
                "env_key_hash": "abc123",
                "gemini_auth": "api_key",
                "openai_auth": True,
            }
        }
        assert setup_mod.should_skip_env_validation(snapshot, "session-123", "abc123") is True

    def test_should_not_skip_when_no_snapshot(self, setup_mod):
        """Returns False when snapshot is None."""
        assert setup_mod.should_skip_env_validation(None, "session-123", "abc123") is False

    def test_should_not_skip_when_no_env_validation(self, setup_mod):
        """Returns False when snapshot has no env_validation block."""
        snapshot = {"env_validation": None}
        assert setup_mod.should_skip_env_validation(snapshot, "session-123", "abc123") is False

    def test_should_not_skip_when_session_mismatch(self, setup_mod):
        """Returns False when session_id doesn't match."""
        snapshot = {
            "env_validation": {
                "validated": True,
                "session_id": "old-session",
                "env_key_hash": "abc123",
                "gemini_auth": "api_key",
                "openai_auth": True,
            }
        }
        assert setup_mod.should_skip_env_validation(snapshot, "new-session", "abc123") is False

    def test_should_not_skip_when_env_hash_mismatch(self, setup_mod):
        """Returns False when env_key_hash doesn't match."""
        snapshot = {
            "env_validation": {
                "validated": True,
                "session_id": "session-123",
                "env_key_hash": "old-hash",
                "gemini_auth": "api_key",
                "openai_auth": True,
            }
        }
        assert setup_mod.should_skip_env_validation(snapshot, "session-123", "new-hash") is False

    def test_should_not_skip_when_not_validated(self, setup_mod):
        """Returns False when validated is False (failed validation not cached)."""
        snapshot = {
            "env_validation": {
                "validated": False,
                "session_id": "session-123",
                "env_key_hash": "abc123",
                "gemini_auth": None,
                "openai_auth": False,
            }
        }
        assert setup_mod.should_skip_env_validation(snapshot, "session-123", "abc123") is False

    def test_run_and_cache_updates_snapshot_on_success(self, setup_mod, tmp_path, monkeypatch):
        """After successful validation, snapshot's env_validation is updated."""
        self._clear_env_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "fake")

        # Create a fake validate-env.sh that outputs valid JSON
        fake_plugin = tmp_path / "scripts" / "checks"
        fake_plugin.mkdir(parents=True)
        validate_script = fake_plugin / "validate-env.sh"
        validate_script.write_text(
            '#!/bin/bash\necho \'{"valid": true, "errors": [], "warnings": [], '
            '"gemini_auth": "api_key", "openai_auth": true}\''
        )
        validate_script.chmod(0o755)

        # Create snapshot file
        snapshot_path = tmp_path / "snapshot.json"
        write_snapshot(str(snapshot_path), {"version": 1, "env_validation": None})

        setup_mod.run_and_cache_env_validation(
            tmp_path, snapshot_path, "test-session"
        )

        # Verify snapshot was updated
        import json as json_mod
        with open(snapshot_path) as f:
            snap = json_mod.load(f)
        assert snap["env_validation"]["validated"] is True
        assert snap["env_validation"]["session_id"] == "test-session"
        assert snap["env_validation"]["gemini_auth"] == "api_key"
        assert snap["env_validation"]["openai_auth"] is True
        assert "env_key_hash" in snap["env_validation"]

    def test_run_and_cache_does_not_cache_on_failure(self, setup_mod, tmp_path, monkeypatch):
        """Failed validation (valid=false) is NOT cached in the snapshot."""
        self._clear_env_keys(monkeypatch)

        fake_plugin = tmp_path / "scripts" / "checks"
        fake_plugin.mkdir(parents=True)
        validate_script = fake_plugin / "validate-env.sh"
        validate_script.write_text(
            '#!/bin/bash\necho \'{"valid": false, "errors": ["Missing API key"], '
            '"warnings": [], "gemini_auth": null, "openai_auth": false}\'\nexit 1'
        )
        validate_script.chmod(0o755)

        snapshot_path = tmp_path / "snapshot.json"
        write_snapshot(str(snapshot_path), {"version": 1, "env_validation": None})

        result = setup_mod.run_and_cache_env_validation(
            tmp_path, snapshot_path, "test-session"
        )

        assert result["valid"] is False
        assert result["cached"] is False

        import json as json_mod
        with open(snapshot_path) as f:
            snap = json_mod.load(f)
        assert snap["env_validation"] is None

    def test_run_and_cache_does_not_cache_on_nonzero_exit(self, setup_mod, tmp_path, monkeypatch):
        """Non-zero exit code prevents caching even if JSON says valid=true."""
        self._clear_env_keys(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "fake")

        fake_plugin = tmp_path / "scripts" / "checks"
        fake_plugin.mkdir(parents=True)
        validate_script = fake_plugin / "validate-env.sh"
        validate_script.write_text(
            '#!/bin/bash\necho \'{"valid": true, "errors": [], "warnings": [], '
            '"gemini_auth": "api_key", "openai_auth": true}\'\nexit 1'
        )
        validate_script.chmod(0o755)

        snapshot_path = tmp_path / "snapshot.json"
        write_snapshot(str(snapshot_path), {"version": 1, "env_validation": None})

        setup_mod.run_and_cache_env_validation(
            tmp_path, snapshot_path, "test-session"
        )

        import json as json_mod
        with open(snapshot_path) as f:
            snap = json_mod.load(f)
        # Should NOT have cached because exit code was non-zero
        assert snap["env_validation"] is None

    def test_run_and_cache_returns_result_on_script_missing(self, setup_mod, tmp_path):
        """Returns error result when validate-env.sh doesn't exist."""
        result = setup_mod.run_and_cache_env_validation(
            tmp_path, tmp_path / "snapshot.json", "test-session"
        )
        assert result["valid"] is False
        assert result["cached"] is False
        assert len(result["errors"]) > 0
