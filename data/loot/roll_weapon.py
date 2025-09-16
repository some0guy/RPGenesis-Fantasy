#!/usr/bin/env python3
"""
RPGenesis - Procedural Weapon Roller
------------------------------------
Reads loot data from data/loot/ and prints rolled weapon instances as JSON.
Usage:
  python scripts/roll_weapon.py --level 12 --seed "banditcamp" --table desert_bandit --num 5

Optional:
  --loot-dir data/loot          # override loot directory
  --pretty                      # pretty-print JSON

The script is deterministic: same arguments -> same output.
"""

from __future__ import annotations
import argparse, json, random, sys, os
from pathlib import Path
from typing import Dict, Any, List, Tuple

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def weighted_choice(pairs: Dict[str, int], rng: random.Random) -> str:
    items = list(pairs.items())
    total = sum(w for _, w in items)
    if total <= 0:
        raise ValueError("weighted_choice: total weight is 0 for pairs=" + str(pairs))
    r = rng.uniform(0, total)
    upto = 0
    for k, w in items:
        upto += w
        if r <= upto:
            return k
    return items[-1][0]

def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))

def get_in(d: Dict[str, Any], path: str, default=None):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

def set_in(d: Dict[str, Any], path: str, value: Any):
    cur = d
    parts = path.split(".")
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value

def add_in(d: Dict[str, Any], path: str, value: float):
    cur = get_in(d, path, 0)
    if cur is None:
        cur = 0
    set_in(d, path, (cur + value))

def read_loot_tables(loot_dir: Path):
    rarity = load_json(loot_dir / "rarity.json")
    names  = load_json(loot_dir / "names.json")
    weapon_bases = load_json(loot_dir / "weapon_bases.json")
    # Optional files
    affix_prefix = load_json(loot_dir / "affixes_prefix.json") if (loot_dir / "affixes_prefix.json").exists() else []
    affix_suffix = load_json(loot_dir / "affixes_suffix.json") if (loot_dir / "affixes_suffix.json").exists() else []
    drop_tables_dir = loot_dir / "drop_tables"
    return rarity, names, weapon_bases, affix_prefix, affix_suffix, drop_tables_dir

def choose_weapon_type(table: Dict[str, Any], rng: random.Random) -> str:
    return weighted_choice(table.get("weapons", {}), rng)

def choose_rarity(rarity_rules: Dict[str, Any], bias: Dict[str, int], rng: random.Random) -> str:
    # merge weights + bias
    weights = {k: int(v.get("weight", 0)) for k, v in rarity_rules.items()}
    for k, delta in (bias or {}).items():
        if k in weights:
            weights[k] = max(0, weights[k] + int(delta))
    return weighted_choice(weights, rng)

def pick_base_for_type(weapon_bases: List[Dict[str, Any]], wtype: str) -> Dict[str, Any]:
    for b in weapon_bases:
        if b.get("type") == wtype:
            return b
    raise KeyError(f"Weapon type '{wtype}' not found in weapon_bases.json")

def randint_envelope(env: Dict[str, Dict[str, int]], key: str, rng: random.Random) -> int:
    # env example: { "physical": { "min": 22, "max": 32 } }
    if key not in env:
        return 0
    lo = int(env[key].get("min", 0))
    hi = int(env[key].get("max", lo))
    if hi < lo:
        lo, hi = hi, lo
    return rng.randint(lo, hi)

def allowed_for_item(rule: Dict[str, Any], base: Dict[str, Any]) -> bool:
    """Checks rule.allow against base (category, types, tags)."""
    allow = rule.get("allow", {})
    if not allow:
        return True
    # category
    cats = allow.get("category")
    if cats and base.get("category") not in cats:
        return False
    # types exact
    types = allow.get("types")
    if types and base.get("type") not in types:
        return False
    # types_any (alias)
    types_any = allow.get("types_any")
    if types_any and base.get("type") not in types_any:
        return False
    # tags_any
    tags_any = allow.get("tags_any")
    if tags_any:
        bt = set(base.get("tags", []))
        if not any(t in bt for t in tags_any):
            return False
    return True

def apply_affix_mods(affix: Dict[str, Any], level: int, out: Dict[str, Any], rng: random.Random):
    for mod in affix.get("mods", []):
        path = mod["path"]
        # Value = flat roll + per-level
        flat_lo = mod.get("flat_min", 0)
        flat_hi = mod.get("flat_max", flat_lo)
        flat = rng.randint(int(flat_lo), int(flat_hi)) if (flat_hi > flat_lo) else int(flat_lo)
        per_level = float(mod.get("add_per_level", 0.0))
        add = flat + per_level * level
        add = round(add, 2)
        if "set" in mod:
            set_in(out, path, mod["set"])
        else:
            add_in(out, path, add)

