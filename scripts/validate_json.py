#!/usr/bin/env python3
"""
scripts/validate_json.py
Validates JSON parseability for all files under data/, checks optional keys,
and enforces ID format consistency mentioned in README.
"""

from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

ID_PATTERNS = {
    "IT": re.compile(r"^IT\d{8}$"),
    "NP": re.compile(r"^NP\d{8}$"),
    "EW": re.compile(r"^EW\d{8}$"),
    "EA": re.compile(r"^EA\d{8}$"),
    "EC": re.compile(r"^EC\d{8}$"),
    "MG": re.compile(r"^MG\d{8}$"),
    "TW": re.compile(r"^TW\d{8}$"),
    "TA": re.compile(r"^TA\d{8}$"),
    "TC": re.compile(r"^TC\d{8}$"),
    "ST": re.compile(r"^ST\d{8}$"),
}

def iter_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)
    elif isinstance(obj, str):
        yield obj

def check_id_formats(content: Any, path: Path) -> list[str]:
    errors: list[str] = []
    for s in iter_strings(content):
        # Only check strings that look like XX#########
        if len(s) == 10 and s[:2].isalpha() and s[2:].isdigit():
            prefix = s[:2]
            patt = ID_PATTERNS.get(prefix)
            if patt and not patt.match(s):
                errors.append(f"{path}: malformed ID '{s}'")
    return errors

def main() -> int:
    if not DATA_DIR.exists():
        print("No data/ directory found; skipping JSON validation.")
        return 0

    all_json = sorted(DATA_DIR.rglob("*.json"))
    if not all_json:
        print("No JSON files under data/; nothing to validate.")
        return 0

    failures = 0
    for jf in all_json:
        try:
            with jf.open("r", encoding="utf-8") as f:
                content = json.load(f)
        except Exception as e:
            print(f"[JSON ERROR] {jf}: {e}")
            failures += 1
            continue

        # Soft checks: schema/version keys if present at top-level dicts
        if isinstance(content, dict):
            if "schema" not in content or "version" not in content:
                # Not fatal—just nudge
                print(f"[WARN] {jf}: missing 'schema' and/or 'version' keys (not fatal).")

        # ID format checks
        id_errors = check_id_formats(content, jf)
        for e in id_errors:
            print(f"[ID ERROR] {e}")
        failures += len(id_errors)

    if failures:
        print(f"\nValidation finished with {failures} error(s).")
        return 1

    print("All JSON validated successfully ✅")
    return 0

if __name__ == "__main__":
    sys.exit(main())
