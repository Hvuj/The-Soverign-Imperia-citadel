---
id: dynamic-directory-brain
title: Dynamic Directory Brain
type: workflow
tags: [directory, dynamic-map, cache, graph]
links: [directory-access-sentinel, directory-brain-mapper, directory-brain-indexer, directory-reuse-router, directory-change-detector]
files:
  - .claude/rules/dynamic-directory-brain.md
  - tools/dir_brain_mapper.py

---

# Dynamic Directory Brain

Maps every newly accessed directory once, then reuses compact directory maps for future work.
