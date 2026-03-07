#!/usr/bin/env python3
"""Discover active deep-trilogy sessions for /deep-resume.

Searches CWD and parent directories for snapshot files and plugin config files,
determines which plugin was active and what step to resume from.

Output: JSON to stdout with session discovery results.

Possible output shapes:
  {"status": "found", "source": "snapshot", "plugin": "deep-implement", ...}
  {"status": "found", "source": "artifact-scan", "plugin": "deep-plan", ...}
  {"status": "multiple", "sessions": [...]}
  {"status": "not_found", "searched": [...]}

Usage:
    uv run --project {plugin_root}/deep-plan \
        {plugin_root}/scripts/tools/discover-session.py [--cwd PATH]
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_VERSION = 1

CONFIG_FILES = {
    "deep_plan_config.json": "deep-plan",
    "deep_implement_config.json": "deep-implement",
    "deep_project_session.json": "deep-project",
}


# ---------------------------------------------------------------------------
# Snapshot helpers (inlined from deep-plan/scripts/lib/snapshot.py)
# ---------------------------------------------------------------------------


def read_snapshot(path: str) -> dict | None:
    """Read and parse snapshot.json. Returns None if missing or corrupt."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def validate_snapshot(snapshot: dict, working_dir: str) -> bool:
    """Check snapshot version and artifact freshness."""
    if snapshot.get("version") != SNAPSHOT_VERSION:
        return False

    artifacts = snapshot.get("completed_artifacts", [])
    if not artifacts:
        return True

    try:
        updated_at = datetime.fromisoformat(snapshot["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return False

    for rel_path in artifacts:
        if ".." in Path(rel_path).parts or os.path.isabs(rel_path):
            continue
        full_path = os.path.join(working_dir, rel_path)
        if not os.path.exists(full_path):
            return False
        mtime = os.path.getmtime(full_path)
        file_time = datetime.fromtimestamp(mtime, tz=timezone.utc)
        if file_time > updated_at:
            return False

    return True


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_configs(cwd: Path) -> list[dict]:
    """Search CWD + 3 parent levels for config files and snapshots."""
    results = []
    search_dir = cwd

    for depth in range(4):
        # Check for snapshot.json directly
        for snapshot_rel in ("snapshot.json", "implementation/snapshot.json"):
            snapshot_path = search_dir / snapshot_rel
            if snapshot_path.is_file():
                results.append({
                    "type": "snapshot",
                    "path": str(snapshot_path),
                    "depth": depth,
                })

        # Check for config files
        for config_name, plugin in CONFIG_FILES.items():
            for config_rel in (config_name, f"implementation/{config_name}"):
                config_path = search_dir / config_rel
                if config_path.is_file():
                    results.append({
                        "type": "config",
                        "plugin": plugin,
                        "path": str(config_path),
                        "depth": depth,
                    })

        parent = search_dir.parent
        if parent == search_dir:
            break
        search_dir = parent

    return results


# ---------------------------------------------------------------------------
# Snapshot resume (fast path)
# ---------------------------------------------------------------------------


def try_snapshot_resume(snapshot_path: str) -> dict | None:
    """Try to build resume info from a snapshot file."""
    snapshot = read_snapshot(snapshot_path)
    if snapshot is None:
        return None

    working_dir = str(Path(snapshot_path).parent)
    valid = validate_snapshot(snapshot, working_dir)

    plugin = snapshot.get("plugin", "")
    if plugin not in ("deep-plan", "deep-implement", "deep-project"):
        return None

    # Build progress string
    task = snapshot.get("task_summary") or {}
    section = snapshot.get("section_progress")
    progress_parts = []
    if task.get("total"):
        progress_parts.append(f"{task.get('completed', 0)}/{task['total']} tasks")
    if section and section.get("total"):
        progress_parts.append(
            f"{section.get('completed', 0)}/{section['total']} sections"
        )

    result = {
        "status": "found",
        "source": "snapshot",
        "snapshot_valid": valid,
        "plugin": plugin,
        "resume_step": snapshot.get("resume_step", 0),
        "resume_step_name": snapshot.get("resume_step_name", ""),
        "progress": ", ".join(progress_parts) if progress_parts else "unknown",
        "git_branch": snapshot.get("git_branch", ""),
        "working_dir": working_dir,
        "snapshot_path": snapshot_path,
        "complete": False,
    }

    # Add plugin-specific paths from sibling config if available
    _enrich_from_config(result, working_dir, plugin)

    return result


def _enrich_from_config(result: dict, working_dir: str, plugin: str) -> None:
    """Add sections_dir/target_dir etc. from the config file next to the snapshot."""
    config_map = {
        "deep-plan": "deep_plan_config.json",
        "deep-implement": "deep_implement_config.json",
        "deep-project": "deep_project_session.json",
    }
    config_name = config_map.get(plugin)
    if not config_name:
        return

    config_path = os.path.join(working_dir, config_name)
    try:
        with open(config_path) as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return

    if plugin == "deep-implement":
        result["sections_dir"] = config.get("sections_dir", "")
        result["target_dir"] = config.get("target_dir", "")
    elif plugin == "deep-plan":
        result["planning_dir"] = config.get("planning_dir", working_dir)


# ---------------------------------------------------------------------------
# Artifact scanners (fallback path)
# ---------------------------------------------------------------------------


def scan_plan_artifacts(config_path: str) -> dict:
    """Scan deep-plan artifacts to determine resume state.

    Mirrors logic from setup-planning-session.py:scan_planning_files()
    and infer_resume_step().
    """
    planning_dir = str(Path(config_path).parent)
    d = Path(planning_dir)

    files = {
        "research": (d / "claude-research.md").exists(),
        "interview": (d / "claude-interview.md").exists(),
        "spec": (d / "claude-spec.md").exists(),
        "plan": (d / "claude-plan.md").exists(),
        "integration_notes": (d / "claude-integration-notes.md").exists(),
        "plan_tdd": (d / "claude-plan-tdd.md").exists(),
        "reviews": list((d / "reviews").glob("*.md")) if (d / "reviews").exists() else [],
        "sections": list((d / "sections").glob("section-*.md")) if (d / "sections").exists() else [],
        "sections_index": (d / "sections" / "index.md").exists(),
    }

    sections_done = len(files["sections"])

    # Infer resume step — highest artifact wins, with prerequisite checks
    if files["sections_index"]:
        if not files["plan_tdd"]:
            return _plan_result(planning_dir, 16, "missing prerequisite: TDD plan", files, sections_done)
        if sections_done > 0:
            return _plan_result(planning_dir, None, "complete", files, sections_done)
        return _plan_result(planning_dir, 19, "index created, generating sections", files, 0)

    if files["sections"] and not files["sections_index"]:
        if not files["plan_tdd"]:
            return _plan_result(planning_dir, 16, "missing prerequisite: TDD plan", files, sections_done)
        return _plan_result(planning_dir, 18, "section files exist but no index", files, sections_done)

    if files["plan_tdd"]:
        return _plan_result(planning_dir, 17, "TDD plan complete", files, 0)
    if files["integration_notes"]:
        if not files["plan"]:
            return _plan_result(planning_dir, 11, "missing prerequisite: plan", files, 0)
        return _plan_result(planning_dir, 15, "feedback integrated", files, 0)
    if files["reviews"]:
        if not files["plan"]:
            return _plan_result(planning_dir, 11, "missing prerequisite: plan", files, 0)
        return _plan_result(planning_dir, 14, "external review complete", files, 0)
    if files["plan"]:
        if not files["spec"]:
            return _plan_result(planning_dir, 10, "missing prerequisite: spec", files, 0)
        return _plan_result(planning_dir, 12, "plan complete", files, 0)
    if files["spec"]:
        if not files["interview"]:
            return _plan_result(planning_dir, 9, "missing prerequisite: interview", files, 0)
        return _plan_result(planning_dir, 11, "spec complete", files, 0)
    if files["interview"]:
        return _plan_result(planning_dir, 10, "interview complete", files, 0)
    if files["research"]:
        return _plan_result(planning_dir, 8, "research complete", files, 0)

    return _plan_result(planning_dir, 6, "fresh start", files, 0)


def _plan_result(
    planning_dir: str,
    step: int | None,
    description: str,
    files: dict,
    sections_done: int,
) -> dict:
    artifact_count = sum(
        1
        for k in ("research", "interview", "spec", "plan", "integration_notes", "plan_tdd")
        if files.get(k)
    )

    if sections_done > 0:
        progress = f"{sections_done} sections written, {artifact_count}/6 artifacts"
    else:
        progress = f"{artifact_count}/6 artifacts"

    return {
        "status": "found",
        "source": "artifact-scan",
        "plugin": "deep-plan",
        "resume_step": step,
        "resume_step_name": description,
        "progress": progress,
        "git_branch": _get_git_branch(),
        "working_dir": planning_dir,
        "snapshot_path": None,
        "complete": step is None,
    }


def scan_implement_artifacts(config_path: str) -> dict:
    """Scan deep-implement artifacts to determine resume state.

    Mirrors logic from setup_implementation_session.py:infer_session_state()
    and detect_section_review_state().
    """
    try:
        with open(config_path) as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"status": "error", "error": f"Cannot read {config_path}"}

    state_dir = Path(config_path).parent
    sections = config.get("sections", [])
    sections_state = config.get("sections_state", {})

    # Count completed sections (status == "complete" with commit_hash)
    completed = []
    for section in sections:
        s = sections_state.get(section, {})
        if s.get("status") == "complete" and s.get("commit_hash"):
            completed.append(section)

    base = {
        "source": "artifact-scan",
        "plugin": "deep-implement",
        "progress": f"{len(completed)}/{len(sections)} sections",
        "git_branch": _get_git_branch(),
        "working_dir": str(state_dir),
        "sections_dir": config.get("sections_dir", ""),
        "target_dir": config.get("target_dir", ""),
        "snapshot_path": None,
    }

    if len(completed) >= len(sections) and sections:
        return {
            **base,
            "status": "found",
            "resume_step": None,
            "resume_step_name": "all sections complete",
            "complete": True,
        }

    # Find first incomplete section
    resume_from = None
    for section in sections:
        if section not in completed:
            resume_from = section
            break

    # Detect sub-step within the resume section
    sub_step = "implement"
    if resume_from:
        section_num = resume_from.split("-")[1] if "-" in resume_from else "00"
        cr_dir = state_dir / "code_review"
        if (cr_dir / f"section-{section_num}-interview.md").exists():
            sub_step = "apply_fixes"
        elif (cr_dir / f"section-{section_num}-review.md").exists():
            sub_step = "interview"
        elif (cr_dir / f"section-{section_num}-diff.md").exists():
            sub_step = "review"

    return {
        **base,
        "status": "found",
        "resume_step": "setup-implementation",
        "resume_step_name": f"{resume_from} ({sub_step})" if resume_from else "unknown",
        "complete": False,
        "resume_section": resume_from,
        "resume_sub_step": sub_step,
    }


def scan_project_artifacts(config_path: str) -> dict:
    """Scan deep-project artifacts to determine resume state.

    Mirrors logic from deep-project/scripts/lib/state.py:detect_state().
    """
    project_dir = str(Path(config_path).parent)
    d = Path(project_dir)

    interview_exists = (d / "deep_project_interview.md").exists()
    manifest_exists = (d / "project-manifest.md").exists()

    # Find split directories (NN-name pattern)
    split_pattern = re.compile(r"^\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
    splits = sorted([
        item.name
        for item in d.iterdir()
        if item.is_dir() and split_pattern.match(item.name)
    ])

    splits_with_specs = [s for s in splits if (d / s / "spec.md").exists()]

    # Determine resume step
    if splits and len(splits_with_specs) == len(splits):
        step, desc, complete = 7, "all specs written", True
    elif splits:
        missing = len(splits) - len(splits_with_specs)
        step, desc, complete = 6, f"{missing} specs remaining", False
    elif manifest_exists:
        step, desc, complete = 4, "manifest created, awaiting confirmation", False
    elif interview_exists:
        step, desc, complete = 2, "interview complete", False
    else:
        step, desc, complete = 1, "fresh start", False

    if splits:
        progress = f"{len(splits_with_specs)}/{len(splits)} specs"
    elif manifest_exists:
        progress = "manifest created"
    elif interview_exists:
        progress = "interview done"
    else:
        progress = "not started"

    return {
        "status": "found",
        "source": "artifact-scan",
        "plugin": "deep-project",
        "resume_step": step if not complete else None,
        "resume_step_name": desc,
        "progress": progress,
        "git_branch": _get_git_branch(),
        "working_dir": project_dir,
        "snapshot_path": None,
        "complete": complete,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_git_branch() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Discover sessions and output JSON."""
    cwd = Path(os.getcwd())

    # Parse --cwd override
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--cwd" and i + 1 < len(args):
            cwd = Path(args[i + 1]).resolve()
            break

    # Step 1: Discover config files and snapshots
    discovered = discover_configs(cwd)

    if not discovered:
        print(json.dumps({
            "status": "not_found",
            "searched": [str(cwd)],
            "message": "No deep-trilogy session artifacts found",
        }))
        return 0

    # Step 2: Try snapshots first (closest to CWD wins)
    snapshots = sorted(
        [d for d in discovered if d["type"] == "snapshot"],
        key=lambda d: d["depth"],
    )

    for snap in snapshots:
        result = try_snapshot_resume(snap["path"])
        if result is not None:
            print(json.dumps(result, indent=2))
            return 0

    # Step 3: Fall back to config-based artifact scanning
    configs = sorted(
        [d for d in discovered if d["type"] == "config"],
        key=lambda d: d["depth"],
    )

    if not configs:
        print(json.dumps({
            "status": "not_found",
            "searched": [str(cwd)],
            "message": "Found snapshot(s) but all were invalid; no config files found",
        }))
        return 0

    # Group by plugin, take closest (lowest depth) for each
    by_plugin: dict[str, dict] = {}
    for cfg in configs:
        plugin = cfg["plugin"]
        if plugin not in by_plugin:
            by_plugin[plugin] = cfg

    # Multiple plugins detected — scan all, return choices
    if len(by_plugin) > 1:
        sessions = []
        for plugin, cfg in by_plugin.items():
            if plugin == "deep-plan":
                sessions.append(scan_plan_artifacts(cfg["path"]))
            elif plugin == "deep-implement":
                sessions.append(scan_implement_artifacts(cfg["path"]))
            elif plugin == "deep-project":
                sessions.append(scan_project_artifacts(cfg["path"]))
        print(json.dumps({"status": "multiple", "sessions": sessions}, indent=2))
        return 0

    # Single plugin — scan its artifacts
    cfg = list(by_plugin.values())[0]
    if cfg["plugin"] == "deep-plan":
        result = scan_plan_artifacts(cfg["path"])
    elif cfg["plugin"] == "deep-implement":
        result = scan_implement_artifacts(cfg["path"])
    elif cfg["plugin"] == "deep-project":
        result = scan_project_artifacts(cfg["path"])
    else:
        result = {"status": "error", "error": f"Unknown plugin: {cfg['plugin']}"}

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
