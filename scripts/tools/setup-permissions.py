#!/usr/bin/env python3
"""Set up project-level auto-approve permissions for deep-trilogy.

Generates scoped permission rules for .claude/settings.json so that
deep-plan, deep-implement, and deep-project workflows run with minimal
approval prompts.

Usage:
    python3 setup-permissions.py --mode check --project-dir /path --plugin-root /path
    python3 setup-permissions.py --mode apply --project-dir /path --plugin-root /path --tiers "A,B,C,D"
"""

import argparse
import json
import sys
from pathlib import Path


def get_rules(category: str, project_dir: str, plugin_root: str) -> list[str]:
    """Return permission rules for a given category."""

    rules: dict[str, list[str]] = {
        "A": [
            # Read project files
            f"Read({project_dir}/**)",
            # Read plugin files (references, scripts, skill docs)
            f"Read({plugin_root}/**)",
            # Search/navigate project
            f"Grep({project_dir}/**)",
            f"Glob({project_dir}/**)",
            # Safe shell commands
            "Bash(ls *)",
            "Bash(pwd)",
            "Bash(find *)",
            "Bash(cat *)",
            "Bash(head *)",
            "Bash(tail *)",
            "Bash(wc *)",
            "Bash(which *)",
            # Context monitoring (session lifecycle reads /tmp/claude-context-pct)
            "Bash(cat /tmp/claude-context-pct*)",
            # Git read operations
            "Bash(git status*)",
            "Bash(git log*)",
            "Bash(git diff*)",
            "Bash(git branch*)",
            "Bash(git rev-parse*)",
            "Bash(git show*)",
        ],
        "B": [
            # Plugin script execution via uv — scoped to plugin path only
            f"Bash(uv run --project {plugin_root}*)",
            f"Bash(uv run {plugin_root}*)",
            # Validate env — scoped to plugin path
            f"Bash(bash {plugin_root}*)",
            # Context tracking setup — scoped to plugin path
            f"Bash(python3 {plugin_root}*)",
        ],
        "C": [
            # Task management
            "TaskList",
            "TaskGet(*)",
            "TaskCreate(*)",
            "TaskUpdate(*)",
            "TaskOutput(*)",
        ],
        "D": [
            # Planning file writes — name-pattern scoped
            "Write(**/claude-*.md)",
            "Write(**/sections/index.md)",
            "Write(**/sections/section-*.md)",
            "Write(**/reviews/*.md)",
            "Write(**/snapshot.json)",
            "Write(**/deep_plan_config.json)",
            "Write(**/deep_implement_config.json)",
            "Write(**/deep_project_session.json)",
            # Edit existing planning files
            "Edit(**/claude-*.md)",
        ],
        "E": [
            # Git write operations
            "Bash(git add *)",
            "Bash(git commit *)",
            "Bash(git checkout -b *)",
        ],
        "F": [
            # Subagent launches
            "Task(*)",
        ],
    }

    return rules.get(category, [])


CATEGORY_META = {
    "A": {
        "name": "Reading & Navigation",
        "description": "Read, Grep, Glob, ls, find, pwd, git status/log/diff for project and plugin files",
        "risk": "None",
        "default_on": True,
    },
    "B": {
        "name": "Plugin Scripts",
        "description": "uv run, bash, python3 scoped to plugin install path only (not blanket)",
        "risk": "Low",
        "default_on": True,
    },
    "C": {
        "name": "Task Management",
        "description": "TaskList, TaskGet, TaskCreate, TaskUpdate, TaskOutput",
        "risk": "None",
        "default_on": True,
    },
    "D": {
        "name": "Planning File Writes",
        "description": "Write/Edit for plugin-specific file patterns only (claude-*.md, sections/*, snapshot.json, configs)",
        "risk": "Medium",
        "default_on": True,
    },
    "E": {
        "name": "Git Operations",
        "description": "git add, git commit, git checkout -b",
        "risk": "Medium",
        "default_on": False,
    },
    "F": {
        "name": "Subagent Launches",
        "description": "Task/Agent tool for general-purpose (section writers, code reviewers) and Explore subagents",
        "risk": "Low",
        "default_on": False,
    },
}

