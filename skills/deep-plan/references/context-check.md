# Context Check Protocol

Before critical operations, check context usage and optionally prompt the user.

## Key Insight

**File-based recovery is the real resilience mechanism, not compaction.**

- Snapshots persist workflow state across `/clear`
- SessionStart hook injects resume info automatically
- SKILL.md is freshly loaded on re-run
- Tasks get reconciled from file state

Compaction keeps the session alive but may cause instruction loss. `/clear` gives a clean slate with auto-resume.

## Checking Context Usage

Read the context percentage from the shared file (written by the statusline):

```bash
cat /tmp/claude-context-pct 2>/dev/null
```

This returns 0-100. The file is written by the plugin's `scripts/tools/write-context-pct.sh` (see that file for setup instructions).

**If the file does not exist** (statusline not configured), fall back to always presenting the prompt at scheduled checkpoints. On first occurrence, mention: "For smarter context management, configure the context monitor — see `scripts/tools/write-context-pct.sh` in the plugin directory."

### Decision Thresholds

| Context % | Action |
|-----------|--------|
| ≥ 85% | **Always prompt, strongly recommend /clear** — auto-compact is imminent |
| 70-84% | **Always prompt** at any checkpoint |
| 50-69% | Prompt only at scheduled checkpoints (before External LLM Review, before Section Split) |
| < 50% | Skip the prompt, proceed immediately |

### Prompt Format

When prompting, include the context percentage:

```
Context check before: {operation} (context: {PCT}%)
```

Use `AskUserQuestion` with these options:

1. **"/clear"** — Fresh context, auto-resumes on next session
2. **"Continue"** — Proceed in current session

## Option Handling

**If user chooses "Continue":**
- Proceed with the operation
- Auto-compact will trigger at ~95% context if needed

**If user chooses "/clear":**
- User runs `/clear` — that's it
- The snapshot is already written, so the next session auto-resumes
- No need to re-type the /deep-plan command

## When to Run Context Checks

- Before External LLM Review (upcoming operation: "External LLM Review")
- Before Section Split (upcoming operation: "Section splitting")
- Any time context ≥ 70% at a natural pause point

## Configuration

In `config.json`:
```json
{
  "context": {
    "check_enabled": true
  }
}
```

Set `check_enabled` to `false` to skip all context prompts (context % checks still apply at ≥ 85%).
