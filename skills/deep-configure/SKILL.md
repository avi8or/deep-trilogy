---
name: deep-configure
description: Set up project-level auto-approve permissions to reduce friction during deep-plan, deep-implement, and deep-project workflows. Run once per project for a smoother experience.
---

# Deep Configure — Permission Setup

Walks users through setting up project-level `.claude/settings.json` auto-approve rules so deep-trilogy workflows run with minimal approval prompts.

## Step 0: Resolve Plugin Root

Look for `DEEP_PLUGIN_ROOT=<path>` in your conversation context (injected by the SessionStart hook). Extract the path value.

**IMPORTANT:** `DEEP_PLUGIN_ROOT` is conversation context, NOT a shell environment variable. You must substitute the actual path value into commands. Do NOT use `${DEEP_PLUGIN_ROOT}` in bash — it will be empty.

If `DEEP_PLUGIN_ROOT` is not in your context, discover it:
```bash
find ~/.claude/plugins/cache -name "plugin.json" -path "*avi8or*deep-trilogy*" -type f 2>/dev/null | head -1 | xargs dirname | xargs dirname
```

Store the resolved path as `plugin_root` for all subsequent commands.

## Step 1: Detect Environment

Get the project directory:
```bash
pwd
```

Run the check script (substitute `plugin_root` value directly):
```bash
python3 <plugin_root>/scripts/tools/setup-permissions.py \
  --mode check \
  --project-dir "$(pwd)" \
  --plugin-root "<plugin_root>"
```

Parse the JSON output. Print the detection banner:

```
═══════════════════════════════════════════════════════════════
DEEP-CONFIGURE: Reduce Approval Friction
═══════════════════════════════════════════════════════════════

Detected:
  Project:     {project_dir}
  Plugin:      {plugin_root}
  Existing:    {existing_allow_count} rules / {existing_deep_rules} deep-trilogy rules
```

If `existing_deep_rules > 0`, mention that existing deep-trilogy rules will be replaced (not duplicated).

## Step 2: Preset Selection

Use `AskUserQuestion`:

```
question: "How much friction do you want to remove?"
options:
  - label: "Recommended"
    description: "Auto-approve reads, plugin scripts, tasks, and planning file writes. You still approve git commits and subagent launches. (~80% fewer prompts)"
  - label: "Conservative"
    description: "Auto-approve reads, plugin scripts, and task management only. You approve every file write, git op, and subagent launch. (~40% fewer prompts)"
  - label: "Full Auto"
    description: "Auto-approve everything including git commits and subagent launches. True zero-friction. (~100% fewer prompts)"
  - label: "Custom"
    description: "Walk through each category individually"
```

Map the selection:
- "Recommended" → `tiers = "A,B,C,D"` → skip to Step 4
- "Conservative" → `tiers = "A,B,C"` → skip to Step 4
- "Full Auto" → `tiers = "A,B,C,D,E,F"` → skip to Step 4
- "Custom" → proceed to Step 3

## Step 3: Custom Category Walkthrough

Present each category one at a time using `AskUserQuestion`. **Be explicit about what each rule matches** so the user understands exactly what they're approving. Use the details below for each category's description.

If `fully_configured` is true for a category, note "(already configured)" in the description.

### Category A: Reading & Navigation (recommend: Enable)

**Before presenting, show the user these examples:**

```
Category A: Reading & Navigation

  Auto-approved:
    ✓ Read("/Users/you/Projects/my-app/src/index.ts")          — project file
    ✓ Read("~/.claude/plugins/cache/avi8or-plugins/.../SKILL.md") — plugin file
    ✓ Grep("TODO", "/Users/you/Projects/my-app/**")            — search project
    ✓ git status, git log, git diff                             — git reads
    ✓ ls, pwd, find, cat, head, wc, which                      — shell reads

  Still requires approval:
    ✗ Read("/Users/you/Documents/taxes.pdf")                    — outside project
    ✗ Read("/etc/passwd")                                       — system file

  Risk: None — all read-only operations. {rule_count} rules.
```

