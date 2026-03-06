# tests/test_create_split_dirs.py
"""Tests for create-split-dirs.py script."""

import json
import subprocess
from pathlib import Path

import pytest


def run_create_split_dirs_with_rc(planning_dir: Path) -> tuple[dict, int]:
    """Helper to run create-split-dirs.py and return parsed output + exit code."""
    result = subprocess.run(
        [
            "uv", "run", "scripts/checks/create-split-dirs.py",
            "--planning-dir", str(planning_dir)
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent
    )
    return json.loads(result.stdout), result.returncode


def run_create_split_dirs(planning_dir: Path) -> dict:
    """Helper to run create-split-dirs.py and return parsed output."""
    output, _ = run_create_split_dirs_with_rc(planning_dir)
    return output


@pytest.mark.integration
class TestCreateSplitDirs:
    """Integration tests for create-split-dirs.py."""

    def test_creates_directories_from_manifest(self, tmp_path):
        """Should create directories listed in manifest."""
        # Create manifest with valid SPLIT_MANIFEST block
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-backend
02-frontend
END_MANIFEST -->

# Project Manifest
""")

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is True
        assert output["created"] == ["01-backend", "02-frontend"]
        assert output["skipped"] == []
        assert (tmp_path / "01-backend").is_dir()
        assert (tmp_path / "02-frontend").is_dir()

    def test_skips_existing_directories(self, tmp_path):
        """Should skip directories that already exist."""
        # Create manifest
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-backend
02-frontend
END_MANIFEST -->""")

        # Pre-create one directory
        (tmp_path / "01-backend").mkdir()

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is True
        assert output["created"] == ["02-frontend"]
        assert output["skipped"] == ["01-backend"]

    def test_all_directories_exist(self, tmp_path):
        """Should report all skipped when all dirs exist."""
        # Create manifest
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-backend
02-frontend
END_MANIFEST -->""")

        # Pre-create all directories
        (tmp_path / "01-backend").mkdir()
        (tmp_path / "02-frontend").mkdir()

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is True
        assert output["created"] == []
        assert output["skipped"] == ["01-backend", "02-frontend"]

    def test_fails_without_manifest(self, tmp_path):
        """Should fail when manifest doesn't exist."""
        output = run_create_split_dirs(tmp_path)

        assert output["success"] is False
        assert "not found" in output["error"].lower() or "errors" in output

    def test_fails_with_invalid_manifest(self, tmp_path):
        """Should fail when manifest has invalid format."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("# No SPLIT_MANIFEST block here")

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is False
        assert "errors" in output or "error" in output

    def test_fails_with_invalid_split_names(self, tmp_path):
        """Should fail when manifest has invalid split names."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
1-bad-prefix
END_MANIFEST -->""")

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is False
        assert "errors" in output

    def test_fails_with_nonexistent_planning_dir(self, tmp_path):
        """Should fail when planning directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"

        output = run_create_split_dirs(nonexistent)

        assert output["success"] is False
        assert "not found" in output["error"].lower()

    def test_single_split_project(self, tmp_path):
        """Should handle single-split projects."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-my-project
END_MANIFEST -->""")

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is True
        assert output["created"] == ["01-my-project"]
        assert (tmp_path / "01-my-project").is_dir()

    def test_returns_manifest_splits_list(self, tmp_path):
        """Should return full manifest_splits list in output."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-backend
02-frontend
03-shared
END_MANIFEST -->""")

        output = run_create_split_dirs(tmp_path)

        assert output["success"] is True
        assert output["manifest_splits"] == ["01-backend", "02-frontend", "03-shared"]

    def test_json_output_format(self, tmp_path):
        """Should return valid JSON with expected fields."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-backend
END_MANIFEST -->""")

        output = run_create_split_dirs(tmp_path)

        assert "success" in output
        assert "created" in output
        assert "skipped" in output
        assert "manifest_splits" in output
        assert "message" in output

    def test_fails_when_file_exists_at_directory_path(self, tmp_path):
        """Should fail with error when a file exists where a directory should be created."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-backend
02-frontend
END_MANIFEST -->""")

        # Place a regular file where 02-frontend directory should be
        (tmp_path / "02-frontend").write_text("I am a file, not a directory")

        output, rc = run_create_split_dirs_with_rc(tmp_path)

        assert output["success"] is False
        assert "02-frontend" in output["error"]
        assert str(tmp_path / "02-frontend") in output["error"]
        assert rc != 0

    def test_file_at_path_reports_created_before_failure(self, tmp_path):
        """Should include 'created' list of directories made before hitting the blocking file."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-setup
02-models
03-routes
04-tests
05-api
END_MANIFEST -->""")

        # Place a regular file at 05-api
        (tmp_path / "05-api").write_text("blocking file")

        output, rc = run_create_split_dirs_with_rc(tmp_path)

        assert output["success"] is False
        assert output["created"] == ["01-setup", "02-models", "03-routes", "04-tests"]
        # Verify the four directories actually exist on disk
        for name in ["01-setup", "02-models", "03-routes", "04-tests"]:
            assert (tmp_path / name).is_dir()

    def test_file_at_path_stops_creating_after_failure(self, tmp_path):
        """Should not create directories after the blocking file (fail-fast)."""
        manifest = tmp_path / "project-manifest.md"
        manifest.write_text("""<!-- SPLIT_MANIFEST
01-setup
02-models
03-routes
04-tests
05-api
06-deploy
END_MANIFEST -->""")

        # Place a regular file at 05-api
        (tmp_path / "05-api").write_text("blocking file")

        output, rc = run_create_split_dirs_with_rc(tmp_path)

        assert output["success"] is False
        # 06-deploy should NOT have been created
        assert not (tmp_path / "06-deploy").exists()
