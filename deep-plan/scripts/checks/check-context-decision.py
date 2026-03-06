#!/usr/bin/env python3
"""Check context usage and return prompt or skip action.

Reads context percentage from /tmp/claude-context-pct (written by statusline),
applies threshold logic, and returns a prompt with the percentage included
so users can make informed decisions.

Usage:
    uv run check-context-decision.py --planning-dir "/path/to/planning" --upcoming-operation "External LLM Review"
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add parent to path for lib imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.config import load_session_config, ConfigError

CONTEXT_PCT_FILE = Path(os.environ.get("DEEP_CONTEXT_FILE", "/tmp/claude-context-pct"))


def read_context_pct() -> int | None:
    """Read context percentage from the shared file written by the statusline."""
    try:
        text = CONTEXT_PCT_FILE.read_text().strip()
        pct = int(text)
        if 0 <= pct <= 100:
            return pct
    except (FileNotFoundError, ValueError, OSError):
        pass
    return None


def build_prompt_message(upcoming_operation: str, context_pct: int | None) -> str:
    """Build the prompt message, including context percentage when available."""
    if context_pct is not None and context_pct >= 85:
        header = (
            f"Context check before: {upcoming_operation} | "
            f"Context usage: {context_pct}% (HIGH — /clear recommended)"
        )
    elif context_pct is not None:
        header = (
            f"Context check before: {upcoming_operation} | "
            f"Context usage: {context_pct}%"
        )
    else:
        header = (
            f"Context check before: {upcoming_operation} | "
            "Context usage: unknown (statusline not configured)"
        )

    return (
        f"{header}\n\n"
        "Note: Compaction (manual or auto) may cause workflow instruction loss. "
        "If Claude gets confused after compacting, /clear + re-run /deep-plan is the cleanest recovery - "
        "your progress is preserved in planning files."
    )


def main():
    parser = argparse.ArgumentParser(description="Check context usage and decide whether to prompt")
    parser.add_argument(
        "--planning-dir",
        required=True,
        type=Path,
        help="Path to planning directory (contains deep_plan_config.json)"
    )
    parser.add_argument(
        "--upcoming-operation",
        required=True,
        help="Name of the upcoming operation (e.g., 'External LLM Review')"
    )
    args = parser.parse_args()

    context_pct = read_context_pct()

    prompt_options = [
        {
            "label": "Continue",
            "description": "Proceed with current context (auto-compact triggers at ~95% if needed)"
        },
        {
            "label": "/clear + re-run",
            "description": "Cleanest recovery if context is critical - fresh window with file-based resume"
        },
    ]

    # Load config to check if context prompts are enabled
    try:
        config = load_session_config(args.planning_dir)
    except (ConfigError, json.JSONDecodeError) as e:
        # Config error — default to prompting
        print(json.dumps({
            "action": "prompt",
            "reason": f"Config error ({e}), defaulting to prompt",
            "context_pct": context_pct,
            "check_enabled": True,
            "prompt": {
                "message": build_prompt_message(args.upcoming_operation, context_pct),
                "options": prompt_options
            }
        }))
        return 0

    ctx = config.get("context", {})
    check_enabled = ctx.get("check_enabled", True)

    # If checks disabled, skip entirely (unless >= 85% — always warn at critical levels)
    if not check_enabled and (context_pct is None or context_pct < 85):
        print(json.dumps({
            "action": "skip",
            "reason": "Context prompts disabled in config",
            "context_pct": context_pct,
            "check_enabled": False
        }))
        return 0

    # Apply threshold logic (script is only called at scheduled checkpoints)
    # < 50%: skip — plenty of room
    if context_pct is not None and context_pct < 50:
        print(json.dumps({
            "action": "skip",
            "reason": f"Context at {context_pct}% — below threshold, skipping prompt",
            "context_pct": context_pct,
            "check_enabled": True
        }))
        return 0

    # >= 50% or unknown: prompt
    print(json.dumps({
        "action": "prompt",
        "reason": f"Context at {context_pct}%" if context_pct is not None else "Context unknown, prompting by default",
        "context_pct": context_pct,
        "check_enabled": True,
        "prompt": {
            "message": build_prompt_message(args.upcoming_operation, context_pct),
            "options": prompt_options
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
