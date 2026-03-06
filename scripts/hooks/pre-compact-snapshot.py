#!/usr/bin/env python3
"""Write a final snapshot before context compaction.

This hook fires on PreCompact (both manual and auto). It finds the active
snapshot and updates it with a marker so the post-compact or post-clear
resume knows the snapshot was saved just before compaction.

This is the safety net: even if the SKILL.md didn't get a chance to write
a snapshot at a natural checkpoint, this hook ensures one exists.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Set up imports for snapshot module
_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


def discover_snapshot_path() -> str | None:
    """Find snapshot.json by checking CWD and walking up to 3 parent levels."""
    cwd = Path(os.getcwd())

    direct = cwd / "snapshot.json"
    if direct.is_file():
        return str(direct)

    config_names = {
        "deep_plan_config.json": "planning_dir",
        "deep_implement_config.json": "state_dir",
    }

    search_dir = cwd
    for _ in range(4):
        for config_name, dir_key in config_names.items():
            config_path = search_dir / config_name
            if config_path.is_file():
                try:
                    with open(config_path) as f:
                        config = json.load(f)
                    target_dir = config.get(dir_key)
                    if target_dir:
                        target_path = Path(target_dir)
                        if not target_path.is_absolute():
                            target_path = config_path.parent / target_path
                        snapshot = target_path / "snapshot.json"
                        if snapshot.is_file():
                            return str(snapshot)
                except (json.JSONDecodeError, OSError, KeyError):
                    continue
        parent = search_dir.parent
        if parent == search_dir:
            break
        search_dir = parent

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    trigger = payload.get("trigger", "unknown")

    try:
        snapshot_path = discover_snapshot_path()
        if not snapshot_path:
            return 0

        with open(snapshot_path) as f:
            snapshot = json.load(f)

        snapshot["pre_compact"] = {
            "trigger": trigger,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Atomic write
        import tempfile
        dir_path = os.path.dirname(snapshot_path)
        with tempfile.NamedTemporaryFile(
            dir=dir_path, mode="w", suffix=".tmp", delete=False
        ) as tf:
            json.dump(snapshot, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tf.name, snapshot_path)

    except Exception:
        pass  # Never crash the hook

    return 0


if __name__ == "__main__":
    sys.exit(main())
