#!/usr/bin/env python3
from __future__ import annotations
import os, json, sys, argparse, re
from typing import Dict, Any, List, Tuple

EXPECTED = {
    "root_files": [
        "data/appearance.json",
        "data/enchants.json",
        "data/traits.json",
        "data/encounters.json",
        "data/loot_tables.json",
        "data/magic.json",
        "data/names.json",
        "data/status.json",
    ],
    "item_files": [
        "data/items/accessories.json",
        "data/items/armours.json",
        "data/items/weapons.json",
        "data/items/clothing.json",
        "data/items/materials.json",
        "data/items/quest_items.json",
        "data/items/trinkets.json",
    ],
    "npc_files": [
        "data/npcs/allies.json",
        "data/npcs/animals.json",
        "data/npcs/citizens.json",
        "data/npcs/enemies.json",
        "data/npcs/monsters.json",
    ],
    "dialogues_dir": "data/dialogues"
}

ID_RULES = {
    "item":    re.compile(r"^IT\d{8}$"),  # Items
    "npc":     re.compile(r"^NP\d{8}$"),  # NPCs

    # Unified Enchants
    "enchant": re.compile(r"^EN\d{8}$"),  # All enchants

    # Unified Traits
    "trait":   re.compile(r"^TR\d{8}$"),  # All traits

    # Other systems
    "magic":   re.compile(r"^MG\d{8}$"),  # Magic spells
    "status":  re.compile(r"^ST\d{8}$"),  # Status effects
}

def load_json(path, fallback=None):
    try:
        # utf-8-sig handles both plain UTF-8 and UTF-8 with BOM
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback if fallback is not None else {}
    except Exception as e:
        raise RuntimeError(f"Failed to load {path}: {e}")

def validate_id(id_str: str, kind: str) -> bool:
    rx = ID_RULES.get(kind)
    return bool(rx and id_str and rx.match(id_str))

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="Project root (RPGenesis Fantasy)")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    errs: List[str] = []
    warns: List[str] = []

    def check_exists(rel):
        p = os.path.join(root, rel)
        return os.path.exists(p)

    missing = [rel for rel in (EXPECTED["root_files"] + EXPECTED["item_files"] + EXPECTED["npc_files"]) if not check_exists(rel)]
    if missing:
        warns.append("[WARN] Missing files: " + ", ".join(missing))

    # Load helper
    def try_load(rel):
        p = os.path.join(root, rel)
        try: return load_json(p), None
        except Exception as e: return None, f"[ERR] Failed to load {rel}: {e}"

    # Root docs
    loaded = {}
    for rel in EXPECTED["root_files"]:
        doc, err = try_load(rel)
        if err: errs.append(err)
        loaded[rel] = doc

    # Validate schemas minimally
    for rel, doc in loaded.items():
        if isinstance(doc, dict):
            if "schema" not in doc or "version" not in doc:
                (errs if args.strict else warns).append(f"[WARN] {rel}: missing schema/version")

    # Items
    item_files = []
    item_index = {}
    dup_items = []
    for rel in EXPECTED["item_files"]:
        doc, err = try_load(rel)
        if err: warns.append(err); continue
        item_files.append(rel)
        if not isinstance(doc, dict): continue
        for it in doc.get("items", []):
            iid = it.get("id")
            if not validate_id(iid, "item"):
                errs.append(f"[ERR] {rel} item id '{iid}' must match IT########")
            if iid in item_index: dup_items.append(iid)
            item_index[iid] = it

    # NPCs
    npc_index = {}
    dup_npcs = []
    for rel in EXPECTED["npc_files"]:
        doc, err = try_load(rel)
        if err: warns.append(err); continue
        if not isinstance(doc, dict): continue
        for npc in doc.get("npcs", []):
            nid = npc.get("id")
            if not validate_id(nid, "npc"):
                errs.append(f"[ERR] {rel} npc id '{nid}' must match NP########")
            if nid in npc_index: dup_npcs.append(nid)
            npc_index[nid] = npc

    # Enchants, traits, magic, status patterns
    def check_ids_in(doc, rel, key, kind):
        for entry in doc.get(key, []):
            _id = entry.get("id")
            if not validate_id(_id, kind):
                errs.append(f"[ERR] {rel} id '{_id}' must match {kind.upper()}########")

    docs_to_check = [
        ("data/enchants.json", "enchants", "enchant"),
        ("data/traits.json",   "traits",   "trait"),
        ("data/magic.json",    "spells",   "magic"),
        ("data/status.json",   "status",   "status"),
    ]
    for rel, key, kind in docs_to_check:
        doc, err = try_load(rel)
        if err: errs.append(err); continue
        if isinstance(doc, dict):
            check_ids_in(doc, rel, key, kind)

    # Loot table references
    loot, err = try_load("data/loot_tables.json")
    if err: errs.append(err); loot = {"tables":{}, "aliases":{}}
    if isinstance(loot, dict):
        for tname, entries in (loot.get("tables") or {}).items():
            if not isinstance(entries, list):
                errs.append(f"[ERR] loot table '{tname}' should be a list"); continue
            for i, entry in enumerate(entries):
                pick = entry.get("pick")
                if isinstance(pick, str):
                    if pick not in item_index and pick not in (loot.get("aliases") or {}):
                        errs.append(f"[ERR] loot '{tname}' entry {i} references unknown id/alias '{pick}'")
                elif isinstance(pick, dict):
                    if "rarity" not in pick:
                        errs.append(f"[ERR] loot '{tname}' entry {i} dict pick missing 'rarity'")
                else:
                    errs.append(f"[ERR] loot '{tname}' entry {i} has invalid 'pick'")

    # Dialogues presence
    ddir = os.path.join(root, EXPECTED["dialogues_dir"])
    dlg_count = 0
    if os.path.isdir(ddir):
        for fn in os.listdir(ddir):
            if fn.lower().endswith(".json"): dlg_count += 1
    else:
        warns.append("[WARN] data/dialogues directory missing")

    # Report
    print("=== RPGenesis Data Report ===")
    print(f"Items: {len(item_index)} (dupes: {len(set(dup_items))})")
    print(f"NPCs:  {len(npc_index)} (dupes: {len(set(dup_npcs))})")
    print(f"Loot tables: {len((loot.get('tables') if isinstance(loot, dict) else {}) or {})}")
    print(f"Dialogues: {dlg_count}")
    for w in warns: print(w)
    for e in errs: print(e)

    sys.exit(1 if errs else 0)

if __name__ == "__main__":
    main()
