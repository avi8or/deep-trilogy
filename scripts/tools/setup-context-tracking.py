#!/usr/bin/env python3
"""Set up context percentage tracking in Claude Code's statusline.

Reads ~/.claude/settings.json, detects current statusline configuration,
and wraps or creates it to also write context percentage to /tmp/claude-context-pct.

Handles three cases:
1. No statusline configured → installs write-context-pct.sh as standalone
2. Existing statusline → wraps it to also write context pct
3. Already configured → skips (idempotent)

Usage:
    python3 setup-context-tracking.py [--check] [--plugin-root /path/to/plugin]

    --check     Only check if setup is needed (exit 0 = configured, exit 1 = needs setup)
    --plugin-root  Path to plugin root (for resolving write-context-pct.sh path)
"""

import argparse
import json
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CONTEXT_PCT_FILE = Path("/tmp/claude-context-pct")
MARKER = "/tmp/claude-context-pct"  # Used to detect if already wrapped


def load_settings() -> dict:
    """Load Claude Code settings, returning empty dict if missing."""
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict) -> None:
    """Write settings back, preserving formatting."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def is_already_configured(settings: dict) -> bool:
    """Check if context tracking is already wired into the statusline."""
    sl = settings.get("statusLine")
    if not sl:
        return False
    command = sl.get("command", "")
    return MARKER in command


def get_wrapper_script_path(plugin_root: str | None) -> str:
    """Resolve the path to write-context-pct.sh."""
    if plugin_root:
        return f"{plugin_root}/scripts/tools/write-context-pct.sh"
    # Fallback: try to find it relative to this script
    here = Path(__file__).resolve().parent
    local = here / "write-context-pct.sh"
    if local.exists():
        return str(local)
    # Last resort: use the typical cache path pattern
    return "${CLAUDE_PLUGIN_ROOT}/scripts/tools/write-context-pct.sh"


def wrap_existing_command(original_cmd: str) -> str:
    """Wrap an existing statusline command to also write context pct."""
    # Capture stdin, fork to jq for pct writing, pipe to original command
    return (
        f'input=$(cat); '
        f'echo "$input" | jq -r \'.context_window.used_percentage // 0\' '
        f'| cut -d. -f1 > /tmp/claude-context-pct 2>/dev/null; '
        f'echo "$input" | {original_cmd}'
    )


def create_standalone_command(wrapper_path: str) -> str:
    """Create a statusline command using write-context-pct.sh as standalone."""
    return wrapper_path


def setup(plugin_root: str | None) -> dict:
    """Run setup. Returns status dict with action taken."""
    settings = load_settings()

    if is_already_configured(settings):
        return {"status": "already_configured", "message": "Context tracking is already set up."}

    wrapper_path = get_wrapper_script_path(plugin_root)
    existing_sl = settings.get("statusLine")

    if existing_sl and existing_sl.get("command"):
        # Wrap existing statusline
        original = existing_sl["command"]
        existing_sl["command"] = wrap_existing_command(original)
        action = "wrapped"
        detail = f"Wrapped existing statusline: {original}"
    else:
        # No statusline — install standalone
        settings["statusLine"] = {
            "type": "command",
            "command": create_standalone_command(wrapper_path),
            "padding": 0,
        }
        action = "installed"
        detail = f"Installed standalone statusline: {wrapper_path}"

    save_settings(settings)
    return {"status": action, "message": detail}


def check_only() -> dict:
    """Check if setup is needed without modifying anything."""
    settings = load_settings()
    configured = is_already_configured(settings)
    has_statusline = bool(settings.get("statusLine", {}).get("command"))

    return {
        "configured": configured,
        "has_statusline": has_statusline,
        "context_file_exists": CONTEXT_PCT_FILE.exists(),
    }


def main():
    parser = argparse.ArgumentParser(description="Set up context percentage tracking")
    parser.add_argument("--check", action="store_true", help="Only check if setup is needed")
    parser.add_argument("--plugin-root", type=str, default=None, help="Plugin root path")
    args = parser.parse_args()

    if args.check:
        result = check_only()
        print(json.dumps(result))
        sys.exit(0 if result["configured"] else 1)
    else:
        result = setup(args.plugin_root)
        print(json.dumps(result))
        sys.exit(0)


if __name__ == "__main__":
    main()
