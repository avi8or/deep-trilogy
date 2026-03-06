#!/usr/bin/env python3
"""Smart path detection helper for no-arg /deep-plan invocation.

Scans a directory for spec.md files, determines their planning status,
and parses project-manifest.md for dependency information.

Usage:
    uv run detect_specs.py --search-dir <path>
"""

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SpecInfo:
    path: str
    name: str
    status: str
    dependencies: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


def _determine_status(spec_dir: Path) -> str:
    """Determine planning status of a spec directory."""
    try:
        sections_dir = spec_dir / "sections"
        if sections_dir.is_dir():
            section_files = list(sections_dir.glob("section-*.md"))
            if section_files:
                return "sections_written"
            if (sections_dir / "index.md").is_file():
                return "planned"
        if (spec_dir / "deep_plan_config.json").is_file():
            return "in_progress"
    except (OSError, PermissionError):
        pass
    return "unplanned"


def parse_manifest(search_dir: str) -> tuple[list[str], dict[str, list[str]]]:
    """Parse project-manifest.md for spec names and dependencies.

    Looks for project-manifest.md in search_dir, then one level up.

    Returns:
        - List of spec names from SPLIT_MANIFEST block
        - Dict mapping spec name -> list of spec names it is blocked by
    """
    search_path = Path(search_dir)
    manifest_path = None
    for candidate in [search_path / "project-manifest.md",
                      search_path.parent / "project-manifest.md"]:
        if candidate.is_file():
            manifest_path = candidate
            break

    if manifest_path is None:
        return [], {}

    try:
        content = manifest_path.read_text()
    except (OSError, PermissionError):
        return [], {}

    # Extract SPLIT_MANIFEST block
    match = re.search(
        r"<!--\s*SPLIT_MANIFEST\s*\n(.*?)\nEND_MANIFEST\s*-->",
        content, re.DOTALL
    )
    if not match:
        return [], {}

    spec_names = [line.strip() for line in match.group(1).strip().splitlines()
                  if line.strip()]

    # Build number -> name mapping (e.g., "01" -> "01-alpha")
    num_to_name: dict[str, str] = {}
    for name in spec_names:
        prefix_match = re.match(r"^(\d+)", name)
        if prefix_match:
            num_to_name[prefix_match.group(1)] = name

    # Extract blocked-by dependencies
    deps: dict[str, list[str]] = {}
    for dep_match in re.finditer(
        r"(\d+)\s*──blocked-by──>\s*(\d+)", content
    ):
        dependent_num = dep_match.group(1)
        blocker_num = dep_match.group(2)
        dependent_name = num_to_name.get(dependent_num)
        blocker_name = num_to_name.get(blocker_num)
        if dependent_name and blocker_name:
            deps.setdefault(dependent_name, []).append(blocker_name)

    return spec_names, deps


def detect_specs(search_dir: str) -> list[SpecInfo]:
    """Find spec.md files and determine their planning status.

    Scans search_dir recursively up to 2 levels deep for files named 'spec.md'.
    For each found spec, determines planning status by checking sibling files.
    Parses project-manifest.md (if found) for dependency info.

    Returns a sorted, deduplicated list of SpecInfo objects.
    """
    search_path = Path(search_dir)
    seen_paths: set[str] = set()
    specs: list[SpecInfo] = []

    # Scan at depths 0, 1, 2
    patterns = ["spec.md", "*/spec.md", "*/*/spec.md"]
    for pattern in patterns:
        try:
            for spec_file in search_path.glob(pattern):
                try:
                    resolved = str(spec_file.resolve())
                except OSError:
                    continue
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)

                spec_dir = spec_file.parent
                specs.append(SpecInfo(
                    path=resolved,
                    name=spec_dir.name,
                    status=_determine_status(spec_dir),
                ))
        except (OSError, PermissionError):
            continue

    # Parse manifest for dependencies
    _, dep_map = parse_manifest(search_dir)

    # Build status lookup for blocked_by resolution
    status_by_name = {s.name: s.status for s in specs}

    for spec in specs:
        if spec.name in dep_map:
            spec.dependencies = dep_map[spec.name]
            # Unknown specs default to "unplanned" (conservative: treat as blocking)
            spec.blocked_by = [
                dep for dep in spec.dependencies
                if status_by_name.get(dep, "unplanned") != "sections_written"
            ]

    specs.sort(key=lambda s: s.name)
    return specs


def main():
    """CLI entry point. Outputs JSON array of spec info to stdout."""
    parser = argparse.ArgumentParser(description="Detect spec.md files and their planning status")
    parser.add_argument("--search-dir", default=".", help="Directory to scan (default: CWD)")
    args = parser.parse_args()

    results = detect_specs(args.search_dir)
    print(json.dumps([asdict(s) for s in results], indent=2))


if __name__ == "__main__":
    main()