Use `AskUserQuestion`:
```
question: "Enable Category A: Reading & Navigation?"
options:
  - label: "Enable (recommended)"
    description: "Read/search scoped to project dir + plugin cache only"
  - label: "Skip"
    description: "Approve every file read and directory listing individually"
```

### Category B: Plugin Scripts (recommend: Enable)

**Before presenting, show the user these examples:**

```
Category B: Plugin Scripts

  Auto-approved (only commands targeting the plugin's install path):
    ✓ uv run --project ~/.claude/plugins/.../deep-plan setup-planning-session.py
    ✓ uv run ~/.claude/plugins/.../scripts/checks/check-context-decision.py
    ✓ bash ~/.claude/plugins/.../scripts/checks/validate-env.sh
    ✓ python3 ~/.claude/plugins/.../scripts/tools/setup-permissions.py

  Still requires approval:
    ✗ uv run pytest                              — not targeting plugin path
    ✗ bash myscript.sh                           — not targeting plugin path
    ✗ python3 my_tool.py                         — not targeting plugin path
    ✗ uv run --project ./my-project some_cmd     — different project

  Risk: Low — only plugin-internal scripts. {rule_count} rules.
```

Use `AskUserQuestion`:
```
question: "Enable Category B: Plugin Scripts?"
options:
  - label: "Enable (recommended)"
    description: "Path-scoped to plugin install dir only — not a blanket uv/bash/python3 approval"
  - label: "Skip"
    description: "Approve every plugin script execution individually"
```

### Category C: Task Management (recommend: Enable)

**Before presenting, show the user these examples:**

```
Category C: Task Management

  Auto-approved:
    ✓ TaskList                     — view workflow checklist
    ✓ TaskGet(taskId="abc123")     — read a specific task
    ✓ TaskCreate(subject="...")    — add a workflow step
    ✓ TaskUpdate(status="done")    — mark step complete
    ✓ TaskOutput(taskId="abc123")  — read subagent output

  These do NOT touch files, code, or git — they only manage
  the internal workflow task list.

  Risk: None. {rule_count} rules.
```

Use `AskUserQuestion`:
```
question: "Enable Category C: Task Management?"
options:
  - label: "Enable (recommended)"
    description: "Workflow checklist only — no file or code changes"
  - label: "Skip"
    description: "Approve every task list operation individually"
```

### Category D: Planning File Writes (recommend: Enable)

**Before presenting, show the user these examples:**

```
Category D: Planning File Writes

  Auto-approved (filename patterns only):
    ✓ Write("planning/claude-spec.md")              — planning spec
    ✓ Write("planning/claude-plan.md")              — implementation plan
    ✓ Write("planning/claude-research.md")          — research notes
    ✓ Write("planning/claude-interview.md")         — interview transcript
    ✓ Write("planning/claude-plan-tdd.md")          — TDD plan
    ✓ Edit("planning/claude-plan.md")               — update plan
    ✓ Write("planning/sections/index.md")           — section manifest
    ✓ Write("planning/sections/section-01-setup.md") — section file
    ✓ Write("planning/reviews/gemini-review.md")    — LLM review
    ✓ Write("planning/snapshot.json")               — session resume data
    ✓ Write("planning/deep_plan_config.json")       — session config

  Still requires approval:
    ✗ Write("src/index.ts")             — not a plugin filename pattern
    ✗ Write("package.json")             — not a plugin filename pattern
    ✗ Write(".env")                     — not a plugin filename pattern
    ✗ Edit("README.md")                — not a claude-*.md pattern
    ✗ Write("my-notes.md")             — doesn't start with "claude-"

  Risk: Medium — writes files, but only plugin-specific name patterns. {rule_count} rules.
```

