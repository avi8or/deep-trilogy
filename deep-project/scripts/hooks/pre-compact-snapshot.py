#!/usr/bin/env python3
"""Write a timestamp to session state before context compaction.

This hook fires on PreCompact. It finds the active session state file
and marks it with a pre_compact timestamp so resume knows the state
was saved just before compaction hit.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def discover_session_state() -> str | None:
    """Find deep_project_session.json by checking CWD and walking up."""
    cwd = Path(os.getcwd())

    search_dir = cwd
    for _ in range(4):
        state_path = search_dir / "deep_project_session.json"
        if state_path.is_file():
            return str(state_path)

        try:
            for child in search_dir.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    child_state = child / "deep_project_session.json"
                    if child_state.is_file():
                        return str(child_state)
        except OSError:
            pass

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
        state_path = discover_session_state()
        if not state_path:
            return 0

        with open(state_path) as f:
            state = json.load(f)

        state["pre_compact"] = {
            "trigger": trigger,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Atomic write
        import tempfile
        dir_path = os.path.dirname(state_path)
        with tempfile.NamedTemporaryFile(
            dir=dir_path, mode="w", suffix=".tmp", delete=False
        ) as tf:
            json.dump(state, tf, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tf.name, state_path)

    except Exception:
        pass  # Never crash the hook

    return 0


if __name__ == "__main__":
    sys.exit(main())
