#!/usr/bin/env python3
"""
Validate the skill-scanner GitLab CI component spec YAML.

Checks:
  1. Every --- block in the file is valid YAML.
  2. The spec block (first non-empty document) contains spec.inputs.
  3. Every input definition has 'type' and 'description' fields.
     'default' is optional — some inputs are intentionally required.

Usage:
    python3 ci/validate-component-spec.py [path]
    COMPONENT_SPEC=<path> python3 ci/validate-component-spec.py

Exit codes: 0 = valid, 1 = validation error, 2 = usage/file error.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml


def main() -> None:
    path_str = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("COMPONENT_SPEC", "")
    if not path_str:
        print("Usage: validate-component-spec.py <path>  OR  set COMPONENT_SPEC env var")
        sys.exit(2)

    path = Path(path_str)
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(2)

    content = path.read_text(encoding="utf-8")

    try:
        parsed = list(yaml.safe_load_all(content))
    except yaml.YAMLError as e:
        print(f"YAML error in block 1: {e}")
        sys.exit(1)

    parsed = [doc for doc in parsed if doc is not None]
    if not parsed:
        print(f"ERROR: {path} is empty or contains no YAML documents")
        sys.exit(1)

    # Locate the spec block — must be a dict containing a 'spec' key.
    spec_doc = None
    for doc in parsed:
        if isinstance(doc, dict) and "spec" in doc:
            spec_doc = doc
            break

    if spec_doc is None:
        print(f"ERROR: no 'spec:' document found in {path}")
        sys.exit(1)

    spec = spec_doc.get("spec", {})
    if not isinstance(spec, dict):
        print(f"ERROR: spec must be a mapping, got {type(spec).__name__}")
        sys.exit(1)

    if "inputs" not in spec:
        print("ERROR: spec.inputs is required")
        sys.exit(1)

    inputs = spec["inputs"]
    if not isinstance(inputs, dict):
        print(f"ERROR: spec.inputs must be a mapping, got {type(inputs).__name__}")
        sys.exit(1)

    errors = []
    for name, defn in inputs.items():
        if not isinstance(defn, dict):
            errors.append(f'Input "{name}": definition must be a mapping, got {type(defn).__name__}')
            continue
        for field in ("type", "description"):
            if field not in defn:
                errors.append(f'Input "{name}" missing "{field}"')

    if errors:
        for e in errors:
            print(e)
        sys.exit(1)

    print(f"OK: {path} ({len(inputs)} inputs validated)")


if __name__ == "__main__":
    main()