PRESETS = {
    "conservative": ["A", "B", "C"],
    "recommended": ["A", "B", "C", "D"],
    "full_auto": ["A", "B", "C", "D", "E", "F"],
}


def load_project_settings(project_dir: str) -> dict:
    """Load existing project .claude/settings.json."""
    settings_path = Path(project_dir) / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_project_settings(project_dir: str, settings: dict) -> str:
    """Write project .claude/settings.json, return path."""
    settings_dir = Path(project_dir) / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return str(settings_path)


def get_all_possible_rules(project_dir: str, plugin_root: str) -> set[str]:
    """Return all rules this script could generate, for any tier combination."""
    all_rules = set()
    for cat in CATEGORY_META:
        all_rules.update(get_rules(cat, project_dir, plugin_root))
    return all_rules


def check(project_dir: str, plugin_root: str) -> dict:
    """Check current state and return info for the skill."""
    settings = load_project_settings(project_dir)
    existing_allow = settings.get("permissions", {}).get("allow", [])
    all_possible = get_all_possible_rules(project_dir, plugin_root)
    existing_deep_rules = [r for r in existing_allow if r in all_possible]

    categories = {}
    for cat_id, meta in CATEGORY_META.items():
        rules = get_rules(cat_id, project_dir, plugin_root)
        already_present = [r for r in rules if r in existing_allow]
        categories[cat_id] = {
            **meta,
            "rule_count": len(rules),
            "already_present": len(already_present),
            "fully_configured": len(already_present) == len(rules),
        }

    return {
        "project_dir": project_dir,
        "plugin_root": plugin_root,
        "settings_path": str(Path(project_dir) / ".claude" / "settings.json"),
        "has_existing_settings": bool(settings),
        "existing_allow_count": len(existing_allow),
        "existing_deep_rules": len(existing_deep_rules),
        "categories": categories,
        "presets": {
            name: {
                "tiers": tiers,
                "total_rules": sum(len(get_rules(t, project_dir, plugin_root)) for t in tiers),
            }
            for name, tiers in PRESETS.items()
        },
    }


def apply(project_dir: str, plugin_root: str, tiers: list[str]) -> dict:
    """Apply permission rules for selected tiers."""
    settings = load_project_settings(project_dir)

    # Remove old deep-trilogy rules to avoid duplicates
    existing_allow = settings.get("permissions", {}).get("allow", [])
    all_possible = get_all_possible_rules(project_dir, plugin_root)
    cleaned = [r for r in existing_allow if r not in all_possible]

    # Build new rules
    new_rules = []
    for tier in sorted(set(tiers)):
        new_rules.extend(get_rules(tier, project_dir, plugin_root))

    # Merge: existing non-deep rules + new deep rules
    merged = cleaned + new_rules

    if "permissions" not in settings:
        settings["permissions"] = {}
    settings["permissions"]["allow"] = merged

    path = save_project_settings(project_dir, settings)

    return {
        "status": "written",
        "settings_path": path,
        "tiers_applied": tiers,
        "rules_written": len(new_rules),
        "total_allow_rules": len(merged),
        "preserved_existing": len(cleaned),
    }


def main():
    parser = argparse.ArgumentParser(description="Set up deep-trilogy permissions")
    parser.add_argument("--mode", required=True, choices=["check", "apply"])
    parser.add_argument("--project-dir", required=True, help="Project root directory")
    parser.add_argument("--plugin-root", required=True, help="Plugin cache root path")
    parser.add_argument("--tiers", default="", help="Comma-separated tier IDs (A,B,C,D,E,F)")
    args = parser.parse_args()

    if args.mode == "check":
        result = check(args.project_dir, args.plugin_root)
    else:
        tiers = [t.strip().upper() for t in args.tiers.split(",") if t.strip()]
        if not tiers:
            print(json.dumps({"error": "No tiers specified"}))
            sys.exit(1)
        result = apply(args.project_dir, args.plugin_root, tiers)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
