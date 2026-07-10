"""citadel.services — the SOLID domain layer for the corporate legion.

Sub-packages:
  corporate  — Legion (the corporate) aggregating Company objects (workspace repos).
  index      — abstractions + concrete indexes (symbols, imports, commits).
  cache      — the resident RAM cache (LRU) and its socket client.
  reuse      — zero-token reuse decision + replication execution.

Design intent: callers depend on these abstractions, not on the standalone
tools/*.py scripts (DIP). The scripts remain the executable/daemon entry points;
the services give the CLI and other Python callers a clean, typed façade.
"""
