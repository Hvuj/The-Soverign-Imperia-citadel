# replicate-feature

Zero-token feature replication across multiple targets.

## When to use

When you've built a feature for one org unit or module and need to apply the same
change to N other targets without token usage.

## Steps

1. Capture the current diff as a template:
   ```bash
   python tools/feature_replicator.py capture \
     --id "<template-slug>" \
     --desc "<what this does>" \
     --unit "<source-unit>" \
     --placeholders "TARGET_MODULE,TARGET_CLASS" \
     --validate "python -m pytest tests/ -x -q"
   ```

2. Verify the template was registered:
   ```bash
   python tools/feature_replicator.py list
   ```

3. Replicate to targets (JSON array of param dicts):
   ```bash
   python tools/feature_replicator.py replicate \
     --id "<template-slug>" \
     --targets '[{"TARGET_MODULE":"client_b","TARGET_CLASS":"ClientBProcessor"}]'
   ```
   Each target runs backup → patch → validate → rollback on failure.

4. Check results — any failures are reported with the rollback status.

## Zero-token guarantee

`feature_replicator.py` never calls any LLM. All transformations are deterministic
string replacements from a registry-controlled patch set.

## When NOT to use

- When changes require judgment (e.g., different business logic per target) — those need
  per-target implementation.
- When the diff is not yet captured in the registry — run `capture` first.
