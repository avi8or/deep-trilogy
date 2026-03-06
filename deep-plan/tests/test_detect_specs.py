"""Tests for detect_specs smart path detection helper."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = str(Path(__file__).resolve().parent.parent / "scripts" / "tools" / "detect_specs.py")

# Add tools dir for direct imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "tools"))
from detect_specs import SpecInfo, detect_specs, parse_manifest


def run_tool(*args):
    """Run detect_specs.py with given args and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, SCRIPT_PATH, *args],
        capture_output=True, text=True
    )


# ── detect_specs function tests ──────────────────────────────────────────


class TestSpecDiscovery:
    """Tests for finding spec.md files at various depths."""

    def test_finds_spec_in_cwd(self, tmp_path):
        """spec.md directly in search dir is found."""
        (tmp_path / "spec.md").write_text("# My Spec")
        results = detect_specs(str(tmp_path))
        assert len(results) == 1
        assert results[0].name == tmp_path.name

    def test_finds_specs_one_level_deep(self, tmp_path):
        """spec.md one level deep is found."""
        spec_dir = tmp_path / "03-feature"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Feature Spec")
        results = detect_specs(str(tmp_path))
        assert len(results) == 1
        assert results[0].name == "03-feature"

    def test_finds_specs_two_levels_deep(self, tmp_path):
        """spec.md at exactly 2 levels deep is found."""
        spec_dir = tmp_path / "plans" / "03-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Feature Spec")
        results = detect_specs(str(tmp_path))
        assert len(results) == 1
        assert results[0].name == "03-feature"

    def test_ignores_specs_beyond_two_levels(self, tmp_path):
        """spec.md at 3+ levels deep is NOT found."""
        spec_dir = tmp_path / "a" / "b" / "c"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Too Deep")
        results = detect_specs(str(tmp_path))
        assert len(results) == 0

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty list without errors."""
        results = detect_specs(str(tmp_path))
        assert results == []


# ── Status detection tests ───────────────────────────────────────────────


class TestStatusDetection:
    """Tests for planning status determination."""

    def test_status_unplanned(self, tmp_path):
        """No config or sections -> 'unplanned'."""
        spec_dir = tmp_path / "01-foo"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Foo")
        results = detect_specs(str(tmp_path))
        assert results[0].status == "unplanned"

    def test_status_in_progress(self, tmp_path):
        """deep_plan_config.json exists but no sections -> 'in_progress'."""
        spec_dir = tmp_path / "01-foo"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Foo")
        (spec_dir / "deep_plan_config.json").write_text("{}")
        results = detect_specs(str(tmp_path))
        assert results[0].status == "in_progress"

    def test_status_planned(self, tmp_path):
        """sections/index.md exists but no section files -> 'planned'."""
        spec_dir = tmp_path / "01-foo"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Foo")
        sections = spec_dir / "sections"
        sections.mkdir()
        (sections / "index.md").write_text("# Index")
        results = detect_specs(str(tmp_path))
        assert results[0].status == "planned"

    def test_status_sections_written(self, tmp_path):
        """section-*.md files exist -> 'sections_written'."""
        spec_dir = tmp_path / "01-foo"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Foo")
        sections = spec_dir / "sections"
        sections.mkdir()
        (sections / "index.md").write_text("# Index")
        (sections / "section-01-bar.md").write_text("# Bar")
        results = detect_specs(str(tmp_path))
        assert results[0].status == "sections_written"


# ── Manifest parsing tests ──────────────────────────────────────────────


class TestManifestParsing:
    """Tests for SPLIT_MANIFEST and dependency extraction."""

    def test_reads_split_manifest(self, tmp_path):
        """Extracts spec names from SPLIT_MANIFEST block."""
        (tmp_path / "project-manifest.md").write_text(
            "<!-- SPLIT_MANIFEST\n"
            "01-alpha\n"
            "02-beta\n"
            "03-gamma\n"
            "END_MANIFEST -->\n"
            "\n# Manifest\n"
        )
        spec_names, deps = parse_manifest(str(tmp_path))
        assert spec_names == ["01-alpha", "02-beta", "03-gamma"]

    def test_extracts_blocked_by_dependencies(self, tmp_path):
        """Extracts blocked-by dependency markers."""
        (tmp_path / "project-manifest.md").write_text(
            "<!-- SPLIT_MANIFEST\n"
            "01-alpha\n"
            "02-beta\n"
            "03-gamma\n"
            "END_MANIFEST -->\n"
            "\n"
            "03 ──blocked-by──> 01\n"
        )
        spec_names, deps = parse_manifest(str(tmp_path))
        assert "03-gamma" in deps
        assert deps["03-gamma"] == ["01-alpha"]

    def test_identifies_blocked_specs(self, tmp_path):
        """Specs with incomplete dependencies have populated blocked_by."""
        (tmp_path / "project-manifest.md").write_text(
            "<!-- SPLIT_MANIFEST\n"
            "01-alpha\n"
            "02-beta\n"
            "END_MANIFEST -->\n"
            "\n"
            "02 ──blocked-by──> 01\n"
        )
        alpha_dir = tmp_path / "01-alpha"
        alpha_dir.mkdir()
        (alpha_dir / "spec.md").write_text("# Alpha")

        beta_dir = tmp_path / "02-beta"
        beta_dir.mkdir()
        (beta_dir / "spec.md").write_text("# Beta")

        results = detect_specs(str(tmp_path))
        beta = next(r for r in results if r.name == "02-beta")
        assert "01-alpha" in beta.blocked_by

    def test_missing_manifest(self, tmp_path):
        """No project-manifest.md returns empty results without crashing."""
        spec_names, deps = parse_manifest(str(tmp_path))
        assert spec_names == []
        assert deps == {}

    def test_manifest_without_dependencies(self, tmp_path):
        """Manifest with SPLIT_MANIFEST but no dependency markers."""
        (tmp_path / "project-manifest.md").write_text(
            "<!-- SPLIT_MANIFEST\n"
            "01-alpha\n"
            "02-beta\n"
            "END_MANIFEST -->\n"
            "\n# Just content, no deps\n"
        )
        spec_names, deps = parse_manifest(str(tmp_path))
        assert spec_names == ["01-alpha", "02-beta"]
        assert deps == {}

    def test_ignores_benefits_markers(self, tmp_path):
        """benefits markers are not treated as hard dependencies."""
        (tmp_path / "project-manifest.md").write_text(
            "<!-- SPLIT_MANIFEST\n"
            "01-alpha\n"
            "02-beta\n"
            "END_MANIFEST -->\n"
            "\n"
            "02 ──benefits──> 01\n"
        )
        spec_names, deps = parse_manifest(str(tmp_path))
        assert deps == {}


# ── Integration tests ────────────────────────────────────────────────────


class TestIntegration:
    """Integration tests for sorted output and deduplication."""

    def test_returns_sorted_specs(self, tmp_path):
        """Multiple spec dirs are returned sorted by name."""
        for name in ["03-gamma", "01-alpha", "02-beta"]:
            d = tmp_path / name
            d.mkdir()
            (d / "spec.md").write_text(f"# {name}")
        results = detect_specs(str(tmp_path))
        names = [r.name for r in results]
        assert names == ["01-alpha", "02-beta", "03-gamma"]

    def test_deduplicates_spec_paths(self, tmp_path):
        """Same spec.md is not returned twice even if discoverable via multiple paths."""
        spec_dir = tmp_path / "01-alpha"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Alpha")
        (tmp_path / "link-to-alpha").symlink_to(spec_dir)
        results = detect_specs(str(tmp_path))
        assert len(results) == 1


# ── CLI tests ────────────────────────────────────────────────────────────


class TestCLI:
    """Tests for CLI invocation."""

    def test_cli_outputs_json(self, tmp_path):
        """CLI outputs valid JSON array."""
        spec_dir = tmp_path / "01-foo"
        spec_dir.mkdir()
        (spec_dir / "spec.md").write_text("# Foo")
        result = run_tool("--search-dir", str(tmp_path))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "01-foo"
        assert data[0]["status"] == "unplanned"

    def test_cli_empty_dir(self, tmp_path):
        """CLI outputs empty array for directory with no specs."""
        result = run_tool("--search-dir", str(tmp_path))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []
