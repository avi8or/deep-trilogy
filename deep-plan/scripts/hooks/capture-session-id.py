#!/usr/bin/env python3
"""Capture session_id and plugin_root, expose via Claude's context.

This hook reads session_id from the JSON payload on stdin and:
1. Outputs it to stdout as additionalContext (Claude sees this directly)
2. Also captures CLAUDE_PLUGIN_ROOT as DEEP_PLUGIN_ROOT (for SKILL.md path resolution)
3. Optionally writes to CLAUDE_ENV_FILE if available (fallback for bash)
4. Discovers and surfaces snapshot.json resume state if available

The additionalContext approach is primary because:
- CLAUDE_ENV_FILE is unreliable (empty string bug, not sourced on resume)
- After /clear, env var has OLD session_id while hook gets NEW one
- additionalContext bypasses these issues by flowing through Claude's context
- CLAUDE_PLUGIN_ROOT is only available in hooks.json, not in SKILL.md files

Usage:
    This script is called automatically by Claude Code when configured
    as a SessionStart hook in hooks/hooks.json (for plugins):

    {
      "hooks": {
        "SessionStart": [
          {
            "hooks": [
              {
                "type": "command",
                "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hooks/capture-session-id.py"
              }
            ]
          }
        ]
      }
    }
"""

import json
import os
import sys
from pathlib import Path

# Set up imports for snapshot module
_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

try:
    from lib.snapshot import read_snapshot, validate_snapshot, format_resume_context, clear_hook_errors
    _snapshot_available = True
except ImportError:
    _snapshot_available = False


def discover_snapshot_path() -> str | None:
    """Find snapshot.json by checking CWD and walking up to 3 parent levels."""
    cwd = Path(os.getcwd())

    # Direct check
    direct = cwd / "snapshot.json"
    if direct.is_file():
        return str(direct)

    # Check for config files in CWD and parent dirs
    config_names = {
        "deep_plan_config.json": "planning_dir",
        "deep_implement_config.json": "state_dir",
    }

    search_dir = cwd
    for _ in range(4):  # CWD + 3 parent levels
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
            break  # Reached filesystem root
        search_dir = parent

    return None


def main() -> int:
    """Capture session_id, output to Claude's context and optionally CLAUDE_ENV_FILE.

    Returns:
        0 always (hooks should not fail the session start)
    """
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No valid JSON on stdin - silently succeed
        return 0
    except Exception:
        # Any other error reading stdin - silently succeed
        return 0

    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")

    # Capture CLAUDE_PLUGIN_ROOT (available because hooks.json expands it)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")

    # Need at least session_id to proceed
    if not session_id:
        return 0

    # Build additionalContext lines
    context_parts = []

    existing_session_id = os.environ.get("DEEP_SESSION_ID")
    if existing_session_id != session_id:
        context_parts.append(f"DEEP_SESSION_ID={session_id}")

    if plugin_root:
        context_parts.append(f"DEEP_PLUGIN_ROOT={plugin_root}")

    # Snapshot discovery and resume context
    if _snapshot_available:
        try:
            snapshot_path = discover_snapshot_path()
            if snapshot_path:
                snapshot = read_snapshot(snapshot_path)
                if snapshot is not None:
                    planning_dir = str(Path(snapshot_path).parent)
                    if validate_snapshot(snapshot, planning_dir):
                        resume_ctx = format_resume_context(snapshot, snapshot_path=snapshot_path)
                        for key, value in resume_ctx.items():
                            # Skip DEEP_SESSION_ID — already handled above
                            if key == "DEEP_SESSION_ID":
                                continue
                            context_parts.append(f"{key}={value}")

                        # Clear hook errors after surfacing
                        if snapshot.get("hook_errors"):
                            clear_hook_errors(snapshot_path)
        except Exception:
            # Snapshot operations must never crash the hook
            pass

    if context_parts:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n".join(context_parts),
            }
        }
        print(json.dumps(output))

    # SECONDARY: Also try CLAUDE_ENV_FILE for bash commands (may not work)
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        try:
            # Check if already set (avoid duplicates from multiple plugins)
            existing_content = ""
            try:
                with open(env_file) as f:
                    existing_content = f.read()
            except FileNotFoundError:
                pass

            # Only write if not already present
            lines_to_write = []
            if f"DEEP_SESSION_ID={session_id}" not in existing_content:
                lines_to_write.append(f"export DEEP_SESSION_ID={session_id}\n")
            if (
                transcript_path
                and f"CLAUDE_TRANSCRIPT_PATH={transcript_path}" not in existing_content
            ):
                lines_to_write.append(
                    f"export CLAUDE_TRANSCRIPT_PATH={transcript_path}\n"
                )

            if lines_to_write:
                with open(env_file, "a") as f:
                    f.writelines(lines_to_write)
        except OSError:
            # Failed to read/write - silently succeed (we already output to context)
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
