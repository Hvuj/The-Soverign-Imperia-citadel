#!/usr/bin/env python3
"""output_normalizer.py — Validate and normalize provider output against Citadel schemas.

Local-only, no AI calls, no external APIs.

Usage:
  python tools/output_normalizer.py --schema ask-response --input output.json [--strict]
  echo '{"answer":"hi"}' | python tools/output_normalizer.py --schema ask-response --stdin [--strict]
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CITADEL_WORKSPACE") or Path(__file__).resolve().parents[1])
SCHEMAS_DIR = ROOT / ".claude" / "schemas"

_DEFAULTS: dict[str, dict] = {
    "ask-response": {
        "source": "unavailable",
        "confidence": "low",
        "category": "unknown",
        "evidence": [],
        "assumptions": [],
        "missing_evidence": [],
        "warnings": [],
        "model_fallback_used": False,
        "local_context_used": False,
        "claim_verification": {"enabled": False, "unsupported_claims_removed": 0},
        "suggested_questions": [],
    },
    "validation-result": {
        "commands": [],
        "failed_commands": [],
        "warnings": [],
    },
    "learning-candidate": {
        "what_worked": [],
        "what_failed": [],
        "routing_updates": [],
        "context_updates": [],
        "validation_updates": [],
        "skill_updates": [],
        "agent_updates": [],
        "memory_candidates": [],
        "artifact_candidates": [],
    },
    "provider-plan": {
        "steps": [],
        "allowed_files": [],
        "risks": [],
        "evidence": [],
    },
    "provider-review": {
        "findings": [],
        "evidence": [],
    },
}


def load_schema(schema_name: str) -> dict | None:
    """Load schema by name (with or without .schema.json suffix)."""
    name = schema_name
    if not name.endswith(".schema.json"):
        name = name + ".schema.json"
    path = SCHEMAS_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def get_required_fields(schema: dict) -> list[str]:
    return schema.get("required", [])


def get_properties(schema: dict) -> dict:
    return schema.get("properties", {})


def validate_required(data: dict, required: list[str]) -> list[str]:
    """Return list of missing required fields."""
    return [f for f in required if f not in data]


def normalize(data: dict, schema_name: str, schema: dict) -> tuple[dict, list[str]]:
    """
    Normalize data to match schema.
    Returns (normalized_data, list_of_changes_made).
    """
    required = get_required_fields(schema)
    props = get_properties(schema)
    changes = []

    if schema.get("additionalProperties") is False:
        known = set(props.keys())
        extra = [k for k in list(data.keys()) if k not in known]
        for k in extra:
            del data[k]
            changes.append(f"removed unknown field: {k}")

    defaults = _DEFAULTS.get(schema_name, {})
    for field in required:
        if field not in data:
            if field in defaults:
                data[field] = defaults[field]
                changes.append(f"added default for missing required field: {field}")

    return data, changes


def check_type(value: object, type_def: str) -> bool:
    """Basic type checking."""
    if type_def == "string":
        return isinstance(value, str)
    if type_def == "boolean":
        return isinstance(value, bool)
    if type_def == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_def == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_def == "array":
        return isinstance(value, list)
    if type_def == "object":
        return isinstance(value, dict)
    return True


def validate_types(data: dict, schema: dict) -> list[str]:
    """Return list of type violation descriptions."""
    errors = []
    props = get_properties(schema)
    for field, spec in props.items():
        if field not in data:
            continue
        t = spec.get("type")
        if t and isinstance(t, str) and not check_type(data[field], t):
            errors.append(f"field '{field}': expected {t}, got {type(data[field]).__name__}")
    return errors


def validate_enums(data: dict, schema: dict) -> list[str]:
    """Return list of enum violation descriptions."""
    errors = []
    props = get_properties(schema)
    for field, spec in props.items():
        if field not in data:
            continue
        enum = spec.get("enum")
        if enum and data[field] not in enum:
            errors.append(f"field '{field}': value {data[field]!r} not in enum {enum}")
    return errors


def normalize_output(
    raw: dict,
    schema_name: str,
    strict: bool = False,
) -> dict:
    """
    Validate and optionally normalize provider output.
    Returns result dict with status, data, errors, changes.
    """
    schema = load_schema(schema_name)
    if schema is None:
        return {
            "status": "error",
            "error": f"Schema not found: {schema_name}",
            "schema": schema_name,
            "data": raw,
        }

    required = get_required_fields(schema)
    missing = validate_required(raw, required)

    if missing and strict:
        return {
            "status": "invalid",
            "error": f"Missing required fields: {missing}",
            "schema": schema_name,
            "missing_fields": missing,
            "data": raw,
        }

    import copy
    data = copy.deepcopy(raw)
    data, changes = normalize(data, schema_name, schema)

    type_errors = validate_types(data, schema)
    enum_errors = validate_enums(data, schema)

    all_errors = type_errors + enum_errors
    if all_errors and strict:
        return {
            "status": "invalid",
            "error": "Type or enum validation failed",
            "schema": schema_name,
            "validation_errors": all_errors,
            "data": data,
        }

    status = "valid" if not all_errors else "normalized_with_warnings"
    return {
        "status": status,
        "schema": schema_name,
        "changes": changes,
        "warnings": all_errors,
        "data": data,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and normalize provider output against a Citadel schema.")
    parser.add_argument("--schema", required=True,
                        help="Schema name (e.g. ask-response or ask-response.schema.json).")
    parser.add_argument("--input", default=None, help="Input JSON file path.")
    parser.add_argument("--stdin", action="store_true", help="Read JSON from stdin.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if output is invalid and cannot be normalized.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    if args.stdin or (not args.input and not sys.stdin.isatty()):
        raw_text = sys.stdin.read()
    elif args.input:
        try:
            raw_text = Path(args.input).read_text()
        except OSError as exc:
            sys.stderr.write(f"Error reading input: {exc}\n")
            sys.exit(1)
    else:
        parser.error("Provide --input <file> or pipe JSON via stdin.")

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        result = {
            "status": "error",
            "error": f"Input is not valid JSON: {exc}",
            "schema": args.schema,
        }
        print(json.dumps(result, indent=2 if args.pretty else None))
        sys.exit(1)

    result = normalize_output(raw_data, args.schema, args.strict)
    print(json.dumps(result, indent=2 if args.pretty else None))

    if args.strict and result["status"] in ("invalid", "error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
