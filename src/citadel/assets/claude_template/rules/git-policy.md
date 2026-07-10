# Git Policy

Never run git commands or make commits unless the user explicitly asks. Always keep a human in the loop for any repository write-back decision.

## Rules

- Do not run `git commit`, `git push`, `git add`, `git checkout`, `git reset`, `git rebase`, `git merge`, or any other git command unless the user explicitly requests it in the current message.
- Do not commit code changes, memory updates, rule changes, or any file as a side-effect of completing a task.
- Tools and scripts in this project (orchestrators, compilers, write-back engines) must never shell out to git as part of their autonomous operation.

## Allowed

- Reading git state is allowed when needed for task context: `git status`, `git diff`, `git log`, `git show`.
- Running git commands when the user explicitly says "commit this", "push", "create a PR", "make a branch", or similar direct instruction.

## Human-in-the-loop

When a task completes and changes are ready for the repository:

1. Describe what was changed and why (compact summary).
2. Write any pending delta to `.claude/state/human-intervention/` if applicable.
3. Stop and wait for the user to decide whether and how to commit.
4. Never auto-commit, auto-push, or trigger CI without an explicit user instruction in the current session turn.