Use `AskUserQuestion`:
```
question: "Enable Category D: Planning File Writes?"
options:
  - label: "Enable (recommended)"
    description: "Only claude-*.md, sections/*, reviews/*, snapshot.json, and config files"
  - label: "Skip"
    description: "Approve every planning file write individually"
```

### Category E: Git Operations (recommend: Skip)

**Before presenting, show the user these examples:**

```
Category E: Git Operations

  Auto-approved:
    ✓ git add src/index.ts
    ✓ git commit -m "Add feature X"
    ✓ git checkout -b feature/my-branch

  What this means:
    Commits happen automatically as part of the /deep-implement workflow.
    You will NOT see or approve commit messages before they're created.

  Risk: Medium — creates commits without review. {rule_count} rules.
```

Use `AskUserQuestion`:
```
question: "Enable Category E: Git Operations?"
options:
  - label: "Enable"
    description: "git add, commit, checkout -b run without prompting"
  - label: "Skip (recommended)"
    description: "Review each commit before it happens"
```

### Category F: Subagent Launches (recommend: Skip)

**Before presenting, show the user these examples:**

```
Category F: Subagent Launches

  Auto-approved:
    ✓ Task(subagent_type="general-purpose")   — section writers, code reviewers
    ✓ Task(subagent_type="Explore")          — researches your codebase

  What this means:
    Subagents run as separate Claude conversations in parallel.
    Each one uses API credits. A /deep-plan run may launch 5-15 subagents.

  Risk: Low — but each subagent consumes API credits. {rule_count} rules.
```

Use `AskUserQuestion`:
```
question: "Enable Category F: Subagent Launches?"
options:
  - label: "Enable"
    description: "Subagents launch automatically for parallel work"
  - label: "Skip (recommended)"
    description: "See and approve each subagent before it launches"
```

Collect enabled categories into a comma-separated tiers string (e.g., `"A,B,C,D,F"`).

## Step 4: Confirmation

Show a summary of what will be written. Use the check output to show rule counts per category:

```
═══════════════════════════════════════════════════════════════
DEEP-CONFIGURE: Review
═══════════════════════════════════════════════════════════════

Will write to: {project_dir}/.claude/settings.json

  ✓ Reading & Navigation     {n} rules
  ✓ Plugin Scripts            {n} rules
  ✓ Task Management           {n} rules
  ✓ Planning File Writes      {n} rules
  ✗ Git Operations            skipped
  ✗ Subagent Launches         skipped

  Total: {total} auto-approve rules
═══════════════════════════════════════════════════════════════
```

Use `✓` for enabled categories and `✗` for skipped ones.

Use `AskUserQuestion`:
```
question: "Write these permissions?"
options:
  - label: "Yes, write settings"
    description: "Create/update .claude/settings.json with these rules"
  - label: "Go back"
    description: "Change selections"
  - label: "Cancel"
    description: "Exit without writing anything"
```

If "Go back" → return to Step 2.
If "Cancel" → print "No changes made." and stop.

## Step 5: Apply

Run the apply command:
```bash
python3 <plugin_root>/scripts/tools/setup-permissions.py \
  --mode apply \
  --project-dir "<project_dir>" \
  --plugin-root "<plugin_root>" \
  --tiers "<selected_tiers>"
```

Parse the JSON output and print:

```
═══════════════════════════════════════════════════════════════
✓ DEEP-CONFIGURE: Complete
═══════════════════════════════════════════════════════════════

Written to: {settings_path}
  Rules added:     {rules_written}
  Rules preserved: {preserved_existing} (non-plugin rules kept)

Restart Claude Code to activate these permissions.

Next time you run /deep-plan, /deep-implement, or /deep-project
in this project, the approved operations will run without prompts.

Tip: Run /deep-configure again anytime to adjust permissions.
═══════════════════════════════════════════════════════════════
```

## Dependencies

- `python3` must be available
- No external packages needed (uses only stdlib)
