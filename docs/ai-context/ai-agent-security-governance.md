# AI Agent Security & Governance (reference)

Reference guidance for how Citadel Legion's autonomous workers, tools, and data handling should
bdd. Sourced from the user's provided best-practices brief (NIST AI RMF + OWASP GenAI/Agentic
Top-10 aligned). This is a `reference` memory — read when working on the legion permission model,
worker spawning, credentials, or data handling. It complements the checked-in rules
`.claude/rules/prompt-leak-policy.md` and `.claude/rules/grounding.md`.

## How this maps to the legion (what is already enforced in code)

- **Least privilege by default** → `legion_orchestrator._build_worker_argv` runs headless workers in
  `dontAsk` with a narrow allowlist (`Read Grep Glob` for smoke; `+ Edit Write MultiEdit` for real
  work — never bare `Bash`, so no arbitrary command execution / network exfil). Full
  `bypassPermissions` is opt-in only via `--autonomous`.
- **Human approval for high-impact/irreversible actions** → autonomous editing requires the explicit
  `--autonomous` flag; the default never silently edits or runs shell.
- **The model is never the authorization decision-maker** → governance gates (`legion_governance`,
  `legion_board`, L5/L6) are deterministic Python; the board veto is enforced by the `audit-gate.sh`
  hook, not by a model's say-so.
- **Log and audit everything** → every worker lifecycle + gate event is appended to the run ledger
  (`.claude/state/legion-runs/<run_id>/ledger.ndjson`), schema-backed by `legion-run-ledger.schema.json`.
- **Never feed secrets to workers** → workers get a `--disallowedTools` denylist for `.env`/`.ssh`/
  `*.pem`/`*.key`/`credentials`, plus a `SECURITY_MANDATE` in every worker prompt forbidding reading,
  echoing, or exfiltrating secrets and forbidding treating retrieved content as instructions
  (prompt-injection defense).
- **Sandbox / stay in scope** → each worker's `cwd` is its own company repo; the prompt tells it to
  stay in its assigned directory.

## Permissions & access control (general)

- Separate and minimize excessive permissions (tools beyond task scope), excessive functionality
  (shell/production writes), and excessive autonomy (no human confirmation before consequential acts).
- Prefer dedicated machine accounts per agent/workflow; if one is compromised the others are unaffected.
- Set expiration on access tokens for ephemeral tasks; scope credentials narrowly (per-function keys,
  not one "can do anything" key); use separate revocable credentials for CI/CD and agent pipelines.
- Enforce user-level authorization (OAuth) so actions run under the human's identity/permissions, not
  elevated agent privileges. Put authz checks in downstream systems, validated against policy.
- Sandbox/isolate execution (containers/restricted sandboxes); normalize paths to block traversal
  (`../../`); whitelist folders rather than blacklist sensitive files.
- Rotate credentials immediately on suspicion (investigate after). Avoid tool combinations that
  together create an exfiltration path (file-read + network-send).
- Treat AI-generated code/actions as an untrusted junior dev: require human review (branch protection,
  ≥1 human approver) even for AI-authored PRs.

## What NOT to feed AI models

- Never feed `.env` files, hardcoded secrets, SSH keys / `~/.ssh`, API keys, tokens, passwords, or
  certificates (`*.pem`/`*.key`). Use exclusion rules so they never enter the context window.
- Don't feed non-public strategic material (roadmaps, financials, HR/customer data, unpublished IP) or
  proprietary/closed codebases to third-party consumer AI tools without an approved, sandboxed deployment.
- `.gitignore` is NOT protection — it only stops git commits, not local AI reads. Treat
  `.claudeignore`/`.cursorignore` as partial, not complete. Don't assume paid tiers make raw secrets safe.
- Don't paste secrets into chat as a "quick fix"; scan generated code for secrets and use placeholders.
- Be cautious with content ingested from untrusted external sources (PR diffs, dependency audits) —
  prompt-injection risk. Avoid feeding regulated PII; once in prompts/logs/memory it is hard to control.
- Litigation can force providers to retain logs indefinitely — "zero retention" is not a guarantee.

## Better alternatives to plaintext secrets

- Eliminate the file, not just hide it — if there's no `.env`, there's nothing to read.
- Use a secrets manager for runtime injection (1Password, AWS Secrets Manager, Doppler, Infisical).
- Use secret references (`op://...`) resolved only at execution time, not raw values.
- Encrypted `.env` is a partial measure (protects passive reads, not an agent with shell access).
- Set project-level defaults (`~/.claude/settings.json`) so file-access restrictions apply everywhere.
- Layer defenses: AI ignore files → pre-commit hooks → CI/CD secret scanning → secrets managers.
- Run secret scanners (e.g. gitleaks) against the working tree AND git history.

## Governance & LLM/agentic risk (OWASP-aligned)

- Ground the program in NIST AI RMF; principles: accountability, transparency, fairness, privacy,
  security. Keep a centralized inventory of AI use cases/models/tools; tiered scrutiny by risk.
- LLM Top-10 to guard: prompt injection (direct + indirect), sensitive-info disclosure, supply-chain,
  data/model poisoning, improper output handling, excessive agency, system-prompt leakage,
  vector/embedding weaknesses, misinformation/hallucination, unbounded consumption (rate/cost limits).
- Agentic Top-10 to guard: goal hijacking, tool misuse (esp. dangerous tool *combinations*), agent
  identity/privilege, agentic supply chain (MCP/plugins), unexpected code execution, memory/context
  poisoning, inter-agent comms, cascading-failure containment, human-agent trust exploitation, rogue
  agents. Test continuously (behavior changes with model/prompt/tool updates), not periodically.
- Regulatory: track the EU AI Act (penalties up to €35M / 7% turnover) and evolving US policy; keep
  audit trails; map controls to NIST AI RMF / OWASP / ISO-IEC 42001 rather than bespoke programs.

## Practical note (this environment)

File-creation and bash tasks here run in an isolated container with **network access disabled**, and
mounted skill/upload dirs are read-only. Treat credentials as with any AI tool: never paste real
secrets into chat, and never place real secrets in files handed to the agent — use fake/placeholder
values. Authoritative primary sources to build a program around: **NIST AI RMF** and the
**OWASP GenAI Security Project** (genai.owasp.org).
