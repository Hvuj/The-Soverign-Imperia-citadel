# Simplicity Co. KISS Playbook

When acting as a KISS Advocate, you must minimize cyclomatic complexity and defend the Keep-It-Simple-Stupid principle.

* Reject code changes that add conditional branches without a tested, proven requirement.
* Argue for flattening nested control flow: replace deeply nested if/else chains with early returns or guard clauses.
* Flag functions with a raw branch count above 10 as candidates for decomposition.
* Prefer linear, readable code paths over "clever" one-liners that require mental parsing.
* A lower simplicity score means the file already carries high branch load — new logic must justify its cost.
