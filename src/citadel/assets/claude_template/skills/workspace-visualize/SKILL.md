---
name: workspace-visualize
description: Generate an interactive collapsible HTML tree view of the codebase with file sizes, type breakdown bar chart, and color-coded file types. Opens in your default browser. Use when exploring a new repo, understanding project structure, or identifying large files before refactoring.
allowed-tools: Bash(python3 *)
argument-hint: [path]
when_to_use: visualize, codebase map, project structure, file tree, directory tree, explore repo, large files, file breakdown
---

Generate an interactive HTML codebase visualization.

Run:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/visualize.py ${0:-.}
```

This creates `codebase-map.html` in the current directory and opens it in your default browser.

## What the visualization shows
- **Collapsible directory tree** — click folders to expand/collapse
- **File sizes** — displayed next to each file and aggregated per directory
- **Color-coded file types** — JS, TS, Python, Go, Rust, CSS, HTML and more
- **Sidebar summary** — total file count, directory count, total size, top-8 file types by size as a bar chart

Files and directories matching `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, and `build` are automatically excluded.
