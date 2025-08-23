#!/usr/bin/env python3
"""
Normalize item JSONs to a canonical schema so the game doesn't need to guess.
- Works on data/items/*.json
- Keys normalized:
  name <- Name|display_name|title|label
  type <- Type|category|slot|item_type
  subtype <- SubType|weapon_type|class|category2
  desc <- description|flavor
  min <- min|min_damage|damage_min|atk_min
  max <- max|max_damage|damage_max|atk_max
  status_chance <- statusChance
  status <- statuses (accepts str or list)
- Lowercases type/subtype strings.
- Creates a .bak alongside each modified file.
- Use --dry-run to preview changes.
"""
import json, os, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS_DIR = ROOT / "data" / "items"

def coalesce(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def normalize_item(it: dict) -> dict:
    out = dict(it)  # start with original, then override normalized keys

    # names / types
    nm = coalesce(it, "name","Name","display_name","title","label")
    if nm: out["name"] = nm

    typ = coalesce(it, "type","Type","category","slot","item_type")
    sub = coalesce(it, "subtype","SubType","weapon_type","class","category2")
    if typ: out["type"] = str(typ).lower()
    if sub: out["subtype"] = str(sub).lower()

    # desc
    desc = coalesce(it, "desc","description","flavor")
    if desc is not None: out["desc"] = desc

    # damage
    mn = coalesce(it, "min","min_damage","damage_min","atk_min")
    mx = coalesce(it, "max","max_damage","damage_max","atk_max")
    if mn is not None:
        try: out["min"] = int(mn)
        except: pass
    if mx is not None:
        try: out["max"] = int(mx)
        except: pass

    # statuses
    stc = coalesce(it, "status_chance","statusChance")
    if stc is not None:
        try: out["status_chance"] = float(stc)
        except: pass
    sts = coalesce(it, "status","statuses")
    if sts is not None:
        if isinstance(sts, str): sts = [sts]
        if isinstance(sts, list): out["status"] = sts

    return out

def process_file(path: Path, dry: bool=False) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[SKIP] {path.name}: {e}")
        return 0

    if not isinstance(data, dict) or "items" not in data or not isinstance(data["items"], list):
        print(f"[SKIP] {path.name}: not an items collection")
        return 0

    changed = 0
    new_items = []
    for it in data["items"]:
        if not isinstance(it, dict):
            new_items.append(it); continue
        norm = normalize_item(it)
        if norm != it:
            changed += 1
        new_items.append(norm)

    if changed:
        print(f"[OK] {path.name}: normalized {changed} item(s)")
        if not dry:
            bak = path.with_suffix(path.suffix + ".bak")
            if not bak.exists():
                bak.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
            data["items"] = new_items
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        print(f"[OK] {path.name}: already normalized")
    return changed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="preview without writing changes")
    args = ap.parse_args()

    if not ITEMS_DIR.exists():
        print(f"[ERR] Items directory not found: {ITEMS_DIR}")
        return 1

    total = 0
    for fn in sorted(ITEMS_DIR.glob("*.json")):
        total += process_file(fn, dry=args.dry_run)
    print(f"\nDone. Normalized items: {total}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
