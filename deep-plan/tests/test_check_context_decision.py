"""Tests for check-context-decision.py script."""

import pytest
import subprocess
import json
import os
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from lib.config import create_session_config


class TestCheckContextDecision:
    """Tests for check-context-decision.py script."""

    @pytest.fixture
    def script_path(self):
        """Return path to check-context-decision.py."""
        return Path(__file__).parent.parent / "scripts" / "checks" / "check-context-decision.py"

    @pytest.fixture
    def plugin_root(self):
        """Return path to plugin root."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def context_file(self, tmp_path):
        """Provide a temp context file and set DEEP_CONTEXT_FILE env var."""
        path = tmp_path / "claude-context-pct"
        return path

    @pytest.fixture
    def planning_dir_with_config(self, tmp_path, plugin_root):
        """Create a planning directory with session config."""
        planning_dir = tmp_path / "planning"
        planning_dir.mkdir()

        create_session_config(
            planning_dir=planning_dir,
            plugin_root=str(plugin_root),
            initial_file=str(planning_dir / "spec.md"),
        )

        return planning_dir

    @pytest.fixture
    def run_script(self, script_path, context_file):
        """Factory fixture to run check-context-decision.py."""
        def _run(planning_dir: Path, upcoming_operation: str, context_pct: int | None = None, config_override: dict = None, timeout=10):
            env = os.environ.copy()
            env["DEEP_CONTEXT_FILE"] = str(context_file)

            if context_pct is not None:
                context_file.write_text(str(context_pct))
            elif context_file.exists():
                context_file.unlink()

            cmd = [
                "uv", "run", str(script_path),
                "--planning-dir", str(planning_dir),
                "--upcoming-operation", upcoming_operation
            ]

            if config_override:
                config_path = planning_dir / "deep_plan_config.json"
                current_config = json.loads(config_path.read_text())
                for key, value in config_override.items():
                    if isinstance(value, dict) and key in current_config:
                        current_config[key] = {**current_config.get(key, {}), **value}
                    else:
                        current_config[key] = value
                config_path.write_text(json.dumps(current_config, indent=2))

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return result
        return _run

    # --- Basic behavior ---

    def test_prompt_includes_operation_name(self, run_script, planning_dir_with_config):
        """Should include upcoming operation in prompt message."""
        result = run_script(planning_dir_with_config, "Split Plan Into Sections", context_pct=65)

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert "Split Plan Into Sections" in output["prompt"]["message"]

    def test_prompt_options_format(self, run_script, planning_dir_with_config):
        """Should return properly formatted prompt options."""
        result = run_script(planning_dir_with_config, "Test Operation", context_pct=60)

        assert result.returncode == 0
        output = json.loads(result.stdout)

        options = output["prompt"]["options"]
        assert len(options) == 2

        for opt in options:
            assert "label" in opt
            assert "description" in opt

        labels = [opt["label"] for opt in options]
        assert "Continue" in labels
        assert "/clear + re-run" in labels

    def test_missing_config_defaults_to_prompt(self, script_path, tmp_path):
        """Should default to prompting if config can't be loaded."""
        planning_dir = tmp_path / "no_config"
        planning_dir.mkdir()
        context_file = tmp_path / "ctx-pct"

        env = os.environ.copy()
        env["DEEP_CONTEXT_FILE"] = str(context_file)

        result = subprocess.run(
            [
                "uv", "run", str(script_path),
                "--planning-dir", str(planning_dir),
                "--upcoming-operation", "Test"
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["action"] == "prompt"
        assert output["check_enabled"] is True

    # --- Context percentage in output ---

    def test_context_pct_included_in_output(self, run_script, planning_dir_with_config):
        """Should include context_pct field in JSON output."""
        result = run_script(planning_dir_with_config, "Test", context_pct=72)

        output = json.loads(result.stdout)
        assert output["context_pct"] == 72

    def test_context_pct_null_when_file_missing(self, run_script, planning_dir_with_config):
        """Should return context_pct as null when file doesn't exist."""
        result = run_script(planning_dir_with_config, "Test", context_pct=None)

        output = json.loads(result.stdout)
        assert output["context_pct"] is None

    def test_prompt_message_shows_percentage(self, run_script, planning_dir_with_config):
        """Should display context percentage in the prompt message."""
        result = run_script(planning_dir_with_config, "External LLM Review", context_pct=65)

        output = json.loads(result.stdout)
        assert "Context usage: 65%" in output["prompt"]["message"]

    def test_prompt_message_shows_unknown_when_missing(self, run_script, planning_dir_with_config):
        """Should show 'unknown' when context file doesn't exist."""
        result = run_script(planning_dir_with_config, "Test", context_pct=None)

        output = json.loads(result.stdout)
        assert "unknown" in output["prompt"]["message"]

    # --- Threshold logic ---

    def test_skips_below_50_pct(self, run_script, planning_dir_with_config):
        """Should skip prompt when context is below 50%."""
        result = run_script(planning_dir_with_config, "Test", context_pct=35)

        output = json.loads(result.stdout)
        assert output["action"] == "skip"
        assert output["context_pct"] == 35

    def test_prompts_at_50_pct(self, run_script, planning_dir_with_config):
        """Should prompt at exactly 50%."""
        result = run_script(planning_dir_with_config, "Test", context_pct=50)

        output = json.loads(result.stdout)
        assert output["action"] == "prompt"
        assert output["context_pct"] == 50

    def test_prompts_at_70_pct(self, run_script, planning_dir_with_config):
        """Should prompt at 70%."""
        result = run_script(planning_dir_with_config, "Test", context_pct=70)

        output = json.loads(result.stdout)
        assert output["action"] == "prompt"

    def test_high_context_warning_at_85_pct(self, run_script, planning_dir_with_config):
        """Should include HIGH warning in prompt at >= 85%."""
        result = run_script(planning_dir_with_config, "Test", context_pct=90)

        output = json.loads(result.stdout)
        assert output["action"] == "prompt"
        assert "HIGH" in output["prompt"]["message"]
        assert "/clear recommended" in output["prompt"]["message"]

    def test_high_context_overrides_disabled_checks(self, run_script, planning_dir_with_config):
        """Should still prompt at >= 85% even when checks are disabled."""
        result = run_script(
            planning_dir_with_config,
            "Test",
            context_pct=90,
            config_override={"context": {"check_enabled": False}}
        )

        output = json.loads(result.stdout)
        assert output["action"] == "prompt"
        assert "HIGH" in output["prompt"]["message"]

    def test_check_disabled_skips_below_85(self, run_script, planning_dir_with_config):
        """Should skip when check_enabled is false and context < 85%."""
        result = run_script(
            planning_dir_with_config,
            "Test",
            context_pct=60,
            config_override={"context": {"check_enabled": False}}
        )

        output = json.loads(result.stdout)
        assert output["action"] == "skip"
        assert output["check_enabled"] is False
