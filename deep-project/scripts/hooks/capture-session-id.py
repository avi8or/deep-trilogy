#!/usr/bin/env python3
"""Capture session_id and plugin_root, expose via Claude's context.

This hook reads session_id from the JSON payload on stdin and:
1. Outputs it to stdout as additionalContext (Claude sees this directly)
2. Also captures CLAUDE_PLUGIN_ROOT as DEEP_PLUGIN_ROOT (for SKILL.md path resolution)
3. Optionally writes to CLAUDE_ENV_FILE if available (fallback for bash)
4. Discovers deep_project_session.json for resume context
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def discover_session_state() -> tuple[str | None, dict | None]:
    """Find deep_project_session.json and return (path, state) or (None, None)."""
    cwd = Path(os.getcwd())

    search_dir = cwd
    for _ in range(4):  # CWD + 3 parent levels
        state_path = search_dir / "deep_project_session.json"
        if state_path.is_file():
            try:
                with open(state_path) as f:
                    state = json.load(f)
                return str(state_path), state
            except (json.JSONDecodeError, OSError):
                return None, None

        # Also check subdirectories one level deep (planning dirs)
        try:
            for child in search_dir.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    child_state = child / "deep_project_session.json"
                    if child_state.is_file():
                        try:
                            with open(child_state) as f:
                                state = json.load(f)
                            return str(child_state), state
                        except (json.JSONDecodeError, OSError):
                            continue
        except OSError:
            pass

        parent = search_dir.parent
        if parent == search_dir:
            break
        search_dir = parent

    return None, None


def infer_resume_step(planning_dir: str) -> tuple[int, str]:
    """Infer the resume step from file existence in the planning directory."""
    p = Path(planning_dir)

    # Check for completed specs in split directories
    manifest = p / "project-manifest.md"
    interview = p / "deep_project_interview.md"

    if manifest.is_file():
        # Check for split directories with specs
        split_dirs = sorted(
            d for d in p.iterdir()
            if d.is_dir() and d.name[:2].isdigit() and d.name[2] == "-"
        )
        if split_dirs:
            specs_missing = [d for d in split_dirs if not (d / "spec.md").is_file()]
            if not specs_missing:
                return 7, "complete"
            return 6, "spec-generation"
        return 4, "user-confirmation"

    if interview.is_file():
        return 2, "split-analysis"

    return 1, "interview"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # Hooks should never fail
    except Exception:
        return 0

    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")

    # Capture CLAUDE_PLUGIN_ROOT (available because hooks.json expands it)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")

    if not session_id:
        return 0

    # Build additionalContext lines
    context_parts = []

    existing_session_id = os.environ.get("DEEP_SESSION_ID")
    if existing_session_id != session_id:
        context_parts.append(f"DEEP_SESSION_ID={session_id}")

    if plugin_root:
        context_parts.append(f"DEEP_PLUGIN_ROOT={plugin_root}")

    # Session state discovery for resume
    try:
        state_path, state = discover_session_state()
        if state_path and state:
            planning_dir = str(Path(state_path).parent)
            step, step_name = infer_resume_step(planning_dir)
            if step > 1:  # Only surface if there's progress to resume
                context_parts.append(f"DEEP_RESUME_STEP={step}")
                context_parts.append(f"DEEP_RESUME_NAME={step_name}")
                context_parts.append(f"DEEP_PLUGIN=deep-project")
                context_parts.append(f"DEEP_SESSION_STATE={state_path}")
    except Exception:
        pass  # Never crash the hook

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
            existing_content = ""
            try:
                with open(env_file) as f:
                    existing_content = f.read()
            except FileNotFoundError:
                pass

            lines_to_write = []
            if f'DEEP_SESSION_ID="{session_id}"' not in existing_content:
                lines_to_write.append(f'export DEEP_SESSION_ID="{session_id}"\n')
            if (
                transcript_path
                and f'CLAUDE_TRANSCRIPT_PATH="{transcript_path}"' not in existing_content
            ):
                lines_to_write.append(
                    f'export CLAUDE_TRANSCRIPT_PATH="{transcript_path}"\n'
                )

            if lines_to_write:
                with open(env_file, "a") as f:
                    f.writelines(lines_to_write)
        except OSError:
            pass  # CLAUDE_ENV_FILE failed, but we already output to context

    return 0


if __name__ == "__main__":
    sys.exit(main())
