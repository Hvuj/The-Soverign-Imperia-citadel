---
name: pr-review-live
description: Review a pull request with live data injected from GitHub — diff, comments, and changed file list fetched before Claude reads anything. Run /pr-review-live [pr-number] or omit the number to review the current branch's PR.
disable-model-invocation: true
allowed-tools: Bash(gh *)
argument-hint: [pr-number]
---

## Pull request context

**Diff:**
!`gh pr diff ${0:-} 2>/dev/null || echo "(no diff available — ensure gh auth is set up and a PR exists for this branch)"`

**Description and comments:**
!`gh pr view ${0:-} --comments 2>/dev/null || echo "(could not fetch PR view)"`

**Changed files:**
!`gh pr diff ${0:-} --name-only 2>/dev/null || echo "(could not list changed files)"`

## Review instructions

Review the PR above across these dimensions:

1. **Correctness** — logic errors, off-by-ones, unhandled edge cases, incorrect assumptions
2. **Security** — injection, auth bypass, secrets in code, missing input validation, OWASP top 10
3. **Performance** — N+1 queries, unnecessary allocations, blocking I/O in hot paths
4. **Test coverage** — behavior changes without corresponding test updates
5. **Code style** — naming clarity, dead code, unnecessary comments, abstraction altitude

Format each finding:
```
[SEVERITY] file.py:42 — description of the problem
  Suggestion: what to change
```
Severity: **critical** (must fix before merge) / **major** (should fix) / **minor** (nice to fix).

End with a one-line merge verdict: Ready / Needs changes / Blocked.
