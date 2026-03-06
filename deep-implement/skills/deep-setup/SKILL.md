---
name: deep-setup
description: One-time setup for the deep-trilogy plugin. Configures context percentage tracking in your statusline so context checkpoints show actual usage. Run this after installing the plugin.
---

# Deep Trilogy Setup

This skill configures context percentage tracking so that `/deep-plan`, `/deep-implement`, and `/deep-project` can show you your actual context usage at checkpoints.

## What It Does

The deep-trilogy plugins check context usage before expensive operations (external LLM calls, large writes). Without setup, these checkpoints show "Context usage: unknown". After setup, they show the actual percentage (e.g., "Context usage: 62%").

## Steps

### 0. Resolve Plugin Root

Look for `DEEP_PLUGIN_ROOT=<path>` in your conversation context (injected by the SessionStart hook). Extract the path value — you'll substitute it directly into commands below.

**IMPORTANT:** `DEEP_PLUGIN_ROOT` is conversation context, NOT a shell environment variable. You must substitute the actual path value into commands. Do NOT use `${DEEP_PLUGIN_ROOT}` in bash — it will be empty.

If `DEEP_PLUGIN_ROOT` is not in your context, discover it:
```bash
find ~/.claude/plugins/cache -name "plugin.json" -path "*avi8or*deep-trilogy*" -type f 2>/dev/null | head -1 | xargs dirname | xargs dirname
```

Store the resolved path as `plugin_root` for all subsequent commands.

### 1. Check Current State

Run the check script (substitute `plugin_root` value directly):

```bash
python3 <plugin_root>/scripts/tools/setup-context-tracking.py --check --plugin-root "<plugin_root>"
```

If the output shows `"configured": true`, tell the user setup is already done and they're good to go. Stop here.

### 2. Confirm With User

Before modifying settings, explain what will happen:

- **If they have no statusline**: A minimal statusline will be installed that shows model name and context percentage
- **If they have an existing statusline**: It will be wrapped to also write context percentage to `/tmp/claude-context-pct` — their existing statusline appearance is preserved

Ask the user to confirm before proceeding.

### 3. Run Setup

```bash
python3 <plugin_root>/scripts/tools/setup-context-tracking.py --plugin-root "<plugin_root>"
```

### 4. Verify

Tell the user:

```
Setup complete! Context tracking is now configured.

To activate: restart Claude Code (exit and relaunch).

After restart, context checkpoints will show your actual usage percentage
instead of "unknown". The percentage updates continuously via the statusline.
```

### Dependencies

- `jq` must be installed (used to parse statusline JSON). Check with `which jq`.
  - If missing, suggest: `brew install jq` (macOS) or `apt install jq` (Linux)
