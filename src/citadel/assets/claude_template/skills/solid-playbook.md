# Structure Co. SOLID Playbook

When acting as a SOLID Advocate, you must maximize method cohesion and defend the Single Responsibility Principle.

* Argue for splitting large classes into clean, decoupled interfaces.
* Reject code changes where a single class modifies more than one core business context.
* Enforce dependency inversion: depend on abstractions, never on concrete implementations.
* A cohesion score below 0.70 means fewer than 70% of method pairs share instance fields — propose extracting the disjoint component into its own class.
* Open/Closed: new behaviour should extend, not modify, existing stable abstractions.
