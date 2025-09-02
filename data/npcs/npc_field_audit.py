#!/usr/bin/env python3
"""
npc_field_audit.py — Scan NPC JSON files for missing or empty fields.

Works with your RPGenesis-style NPC files (e.g., allies.json, citizens.json, enemies.json, villains.json)
which typically look like:
{
  "schema": "...",
  "version": 1,
  "npcs": [ { ... }, ... ]
}

What it checks (by default):
- Required top-level fields: id, name, race, sex, type, description, appearance
- Required nested appearance fields:
  eye_color, hair_color, build, skin_tone, hair_length, hair_style, height, skin_texture, features

"Empty" means: null, "", [], {}, or all-whitespace.

You can customize required fields via CLI flags.

Usage examples:
  # Scan the standard four files in the current directory and print a report
  python npc_field_audit.py

  # Scan specific files
  python npc_field_audit.py --inputs allies.json citizens.json

  # Scan a directory with a glob
  python npc_field_audit.py --dir data --pattern "*npcs*.json"

  # Write CSV and Markdown reports
  python npc_field_audit.py --csv npc_audit.csv --md npc_audit.md

  # Customize required fields
  python npc_field_audit.py --require-top id,name,race,type,description --require-appearance eye_color,hair_color,height,build
"""
import argparse, json, os, glob, csv, sys

DEFAULT_TOP = ["id","name","race","sex","type","description","appearance"]
DEFAULT_APPEARANCE = ["eye_color","hair_color","build","skin_tone","hair_length","hair_style","height","skin_texture","features"]

def is_empty(val):
    if val is None:
        return True
    if isinstance(val, str):
        return len(val.strip()) == 0
    if isinstance(val, (list, dict)):
        return len(val) == 0
    return False

def load_payload(path):
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            return None, f"JSON error in {path}: {e}"
    # Accept either dict with 'npcs' or raw list of npcs
    if isinstance(data, dict) and "npcs" in data and isinstance(data["npcs"], list):
        return data, None
    if isinstance(data, list):
        return {"npcs": data}, None
    return None, f"Unrecognized structure in {path} (expected dict with 'npcs' or list)."

def audit_file(path, required_top, required_app):
    payload, err = load_payload(path)
    if err:
        return {"file": path, "error": err, "rows": []}
    rows = []
    for npc in payload["npcs"]:
        if not isinstance(npc, dict):
            continue
        rid = npc.get("id","")
        name = npc.get("name","")
        race = npc.get("race","")
        # Top-level checks
        missing_top = []
        empty_top = []
        for k in required_top:
            if k not in npc:
                missing_top.append(k)
            else:
                if is_empty(npc.get(k)):
                    empty_top.append(k)
        # Appearance checks (if "appearance" exists and is dict-like)
        missing_app = []
        empty_app = []
        app = npc.get("appearance", {})
        if isinstance(app, dict):
            for k in required_app:
                if k not in app:
                    missing_app.append(k)
                else:
                    if is_empty(app.get(k)):
                        empty_app.append(k)
        else:
            # If appearance itself is missing or not a dict, all app fields are missing.
            missing_app = list(required_app)

        if missing_top or empty_top or missing_app or empty_app:
            rows.append({
                "file": os.path.basename(path),
                "id": rid,
                "name": name,
                "race": race,
                "missing_top": ",".join(missing_top),
                "empty_top": ",".join(empty_top),
                "missing_appearance": ",".join(missing_app),
                "empty_appearance": ",".join(empty_app),
            })
    return {"file": path, "error": None, "rows": rows}

def write_csv(rows, out_path):
    fields = ["file","id","name","race","missing_top","empty_top","missing_appearance","empty_appearance"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def write_md(rows, out_path):
    # Group by file
    by_file = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# NPC Field Audit\n\n")
        if not rows:
            f.write("_No issues found._\n")
            return
        for fname, group in sorted(by_file.items()):
            f.write(f"## {fname}\n\n")
            for r in group:
                f.write(f"- **{r['name']}** ({r['id']}, {r['race']})\n")
                if r["missing_top"]:
                    f.write(f"  - Missing (top): `{r['missing_top']}`\n")
                if r["empty_top"]:
                    f.write(f"  - Empty (top): `{r['empty_top']}`\n")
                if r["missing_appearance"]:
                    f.write(f"  - Missing (appearance): `{r['missing_appearance']}`\n")
                if r["empty_appearance"]:
                    f.write(f"  - Empty (appearance): `{r['empty_appearance']}`\n")
                f.write("\n")

def main():
    ap = argparse.ArgumentParser(description="Scan NPC JSON files for missing/empty fields.")
    ap.add_argument("--inputs", nargs="*", help="Specific JSON files to scan (space-separated).")
    ap.add_argument("--dir", default=".", help="Directory to scan when using --pattern (default: current dir).")
    ap.add_argument("--pattern", default="", help="Glob pattern inside --dir (e.g., '*allies*.json').")
    ap.add_argument("--csv", help="Write CSV report to this path.")
    ap.add_argument("--md", help="Write Markdown report to this path.")
    ap.add_argument("--require-top", default=",".join(DEFAULT_TOP),
                    help="Comma-separated list of required top-level fields.")
    ap.add_argument("--require-appearance", default=",".join(DEFAULT_APPEARANCE),
                    help="Comma-separated list of required appearance fields.")
    args = ap.parse_args()

    required_top = [x.strip() for x in args.require_top.split(",") if x.strip()]
    required_app = [x.strip() for x in args.require_appearance.split(",") if x.strip()]

    paths = []
    if args.inputs:
        paths.extend(args.inputs)
    if args.pattern:
        base = args.dir or "."
        paths.extend(glob.glob(os.path.join(base, args.pattern)))
    if not paths:
        # default common files in CWD
        for f in ("allies.json","citizens.json","enemies.json","villains.json"):
            if os.path.exists(f):
                paths.append(f)
    if not paths:
        print("No input JSON files found. Use --inputs or --dir + --pattern.", file=sys.stderr)
        sys.exit(2)

    all_rows = []
    any_errors = False
    for p in sorted(set(paths)):
        result = audit_file(p, required_top, required_app)
        if result["error"]:
            print(result["error"], file=sys.stderr)
            any_errors = True
            continue
        all_rows.extend(result["rows"])

    # Print summary
    if not all_rows:
        print("✅ No missing/empty fields found in the scanned files.")
    else:
        # Count issues by file
        from collections import Counter
        c = Counter([r["file"] for r in all_rows])
        print("⚠️  Issues found in:")
        for fname, n in c.most_common():
            print(f" - {fname}: {n} NPC(s) with missing/empty fields")

        # Print first few rows
        print("\nExample rows:")
        for r in all_rows[:10]:
            print(f" - {r['file']} :: {r['name']} ({r['id']}): missing_top=[{r['missing_top']}], empty_top=[{r['empty_top']}], "
                  f"missing_appearance=[{r['missing_appearance']}], empty_appearance=[{r['empty_appearance']}]")

    if args.csv:
        write_csv(all_rows, args.csv)
        print(f"🧾 CSV written to: {args.csv}")
    if args.md:
        write_md(all_rows, args.md)
        print(f"📝 Markdown written to: {args.md}")

    sys.exit(1 if any_errors else 0)

if __name__ == "__main__":
    main()
