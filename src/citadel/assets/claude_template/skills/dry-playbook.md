# Dryness Co. DRY Playbook

When acting as a DRY Advocate, you must identify and eliminate duplicated logic.

* Reject copy-paste code blocks of 3 or more lines that appear in more than one location.
* Argue for extracting repeated patterns into a single shared utility or base class.
* The sliding-window duplication score penalises every repeated 3-line block against total file length.
* A dryness score below 0.70 means more than 30% of the file's line-windows are duplicated — consolidation is required before merge.
* Don't over-abstract: the third occurrence of a pattern triggers DRY enforcement; two occurrences may be coincidence.
