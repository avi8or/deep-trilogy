#!/bin/bash
# Statusline addon: writes context window percentage to /tmp/claude-context-pct
#
# This script is designed to be called FROM your existing statusline.sh.
# Add this line to your statusline.sh (after reading input):
#
#   echo "$input" | "${DEEP_PLUGIN_ROOT}/scripts/tools/write-context-pct.sh"
#
# Or if you don't have a statusline, use this as your statusline directly:
#
#   Run /deep-setup to configure this automatically, or manually set:
#   {
#     "statusLine": {
#       "type": "command",
#       "command": "<plugin-cache-path>/scripts/tools/write-context-pct.sh"
#     }
#   }
#
# When used as a standalone statusline, it displays a minimal context bar.
# When piped to from another statusline, it writes silently (no output).

input=$(cat)
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)

# Write percentage to shared file for plugins to read
echo "$PCT" > /tmp/claude-context-pct 2>/dev/null

# If run as standalone statusline (not piped from another script), show output
if [ -t 1 ] || [ -z "${STATUSLINE_PARENT:-}" ]; then
  # Only show output if there's no parent statusline piping to us
  # Detect: if we got valid data and stdout is the terminal
  if [ "$PCT" != "0" ] && [ "$PCT" != "" ]; then
    if [ "$PCT" -lt 50 ]; then COLOR="\033[32m"
    elif [ "$PCT" -lt 80 ]; then COLOR="\033[33m"
    else COLOR="\033[31m"
    fi
    MODEL=$(echo "$input" | jq -r '.model.display_name // "—"')
    echo -e "${COLOR}${MODEL} | ${PCT}% context\033[0m"
  fi
fi
