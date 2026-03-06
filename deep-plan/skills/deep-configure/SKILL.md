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

Present each category one at a time using `AskUserQuestion`. Use the info from the check output's `categories` field.

**For each category (A through F), ask:**

```
question: "Category {id}: {name}"
options:
  - label: "Enable"
    description: "{description} | Risk: {risk} | {rule_count} rules"
  - label: "Skip"
    description: "Do not auto-approve these operations"
```

If `fully_configured` is true for a category, note "(already configured)" in the description.

**Default recommendations per category:**
- A (Reading & Navigation): recommend Enable
- B (Plugin Scripts): recommend Enable
- C (Task Management): recommend Enable
- D (Planning File Writes): recommend Enable
- E (Git Operations): recommend Skip
- F (Subagent Launches): recommend Skip

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
