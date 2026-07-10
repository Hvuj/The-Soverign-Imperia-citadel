#!/usr/bin/env python3
"""
Telemetry Ledger — Phase 17: The Legion Overlord Interface & Kinetic Graph.

Append-only NDJSON event emitter for SOVEREIGN-IMPERIA-CITADEL pipeline telemetry.
Producers (orchestrator, L5, L6) call emit() to record routing and gate events;
the Citadel UI server tails the ledger and pushes events to connected browsers as SSE.

Design principles:
  - Fail-soft: emit() never raises; OSError is silently caught.
  - Atomic POSIX appends: single write() of a <4096-byte line (PIPE_BUF safe on macOS/Linux).
  - Decoupled: no dependency on the server, orchestrator, or any framework class.
  - Root-anchored: ledger path resolved from _ROOT (same convention as task_ledger.py).

Event schema (one JSON object per line):
  {
    "ts":          "<UTC isoformat>",
    "kind":        "route" | "l5_pass" | "l6_pass" | "l5_veto" | "l6_fail" | "heartbeat",
    "source_node": "<graph node id>",
    "target_node": "<graph node id>",
    "color":       "cyan" | "green" | "red",
    "state":       "routing" | "pass" | "veto" | "fail",
    "message":     "<short description, max 500 chars>",
    "seq":         <int millisecond timestamp for ordering>
  }
"""


import argparse
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
_LEDGER_NAME = "telemetry-events.ndjson"

_KIND_MAP: dict[str, tuple[str, str]] = {
    "route": ("cyan", "routing"),
    "l5_pass": ("green", "pass"),
    "l6_pass": ("green", "pass"),
    "l5_veto": ("red", "veto"),
    "l6_fail": ("red", "fail"),
    "heartbeat": ("cyan", "routing"),
}


def _state_dir(root: Path | None = None) -> Path:
    """Return .claude/state under root, creating it if absent."""
    base = root if root is not None else _ROOT
    d = base / ".claude" / "state"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def emit(
    kind: str,
    source_node: str,
    target_node: str,
    message: str = "",
    *,
    color: str | None = None,
    state: str | None = None,
    _ledger_path: Path | None = None,
) -> None:
    """Append one telemetry event to the NDJSON ledger.

    Fail-soft: any OSError is silently swallowed so telemetry never breaks the pipeline.
    Each write is a single atomic append of a <4096-byte JSON line (PIPE_BUF safe).

    Args:
        kind:         Event kind (see _KIND_MAP for color/state defaults).
        source_node:  Graph node id of the event origin.
        target_node:  Graph node id of the event destination.
        message:      Human-readable description (truncated to 500 chars).
        color:        Override color (cyan|green|red); defaults derived from kind.
        state:        Override state string; defaults derived from kind.
        _ledger_path: Override ledger path for hermetic testing.
    """
    default_color, default_state = _KIND_MAP.get(kind, ("cyan", "routing"))
    rec: dict = {
        "color": color if color is not None else default_color,
        "kind": kind,
        "message": (message or "")[:500],
        "seq": int(time.time() * 1000),
        "source_node": source_node,
        "state": state if state is not None else default_state,
        "target_node": target_node,
        "ts": datetime.now(UTC).isoformat(),
    }
    line = json.dumps(rec, sort_keys=True) + "\n"

    if len(line.encode("utf-8")) > 4000:
        rec["message"] = rec["message"][:200]
        line = json.dumps(rec, sort_keys=True) + "\n"

    ledger = _ledger_path if _ledger_path is not None else _state_dir() / _LEDGER_NAME
    try:
        with ledger.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="SOVEREIGN-IMPERIA-CITADEL Telemetry Ledger — Phase 17: emit pipeline events")
    _parser.add_argument("--test", action="store_true", help="Run self-test and exit 0 on pass.")
    _parser.add_argument(
        "--emit",
        nargs=3,
        metavar=("KIND", "SRC", "TGT"),
        help="Emit one event to the default ledger.",
    )
    _args = _parser.parse_args()

    if _args.test:
        _failures: list[str] = []
        with tempfile.TemporaryDirectory() as _tmp:
            _ledger = Path(_tmp) / _LEDGER_NAME

            for _kind in ("route", "l5_pass", "l6_pass", "l5_veto", "l6_fail"):
                emit(_kind, "src-node", "tgt-node", f"test {_kind}", _ledger_path=_ledger)

            if not _ledger.exists():
                _failures.append("Ledger file was not created.")
            else:
                _lines = _ledger.read_text(encoding="utf-8").strip().splitlines()
                if len(_lines) != 5:
                    _failures.append(f"Expected 5 lines, got {len(_lines)}.")
                for _line in _lines:
                    try:
                        _evt = json.loads(_line)
                    except json.JSONDecodeError as _e:
                        _failures.append(f"Invalid JSON line: {_e}")
                        continue
                    for _key in ("ts", "kind", "source_node", "target_node", "color", "state", "message", "seq"):
                        if _key not in _evt:
                            _failures.append(f"Missing key {_key!r} in event kind={_evt.get('kind')!r}.")

            emit("route", "a", "b", _ledger_path=Path("/dev/null/impossible"))

        if _failures:
            print("TelemetryLedger --test FAILED:")
            for _f in _failures:
                print(f"  {_f}")
            sys.exit(1)

        print(
            json.dumps(
                {"test": "TelemetryLedger --test", "cases_run": 5, "result": "PASS"},
                indent=2,
            )
        )
        print("TelemetryLedger --test passed.")
        sys.exit(0)

    if _args.emit:
        emit(_args.emit[0], _args.emit[1], _args.emit[2])
        sys.exit(0)

    _parser.print_help()
    sys.exit(1)
