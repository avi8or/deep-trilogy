#!/usr/bin/env python3
"""Update snapshot file at workflow milestones.

Called by SKILL.md to record step progress, completed artifacts,
key decisions, section progress, and task IDs.

Usage:
    uv run update_snapshot.py --snapshot-path <path> --step <n> --step-name <name> [options]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path for lib imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.snapshot import read_snapshot, write_snapshot

_DEFAULT_SNAPSHOT_TEMPLATE = json.dumps({
    "version": 1,
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
})


def _fresh_snapshot() -> dict:
    """Return a deep copy of the default snapshot template."""
    return json.loads(_DEFAULT_SNAPSHOT_TEMPLATE)


def validate_artifact_path(path: str) -> bool:
    """Return True if path is a safe relative path."""
    if ".." in Path(path).parts:
        return False
    if path.startswith("/"):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Update snapshot at workflow milestones")
    parser.add_argument("--snapshot-path", required=True, help="Path to snapshot.json")
    parser.add_argument("--step", required=True, type=int, help="Current step number")
    parser.add_argument("--step-name", required=True, help="Step name")
    parser.add_argument("--artifact", action="append", default=[], help="Completed artifact path (repeatable)")
    parser.add_argument("--key-decision", action="append", default=[], help="Key decision (repeatable)")
    parser.add_argument("--section-progress", help="Format: completed/total")
    parser.add_argument("--task-id", help="Current task ID")
    args = parser.parse_args()

    # Validate artifact paths before any writes
    for artifact in args.artifact:
        if not validate_artifact_path(artifact):
            print(f"Error: invalid artifact path: {artifact}", file=sys.stderr)
            return 1

    # Read existing or start fresh
    data = read_snapshot(args.snapshot_path)
    if data is None:
        if Path(args.snapshot_path).exists():
            print("Warning: corrupt snapshot, starting fresh", file=sys.stderr)
        data = _fresh_snapshot()

    # Update step fields
    data["resume_step"] = args.step
    data["resume_step_name"] = args.step_name
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Append artifacts (deduplicate)
    if args.artifact:
        existing = set(data.get("completed_artifacts", []))
        for a in args.artifact:
            existing.add(a)
        data["completed_artifacts"] = sorted(existing)

    # Append key decisions
    if args.key_decision:
        decisions = data.get("key_decisions", [])
        decisions.extend(args.key_decision)
        data["key_decisions"] = decisions

    # Parse section progress
    if args.section_progress:
        try:
            completed, total = args.section_progress.split("/")
            sp = data.get("section_progress") or {}
            sp["completed"] = int(completed)
            sp["total"] = int(total)
            data["section_progress"] = sp
        except ValueError:
            print(f"Error: invalid section-progress format: {args.section_progress}", file=sys.stderr)
            return 1

    # Update task ID
    if args.task_id:
        ts = data.get("task_summary") or {"total": 0, "completed": 0, "current_task_id": ""}
        ts["current_task_id"] = args.task_id
        data["task_summary"] = ts

    try:
        write_snapshot(args.snapshot_path, data)
    except Exception as e:
        print(f"Error writing snapshot: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
