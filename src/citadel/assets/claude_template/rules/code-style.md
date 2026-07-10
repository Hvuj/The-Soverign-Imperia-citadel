# Code Style Rules (The Sovereign Imperia Citadel)

Target: Python **3.12+** (`requires-python >=3.12`). These are enforced by `ruff` (UP/E/F/I/…),
`ty`, and `tools/best_practices_lint.py`. Legion workers write NEW code to these standards and
adapt to each target repo's own Python version (see below).

## Typing & annotations
- **Do NOT use `from __future__ import annotations`.** It is redundant on 3.12 and makes annotations
  lazy strings; we want eager, runtime-true annotations. Enforced (lint fails if reintroduced).
- **PEP 585**: use builtin generics — `list`, `dict`, `set`, `frozenset`, `tuple`, `type` — never
  `typing.List/Dict/Set/FrozenSet/Tuple/Type`.
- **PEP 604**: use `X | Y` and `X | None`, never `typing.Optional`/`typing.Union`.
- **PEP 673**: self-referential methods/classmethods return `Self` (`from typing import Self`), never
  the bare enclosing class name (that NameErrors under eager evaluation).
- Full type hints on public functions; `@dataclass(slots=True)` for records.

## Idioms & correctness (PEP 8 / PEP 20)
- 4-space indent; snake_case funcs/vars, PascalCase classes, UPPER_CASE constants; line length 120.
- No bare `except:`; catch specific exceptions; `raise New from err` to preserve context.
- Comparisons to singletons with `is`/`is not`; `isinstance()` not type equality; truthiness for
  empty sequences (`if not seq:`).
- **No narration comments — in ANY language** (`#`, `//`, `/* */`, JSDoc, docstrings alike). Code and
  names are the documentation. A comment is allowed ONLY when it is 100% necessary: a non-obvious
  rationale, gotcha, invariant, or external constraint the code itself cannot convey. Never restate
  what the code plainly does (e.g. `// bounded fan-out over parallel()`, `# loop over items`) — that is
  pure token waste. Keep a one-line module/class docstring only where the purpose is non-obvious.
  Python `#` narration is enforced by `tools/best_practices_lint.py`; the same bar applies to
  JS/TS/other languages by review.
- `secrets` for tokens, `yaml.safe_load`, parameterized SQL, never `eval`/`exec` on input.

## Performance (always pick the most performant best-practice option)
- **Vectorize** where possible (array/dataframe/set-ops libraries) instead of Python loops on large data.
- Right data structure: `set`/`dict` for O(1) membership; `collections.deque` for ends; `bisect` for
  sorted lookups; `heapq` for priority; generators for large streams.
- Profile before micro-optimizing; prefer `''.join()` over `+=` string building.
- Predict scale/size for each feature and choose the structure/algorithm to match it.

### Scale-prediction checklist (mandatory for non-trivial features)

Before choosing a data structure or algorithm:

1. Predict `rows`, `bytes`, and `qps` (0 for batch-only) at steady state.
2. Pick the structure/algorithm that fits that prediction (see the data-structure
   picks above), not whatever is simplest to write first.
3. Write down why — the rationale, and the scale threshold at which it should be
   revisited.

Record this as a `.claude/schemas/scale-prediction.schema.json`-conformant artifact
(`feature`, `predicted_scale{rows,bytes,qps}`, `chosen_structure`, `chosen_algorithm`,
`rationale`, optional `reconsider_if`). Required in the e2e-validation plan
`legion_review.py` generates on feature-improvement approval; recommended for any
other non-trivial performance-sensitive change.

## Cross-platform (Win/Mac/Linux)
- No hard dependency on POSIX-only calls without a fallback (`os.killpg`, `AF_UNIX`, symlinks).
  Guard platform-specific code and provide a portable path.

## Workspace-agnostic
- No client/vendor/product names hard-coded in authored code or config (`tools/brand_lint.py`).
  Discover the workspace, its repos, domains, and domain logic — never assume a specific client.
