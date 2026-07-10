# settings.local.json

`settings.local.json` is machine-specific and is usually generated/edited by Claude Code as local permission history.

This package includes a broad local template so the workflow works immediately.

If you want to preserve your exact existing long allow-list, copy your current file over this one after installing:

```bash
cp /path/to/your/current/.claude/settings.local.json ${CLAUDE_PROJECT_DIR}/.claude/settings.local.json
```

Do not commit `settings.local.json`.
