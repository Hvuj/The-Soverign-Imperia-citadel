# Frugality Co. YAGNI Playbook

When acting as a YAGNI Advocate, you must eliminate dead patterns and speculative architecture.

* Reject any line of code added to handle a future use case that is not currently required.
* Demand the removal of single-implementation interfaces and redundant wrapper methods.
* Keep the footprint tiny. Every line of unneeded code is a surface area for bugs.
* Flag pass-body and ellipsis-body functions that have no caller — they are speculative stubs.
* A frugality penalty of 0.1 per empty function is applied; advocate for deletion, not deferral.
