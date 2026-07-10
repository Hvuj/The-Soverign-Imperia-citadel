---
name: session-logger
description: Append a timestamped note to this session's activity log. Use to record decisions, key findings, or milestones during long sessions so the log outlasts context compaction.
disallowed-tools: AskUserQuestion
argument-hint: [note to log]
---

Append to the session log and confirm:

```!
mkdir -p .claude/state/sessions
LOGFILE=".claude/state/sessions/${CLAUDE_SESSION_ID}.log"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $ARGUMENTS" >> "$LOGFILE"
echo "--- Last 5 entries in $LOGFILE ---"
tail -5 "$LOGFILE"
```

Confirm the note was logged and echo back the last 5 entries shown above.