def roll_affixes(n: int, pool: List[Dict[str, Any]], base: Dict[str, Any], rng: random.Random) -> List[Dict[str, Any]]:
    valid = [a for a in pool if allowed_for_item(a, base)]
    # simple weight pick without repeats (unless pool small)
    chosen = []
    for _ in range(max(0, n)):
        if not valid:
            break
        weights = [a.get("weight", 1) for a in valid]
        total = sum(weights)
        r = rng.uniform(0, total)
        upto = 0
        pick = None
        for a, w in zip(valid, weights):
            upto += w
            if r <= upto:
                pick = a
                break
        if pick is None:
            pick = valid[-1]
        chosen.append(pick)
        # remove pick to avoid dupes
        valid.remove(pick)
    return chosen

def build_name(base_type: str, rarity: str, names_rules: Dict[str, Any], prefixes: List[Dict[str, Any]], suffixes: List[Dict[str, Any]]) -> str:
    pattern = names_rules.get("weapon", {}).get("pattern", "{base}")
    fallbacks = names_rules.get("weapon", {}).get("fallbacks", ["{base}"])
    base_name = base_type.replace("_"," ").title()
    prefix_name = prefixes[0]["name"] if prefixes else ""
    suffix_name = suffixes[0]["name"] if suffixes else ""
    def fmt(p):
        return p.replace("{prefix}", prefix_name).replace("{base}", base_name).replace("{suffix}", suffix_name).strip()
    candidate = fmt(pattern)
    if "{prefix}" in pattern and not prefix_name:
        for fb in fallbacks:
            cand = fmt(fb)
            if cand:
                candidate = cand
                break
    if "{suffix}" in pattern and not suffix_name:
        for fb in fallbacks:
            cand = fmt(fb)
            if cand:
                candidate = cand
                break
    return candidate

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=10)
    ap.add_argument("--seed", type=str, default="rpgenesis")
    ap.add_argument("--table", type=str, default="desert_bandit")
    ap.add_argument("--num", type=int, default=5)
    ap.add_argument("--loot-dir", type=str, default="data/loot")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    loot_dir = Path(args.loot_dir)
    rarity, names, weapon_bases, affix_prefix, affix_suffix, drop_tables_dir = read_loot_tables(loot_dir)

    table_path = drop_tables_dir / f"{args.table}.json"
    if not table_path.exists():
        print(f"[error] drop table not found: {table_path}", file=sys.stderr)
        sys.exit(2)
    table = load_json(table_path)

    # PRNG: include level and table in seed for easy determinism across runs
    rng = random.Random(f"{args.seed}|{args.level}|{args.table}")

    instances = []
    for i in range(args.num):
        # pick type + rarity
        wtype = choose_weapon_type(table, rng)
        base = pick_base_for_type(weapon_bases, wtype)
        rarity_id = choose_rarity(rarity, table.get("rarity_bias", {}), rng)

        # base physical damage
        phys = randint_envelope(base.get("base_damage", {}), "physical", rng)
        dmg = {"physical": phys}

        # affix counts
        aff_lo, aff_hi = rarity[rarity_id].get("affixes", [0,0])
        n_affixes = rng.randint(int(aff_lo), int(aff_hi))

        # split roughly half prefix / half suffix
        n_pre = n_affixes // 2 + (n_affixes % 2)
        n_suf = n_affixes // 2

        prefixes = roll_affixes(n_pre, affix_prefix, base, rng)
        suffixes = roll_affixes(n_suf, affix_suffix, base, rng)

        # apply mods
        out = {"damage_type": dict(dmg), "bonus": {}, "weapon_trait": "none"}
        for a in prefixes + suffixes:
            apply_affix_mods(a, args.level, out, rng)

        # build instance
        instance = {
            "id": f"IT{rng.randint(10000000, 99999999)}",
            "category": "weapon",
            "type": wtype,
            "name": build_name(wtype, rarity_id, names, prefixes, suffixes),
            "rarity": rarity_id,
            "level": args.level,
            "seed": f"{args.seed}|{args.level}|{args.table}|{i}",
            "provenance": { "source_table": args.table },
            "base": { "damage_type": {"physical": phys} },
            "damage_type": out.get("damage_type", {"physical": phys}),
            "bonus": out.get("bonus", {}),
            "weapon_trait": out.get("weapon_trait", "none"),
            "affixes": [a["id"] for a in (prefixes + suffixes)]
        }
        instances.append(instance)

    dump = (json.dumps(instances, ensure_ascii=False, indent=2) if args.pretty
            else json.dumps(instances, ensure_ascii=False))
    print(dump)

if __name__ == "__main__":
    main()
