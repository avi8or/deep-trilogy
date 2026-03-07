---
name: deep-resume
description: Resume an active deep-plan, deep-implement, or deep-project session after /clear. Discovers the snapshot or project artifacts automatically and invokes the correct skill.
---

# Deep Resume

Resumes active deep-trilogy sessions. Works after `/clear`, new terminal sessions, or any time you want to pick up where you left off.

## Step 1: Resolve Plugin Root

Look for `DEEP_PLUGIN_ROOT=<path>` in your conversation context (injected by the SessionStart hook). Extract the path value.

**IMPORTANT:** `DEEP_PLUGIN_ROOT` is conversation context, NOT a shell environment variable. You must substitute the actual path value into commands. Do NOT use `${DEEP_PLUGIN_ROOT}` in bash — it will be empty.

If `DEEP_PLUGIN_ROOT` is not in your context, discover it:
```bash
find ~/.claude/plugins/cache -name "plugin.json" -path "*avi8or*deep-trilogy*" -type f 2>/dev/null | head -1 | xargs dirname | xargs dirname
```

Store the resolved path as `plugin_root` for the next step.

## Step 2: Run Discovery Script

Run the discover-session script (substitute `plugin_root` directly):
```bash
uv run --project <plugin_root>/deep-plan <plugin_root>/scripts/tools/discover-session.py
```

The script outputs JSON. Parse it and proceed based on `status`:

## Step 3: Handle Result

### If `status` is `"found"`:

**Check `complete` field first.** If `true`:
```
═══════════════════════════════════════════════════════════════
DEEP-RESUME: {plugin} session is complete
═══════════════════════════════════════════════════════════════
All work finished. Start a new session with:
  /deep-plan, /deep-implement, or /deep-project
═══════════════════════════════════════════════════════════════
```
Stop here.

**Otherwise, print the resume banner:**
```
═══════════════════════════════════════════════════════════════
DEEP-RESUME: Resuming {plugin} session
═══════════════════════════════════════════════════════════════
Source:    {source} (snapshot or artifact-scan)
Progress:  {progress}
Next:      {resume_step_name}
Branch:    {git_branch}
Path:      {working_dir}
═══════════════════════════════════════════════════════════════
```

**Set resume context.** Print these key=value pairs so the target skill sees them:
```
DEEP_RESUME_STEP={resume_step}
DEEP_RESUME_NAME={resume_step_name}
DEEP_PLUGIN={plugin}
DEEP_SNAPSHOT={snapshot_path or "none"}
DEEP_PROGRESS={progress}
DEEP_BRANCH={git_branch}
```

**Invoke the skill** using the `Skill` tool:
- `plugin` is `deep-plan` → `Skill(skill="deep-trilogy:deep-plan")`
- `plugin` is `deep-implement` → `Skill(skill="deep-trilogy:deep-implement")`
- `plugin` is `deep-project` → `Skill(skill="deep-trilogy:deep-project")`

The target skill will see `DEEP_RESUME_STEP` in conversation context and auto-resume.

### If `status` is `"multiple"`:

Multiple plugin sessions detected. Present the `sessions` array as choices:

Use `AskUserQuestion`:
```
question: "Multiple sessions detected. Which one to resume?"
options: (one per session)
  - label: "{plugin} — {progress} — {working_dir}"
```

After user selects, use that session's data and proceed as `"found"` above.

### If `status` is `"not_found"`:

```
═══════════════════════════════════════════════════════════════
DEEP-RESUME: No active session found
═══════════════════════════════════════════════════════════════
No deep-plan, deep-implement, or deep-project artifacts
detected in this directory or its parents.

Start a new session:
  /deep-plan      — Plan a feature from a spec
  /deep-implement — Implement sections from a plan
  /deep-project   — Decompose requirements into specs
═══════════════════════════════════════════════════════════════
```

### If `status` is `"error"`:

Print the error message from the JSON and suggest the user check the config file manually.
