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

```
question: "Category A: Reading & Navigation"
options:
  - label: "Enable (recommended)"
    description: |
      Read/Grep/Glob scoped to your project dir and the plugin cache dir only.
      Shell commands: ls, pwd, find, cat, head, tail, wc, which.
      Git reads: status, log, diff, branch, rev-parse, show.
      Risk: None — all read-only. {rule_count} rules.
  - label: "Skip"
    description: "You'll approve every file read and directory listing"
```

### Category B: Plugin Scripts (recommend: Enable)

```
question: "Category B: Plugin Scripts"
options:
  - label: "Enable (recommended)"
    description: |
      NOT a blanket uv/bash/python3 approval.
      Only approves commands targeting the plugin's own install path:
        uv run --project <plugin_cache_path>/*
        uv run <plugin_cache_path>/*
        bash <plugin_cache_path>/*
        python3 <plugin_cache_path>/*
      A random "uv run pytest" or "bash myscript.sh" still requires approval.
      Risk: Low — only plugin-internal scripts. {rule_count} rules.
  - label: "Skip"
    description: "You'll approve every plugin script execution individually"
```

### Category C: Task Management (recommend: Enable)

```
question: "Category C: Task Management"
options:
  - label: "Enable (recommended)"
    description: |
      TaskList, TaskGet, TaskCreate, TaskUpdate, TaskOutput.
      These manage the workflow checklist — no file or code changes.
      Risk: None. {rule_count} rules.
  - label: "Skip"
    description: "You'll approve every task list operation"
```

### Category D: Planning File Writes (recommend: Enable)

```
question: "Category D: Planning File Writes"
options:
  - label: "Enable (recommended)"
    description: |
      NOT a blanket Write/Edit approval. Only approves specific filename patterns:
        Write/Edit: claude-*.md (spec, plan, research, interview, TDD)
        Write: sections/index.md, sections/section-*.md
        Write: reviews/*.md, snapshot.json
        Write: deep_plan_config.json, deep_implement_config.json, deep_project_session.json
      Writing to package.json, .env, or any non-matching file still requires approval.
      Risk: Medium — writes files, but only plugin-specific name patterns. {rule_count} rules.
  - label: "Skip"
    description: "You'll approve every planning file write individually"
```

### Category E: Git Operations (recommend: Skip)

```
question: "Category E: Git Operations"
options:
  - label: "Enable"
    description: |
      git add, git commit, git checkout -b.
      Commits will happen without prompting you to review them.
      Risk: Medium — creates commits automatically. {rule_count} rules.
  - label: "Skip (recommended)"
    description: "Review each commit before it happens"
```

### Category F: Subagent Launches (recommend: Skip)

```
question: "Category F: Subagent Launches"
options:
  - label: "Enable"
    description: |
      Task tool for section-writer, code-reviewer, Explore, web-search subagents.
      These launch sub-conversations that do work in parallel.
      Risk: Low — but can consume additional API credits. {rule_count} rules.
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
