#!/usr/bin/env python3
from __future__ import annotations
import os, sys, json, re, argparse, random, math, hashlib
from typing import Dict, Any, List, Tuple, Optional, Set, TYPE_CHECKING
# Lightweight alias for pygame.Rect used only for type checking.
# Avoids Pylance "Variable not allowed in type expression" when pygame stubs are missing.
if TYPE_CHECKING:
    import pygame as _pg
    Rect = _pg.Rect
else:  # pragma: no cover - runtime fallback when pygame is unavailable
    Rect = Any  # type: ignore[assignment]
from datetime import datetime
from collections import deque, defaultdict
import copy
from dataclasses import dataclass, field

from pathlib import Path

# --- JSON map loader integration ---
from rpgen_map_loader import (
    load_world_map,
    load_scene_by_name,
    scene_to_runtime,
    find_entry_coords,
    get_game_start,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UI_DIR = DATA_DIR / "ui"
SAVE_DIR = DATA_DIR / "saves"
WORLD_MAP_PATH = DATA_DIR / "maps" / "world_map.json"
ASSETS_DIR = ROOT / "assets"

# -------------------- Project paths / version --------------------
VERSION_FILE = ROOT / "VERSION.txt"

def get_version() -> str:
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "0.0.0-dev"

# -------------------- Expected files + ID rules --------------------
EXPECTED = {
    "root_files": [
        "data/appearance.json",
        "data/mechanics/enchants.json",
        "data/mechanics/traits.json",
        "data/mechanics/encounters.json",
        "data/mechanics/loot_tables.json",
        "data/mechanics/magic.json",
        "data/status.json",
    ],
    "item_files": [
        "data/items/accessories.json",
        "data/items/armour.json",
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
        "data/npcs/calamities.json",
    ],
    "dialogues_dir": "data/dialogues",
}

ID_RULES = {
    "item":    re.compile(r"^IT\d{8}$"),
    "npc":     re.compile(r"^NP\d{8}$"),
    "enchant": re.compile(r"^EN\d{8}$"),
    "trait":   re.compile(r"^TR\d{8}$"),
    "magic":   re.compile(r"^MG\d{8}$"),
    "status":  re.compile(r"^ST\d{8}$"),
}

# -------------------- JSON I/O + validation --------------------
def load_json(path: str, fallback=None):
    """Load JSON with tolerant behavior.

    - Returns ``fallback`` (or ``{}``) when the file is missing.
    - If the file exists but is empty/whitespace or malformed and a ``fallback``
      is provided, returns ``fallback`` instead of raising.
    - Otherwise, raises a RuntimeError on failure to decode.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = f.read()
        if not (data.strip()):
            return fallback if fallback is not None else {}
        return json.loads(data)
    except FileNotFoundError:
        return fallback if fallback is not None else {}
    except json.JSONDecodeError as e:
        if fallback is not None:
            return fallback
        raise RuntimeError(f"Failed to load {path}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to load {path}: {e}")

def validate_id(id_str: str, kind: str) -> bool:
    rx = ID_RULES.get(kind)
    return bool(rx and id_str and isinstance(id_str, str) and rx.match(id_str))

def validate_project(root: str, strict: bool=False):
    errs: List[str] = []
    warns: List[str] = []

    def abspath(rel: str) -> str:
        return os.path.join(root, rel)

    missing = [rel for rel in (EXPECTED["root_files"] + EXPECTED["item_files"] + EXPECTED["npc_files"])
               if not os.path.exists(abspath(rel))]
    if missing:
        warns.append("[WARN] Missing files: " + ", ".join(missing))

    loaded_root: Dict[str, Optional[dict]] = {}
    for rel in EXPECTED["root_files"]:
        p = abspath(rel)
        try:
            doc = load_json(p, {})
            loaded_root[rel] = doc
        except Exception as e:
            errs.append(f"[ERR] Failed to load {rel}: {e}")
            loaded_root[rel] = None

    for rel, doc in loaded_root.items():
        if isinstance(doc, dict):
            if "schema" not in doc or "version" not in doc:
                (errs if strict else warns).append(f"[WARN] {rel}: missing schema/version")

    item_index: Dict[str, dict] = {}
    dup_items: List[str] = []
    for rel in EXPECTED["item_files"]:
        try:
            doc = load_json(abspath(rel), {"items": []})
        except Exception as e:
            warns.append(f"[WARN] {rel}: {e}"); doc = {"items": []}
        items_in = []
        try:
            if isinstance(doc, list):
                items_in = list(doc)
            elif isinstance(doc, dict):
                items_in = list(doc.get("items", []) or [])
        except Exception:
            items_in = []
        for it in items_in:
            if not isinstance(it, dict):
                continue
            iid = it.get("id")
            if not validate_id(iid, "item"):
                errs.append(f"[ERR] {rel} item id '{iid}' must match IT########")
            if iid in item_index:
                dup_items.append(iid)
            item_index[iid] = it

    npc_index: Dict[str, dict] = {}
    dup_npcs: List[str] = []
    for rel in EXPECTED["npc_files"]:
        try:
            doc = load_json(abspath(rel), {"npcs": []})
        except Exception as e:
            warns.append(f"[WARN] {rel}: {e}"); doc = {"npcs": []}
        npcs_in = []
        try:
            if isinstance(doc, list):
                npcs_in = list(doc)
            elif isinstance(doc, dict):
                npcs_in = list(doc.get("npcs", []) or [])
        except Exception:
            npcs_in = []
        for npc in npcs_in:
            if not isinstance(npc, dict):
                continue
            nid = npc.get("id")
            if not validate_id(nid, "npc"):
                errs.append(f"[ERR] {rel} npc id '{nid}' must match NP########")
            if nid in npc_index:
                dup_npcs.append(nid)
            npc_index[nid] = npc

    def check_ids_in(doc: dict, rel: str, key: str, kind: str):
        for entry in doc.get(key, []) or []:
            if not isinstance(entry, dict):
                continue
            _id = entry.get("id")
            if not validate_id(_id, kind):
                errs.append(f"[ERR] {rel} id '{_id}' must match {kind.upper()}########")

    for rel, key, kind in [
        ("data/mechanics/enchants.json", "enchants", "enchant"),
        ("data/mechanics/traits.json",   "traits",   "trait"),
        ("data/mechanics/magic.json",    "spells",   "magic"),
        ("data/status.json",              "status",   "status"),
    ]:
        try:
            doc = load_json(abspath(rel), {key: []})
            if isinstance(doc, dict):
                check_ids_in(doc, rel, key, kind)
        except Exception as e:
            errs.append(f"[ERR] Failed to load {rel}: {e}")

    try:
        loot = load_json(abspath("data/mechanics/loot_tables.json"), {"tables": {}, "aliases": {}})
    except Exception as e:
        errs.append(f"[ERR] Failed to load data/mechanics/loot_tables.json: {e}")
        loot = {"tables": {}, "aliases": {}}
    if isinstance(loot, dict):
        tables = loot.get("tables") or {}
        aliases = loot.get("aliases") or {}
        for tname, entries in tables.items():
            if not isinstance(entries, list):
                errs.append(f"[ERR] loot table '{tname}' should be a list")
                continue
            for i, entry in enumerate(entries):
                pick = entry.get("pick")
                if isinstance(pick, str):
                    if pick not in item_index and pick not in aliases:
                        errs.append(f"[ERR] loot '{tname}' entry {i} references unknown id/alias '{pick}'")
                elif isinstance(pick, dict):
                    if "rarity" not in pick:
                        errs.append(f"[ERR] loot '{tname}' entry {i} dict pick missing 'rarity'")
                else:
                    errs.append(f"[ERR] loot '{tname}' entry {i} has invalid 'pick'")

    dlg_dir = abspath(EXPECTED["dialogues_dir"])
    dlg_count = 0
    if os.path.isdir(dlg_dir):
        for fn in os.listdir(dlg_dir):
            if fn.lower().endswith(".json"):
                dlg_count += 1
    else:
        warns.append("[WARN] data/dialogues directory missing")

    print(f"=== RPGenesis Data Report (v{get_version()}) ===")
    print(f"Items: {len(item_index)} (dupes: {len(set(dup_items))})")
    print(f"NPCs:  {len(npc_index)} (dupes: {len(set(dup_npcs))})")
    print(f"Loot tables: {len((loot.get('tables') if isinstance(loot, dict) else {}) or {})}")
    print(f"Dialogues: {dlg_count}")
    for w in warns: print(w)
    for e in errs: print(e)

    return errs, warns

# ======================== Game data API ========================
def safe_load_doc(rel: str, array_key: str) -> List[dict]:
    """Load a top-level data document that may live in data/ or data/mechanics/.

    Resolution order:
    1) If `data/<rel>` exists and is non-empty, load and parse it.
    2) Else if `data/mechanics/<basename(rel)>` exists, load and parse it.
    3) Else return an empty list.

    Accepts either a top-level list or a dict containing an array at `array_key`.
    """
    try:
        # Prefer legacy path if it actually exists
        legacy_path = os.path.join(DATA_DIR, rel)
        if os.path.exists(legacy_path) and os.path.getsize(legacy_path) > 0:
            doc = load_json(legacy_path, {array_key: []})
            if isinstance(doc, list):
                return [x for x in doc if isinstance(x, dict)]
            if isinstance(doc, dict):
                return [x for x in doc.get(array_key, []) if isinstance(x, dict)]

        # Try mechanics path next
        base = os.path.basename(rel)
        mpath = os.path.join(DATA_DIR, "mechanics", base)
        if os.path.exists(mpath) and os.path.getsize(mpath) > 0:
            doc2 = load_json(mpath, {array_key: []})
            if isinstance(doc2, list):
                return [x for x in doc2 if isinstance(x, dict)]
            if isinstance(doc2, dict):
                return [x for x in doc2.get(array_key, []) if isinstance(x, dict)]
    except Exception:
        pass
    return []

def _coalesce(*vals, default=None):
    for v in vals:
        if v is None: 
            continue
        return v
    return default

# ---- Schema-tolerant item helpers ----
def item_name(it: dict) -> str:
    return (it.get('name') or it.get('Name') or it.get('display_name') or
            it.get('title') or it.get('label') or it.get('id') or '?')

def _is_placeholder_item(it: Optional[Dict[str, Any]]) -> bool:
    """Heuristically detect starter/placeholder items that shouldn't be named in UI.

    We treat items with names like 'Rough Dagger' or 'Plain Staff' as placeholders.
    """
    if not isinstance(it, dict):
        return False
    try:
        nm = str((it.get('name') or it.get('title') or '')).strip().lower()
        if nm in { 'rough dagger', 'plain staff' }:
            return True
    except Exception:
        pass
    return False

def _combat_item_label(it: Optional[Dict[str, Any]], fallback: str) -> str:
    """Return a user-facing label for an equipped item in combat.

    Hides placeholder starter gear by returning the fallback label instead.
    """
    if not it:
        return fallback
    if _is_placeholder_item(it):
        return fallback
    try:
        return item_name(it)
    except Exception:
        return fallback

def item_type(it: dict) -> str:
    """Return a major type for the item (weapon/armour/accessory/clothing/consumable/material/trinket/quest_item).

    Prefer broader category-like fields over specific subtype names.
    """
    majors = {
        'weapon','armour','armor','accessory','accessories','clothing',
        'consumable','consumables','material','materials','trinket','trinkets',
        'quest','quest_item','quest_items'
    }
    # Strong signals first
    for key in ('category','slot','item_type','Type'):
        v = it.get(key)
        if v and str(v).lower() in majors:
            return str(v)
    # Fall back to 'type' only if it looks like a major
    v = it.get('type')
    if v and str(v).lower() in majors:
        return str(v)
    # Otherwise, if nothing matches, still return something meaningful
    return str(it.get('category') or it.get('slot') or it.get('type') or '?')

def item_subtype(it: dict) -> str:
    """Return a specific subtype: e.g., dagger/head/ring.
    If not explicitly present, fall back to the narrow 'type' field when it does not collide with item_type.
    """
    v = (it.get('subtype') or it.get('SubType') or it.get('weapon_type') or
         it.get('class') or it.get('category2'))
    if v:
        return str(v)
    # Avoid duplicating the major type
    t_major = str(item_type(it)).lower()
    t_narrow = str(it.get('type') or '-')
    if t_narrow and t_narrow.lower() != t_major and t_narrow.lower() not in ('quest','quest_item','weapon','armour','armor','accessory','accessories','clothing','consumable','consumables','material','materials','trinket','trinkets'):
        return t_narrow
    return '-'

def item_desc(it: dict) -> str:
    return (it.get('desc') or it.get('description') or it.get('flavor') or '')

def item_value(it: dict) -> int:
    try:
        return int(it.get('value') or 0)
    except Exception:
        return 0

def item_weight(it: dict) -> int:
    try:
        return int(it.get('weight') or 0)
    except Exception:
        return 0

def item_major_type(it: dict) -> str:
    return str(item_type(it)).lower()

def item_is_consumable(it: dict) -> bool:
    t = item_major_type(it)
    return t in ('consumable','consumables','food','drink','potion','elixir')

def item_is_quest(it: dict) -> bool:
    t = item_major_type(it)
    return t in ('quest','quest_item','quest_items')

# ---- Equipment slot helpers ----
SLOT_LABELS = {
    'head': 'Head',
    'neck': 'Necklace',
    'torso': 'Torso',
    'legs': 'Legs',
    'feet': 'Feet',
    'hands': 'Hands',
    'ring': 'Ring',
    'bracelet': 'Bracelet',
    'charm': 'Charm',
    'back': 'Cape/Backpack',
    'weapon_main': 'Right Hand',
    'weapon_off': 'Left Hand',
}

def normalize_slot(name: str) -> str:
    n = (name or '').strip().lower()
    if n in ('head','helm','helmet','hat'): return 'head'
    if n in ('neck','amulet','necklace','torc'): return 'neck'
    if n in ('chest','torso','body','armor','armour','breastplate','chestplate'): return 'torso'
    if n in ('legs','pants','trousers'): return 'legs'
    if n in ('boots','shoes','feet','foot','greaves'): return 'feet'
    if n in ('hands','hand','gloves','gauntlets'): return 'hands'
    if n in ('wrist','bracelet','bracer','bracers'): return 'bracelet'
    if n in ('charm','token','fetish'): return 'charm'
    if n in ('ring','finger'): return 'ring'
    if n in ('back','cloak','cape','backpack'): return 'back'
    if n in ('weapon1','mainhand','main','weapon_main','weapon'): return 'weapon_main'
    if n in ('weapon2','offhand','off','weapon_off','shield'): return 'weapon_off'
    return n

def slot_accepts(slot: str, it: dict) -> bool:
    slot = normalize_slot(slot)
    m = item_major_type(it)
    sub = str(item_subtype(it)).lower()
    typ = str(item_type(it)).lower()
    slot_hint = str(it.get('slot') or '').lower()
    equip_hints = [str(s).lower() for s in (it.get('equip_slots') or [])]
    candidates = {v for v in ([sub, slot_hint] + equip_hints) if v}
    if slot in ('weapon_main','weapon_off'):
        return typ == 'weapon'
    if slot == 'head':
        return m in ('armour','armor','clothing') and bool(candidates & {'head','helm','helmet','hat'})
    if slot == 'torso':
        return m in ('armour','armor','clothing') and bool(candidates & {'torso','chest','body','armor','armour','breastplate','chestplate'})
    if slot == 'legs':
        return m in ('armour','armor','clothing') and bool(candidates & {'legs','pants','trousers'})
    if slot == 'feet':
        return m in ('armour','armor','clothing') and bool(candidates & {'feet','foot','boots','shoes','greaves'})
    if slot == 'hands':
        return m in ('armour','armor','clothing') and bool(candidates & {'hands','hand','gloves','gauntlets'})
    if slot == 'ring':
        return m in ('accessory','accessories','trinket','trinkets') and bool(candidates & {'ring'})
    if slot == 'bracelet':
        return m in ('accessory','accessories','trinket','trinkets') and bool(candidates & {'bracelet','bracer','bracers','wrist'})
    if slot == 'charm':
        return m in ('accessory','accessories','trinket','trinkets') and bool(candidates & {'charm','token','trinket'})
    if slot == 'neck':
        return m in ('accessory','accessories','trinket','trinkets') and bool(candidates & {'neck','amulet','necklace','torc'})
    if slot == 'back':
        return (m in ('armour','armor','clothing','accessory','accessories') and bool(candidates & {'back','cloak','cape','backpack'}))
    return False

# Migrate legacy equipped_gear slot keys to new canonical names
def migrate_gear_keys(gear: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        g = dict(gear or {})
    except Exception:
        g = {}
    mapping = {'chest': 'torso', 'boots': 'feet', 'gloves': 'hands'}
    for old, new in mapping.items():
        try:
            if old in g and new not in g:
                g[new] = g.pop(old)
        except Exception:
            pass
    return g

def _weapon_stats(it: Dict) -> Tuple[int,int,float,List[str]]:
    """Returns (min_bonus, max_bonus, status_chance, statuses) reading multiple possible keys safely."""
    min_b = int(_coalesce(it.get('min'), it.get('min_damage'), it.get('damage_min'), it.get('atk_min'), 0) or 0)
    max_b = int(_coalesce(it.get('max'), it.get('max_damage'), it.get('damage_max'), it.get('atk_max'), 0) or 0)
    st_ch = float(_coalesce(it.get('status_chance'), it.get('statusChance'), 0.0) or 0.0)
    statuses = it.get('status') or it.get('statuses') or []
    if isinstance(statuses, str): statuses = [statuses]
    st_ch = max(0.0, min(1.0, st_ch))
    return min_b, max_b, st_ch, list(statuses)

# Ensure a weapon dict has combat damage fields (min/max) based on its damage map
def _ensure_weapon_combat_stats_inplace(it: Optional[Dict]) -> None:
    if not isinstance(it, dict):
        return
    try:
        if str(item_major_type(it)).lower() != 'weapon':
            return
    except Exception:
        return
    # If already present and > 0, keep
    try:
        cur_min = int(it.get('min') or it.get('min_damage') or it.get('damage_min') or it.get('atk_min') or 0)
        cur_max = int(it.get('max') or it.get('max_damage') or it.get('damage_max') or it.get('atk_max') or 0)
    except Exception:
        cur_min = cur_max = 0
    if cur_min > 0 and cur_max > 0 and cur_max >= cur_min:
        return
    dmg_map = it.get('damage_type') or {}
    total = 0
    if isinstance(dmg_map, dict):
        for v in dmg_map.values():
            try:
                total += int(v)
            except Exception:
                pass
    # If no per-type damage provided, leave defaults (0) — attack will still use base atk
    if total <= 0:
        return
    # Derive a sensible combat range from total damage budget
    wmin = max(1, int(round(total * 0.55)))
    wmax = max(wmin + 1, int(round(total * 0.95)))
    it['min'] = int(wmin)
    it['max'] = int(wmax)

# ======================== Loot rolling (weapons) ========================

def _stable_int_hash(s: str) -> int:
    try:
        h = hashlib.sha256(s.encode('utf-8', errors='ignore')).hexdigest()
        return int(h[:16], 16)
    except Exception:
        return abs(hash(s)) & 0xFFFFFFFF

def _weighted_choice(weights: List[Tuple[str, int]], rng: random.Random) -> str:
    total = sum(max(0, int(w)) for _, w in weights) or 1
    r = rng.randrange(total)
    acc = 0
    for key, w in weights:
        acc += max(0, int(w))
        if r < acc:
            return key
    return weights[-1][0]

RARITY_WEIGHTS: List[Tuple[str,int]] = [
    ("common", 40), ("uncommon", 28), ("rare", 18), ("exotic", 9), ("legendary", 4), ("mythic", 1)
]

RARITY_DMG_MULT = {
    "common": 1.00, "uncommon": 1.05, "rare": 1.12, "exotic": 1.20, "legendary": 1.30, "mythic": 1.45
}

def _affix_budget_for_rarity(r: str, rng: random.Random) -> int:
    base = {"common": 0, "uncommon": 1, "rare": 2, "exotic": 3, "legendary": rng.choice([3,4]), "mythic": 4}.get(r, 0)
    return int(base)

class _Affix(Tuple[str, Dict[str, Any]]):
    pass

PREFIX_POOL: List[Dict[str, Any]] = [
    {"name":"Runed",      "adds": {"arcane": (2.0, 0.8)},    "bonus": {},        "traits": [],          "styles": ["physical","arcane","ranged"]},
    {"name":"Stormkissed","adds": {"lightning": (1.6,0.6)},  "bonus": {"attack": 1}, "traits": [],          "styles": ["physical","ranged"]},
    {"name":"Embered",    "adds": {"fire": (1.4,0.5)},       "bonus": {},        "traits": [],          "styles": ["physical","ranged","arcane"]},
    {"name":"Bloodbound", "adds": {"bleed": (1.2,0.6)},      "bonus": {},        "traits": ["lifedrink"], "styles": ["physical"]},
    {"name":"Moonlit",    "adds": {"ice": (1.4,0.6)},        "bonus": {},        "traits": [],          "styles": ["physical","arcane"]},
    {"name":"Kingsfall",  "adds": {"physical_pct": (0.08,0.02)}, "bonus": {"attack": 2}, "traits": ["knockback"], "min_rarity":"legendary", "styles": ["physical"]},
]

SUFFIX_POOL: List[Dict[str, Any]] = [
    {"name":"of the Vanguard", "adds": {},                "bonus": {"attack": 2}, "traits": ["stagger"],    "styles": ["physical","ranged","arcane"]},
    {"name":"of the Glacier",  "adds": {"ice": (1.2,0.5)},  "bonus": {},         "traits": ["chill"],      "styles": ["physical","arcane"]},
    {"name":"of Echoes",        "adds": {},                "bonus": {},         "traits": ["echo_strike"], "styles": ["physical","ranged","arcane"]},
    {"name":"of Embers",        "adds": {"fire": (1.2,0.5)}, "bonus": {},         "traits": ["burn"],       "styles": ["physical","ranged","arcane"]},
    {"name":"of Bursting",      "adds": {"stagger": (1.0,0.4)}, "bonus": {},      "traits": [],           "types": ["projectile","handcannon","bomb"]},
]

# Gear (armour/clothing/accessories) affixes
GEAR_PREFIX_POOL: List[Dict[str, Any]] = [
    {"name":"Stalwart",   "adds_def": {"physical": (2.0, 0.8)},     "bonus": {"defense": 1}},
    {"name":"Wardwoven",  "adds_def": {"arcane": (1.6, 0.6)},       "bonus": {"mana": 2}},
    {"name":"Emberward",  "adds_def": {"fire": (1.4, 0.5)},         "bonus": {}},
    {"name":"Frostbound", "adds_def": {"ice": (1.4, 0.6)},          "bonus": {}},
    {"name":"Stormguard", "adds_def": {"lightning": (1.4, 0.6)},    "bonus": {}},
    {"name":"Fleetstep",  "adds_def": {},                            "bonus": {"dexterity": 1}},
]

GEAR_SUFFIX_POOL: List[Dict[str, Any]] = [
    {"name":"of the Oak",     "adds_def": {"stagger": (1.0, 0.5)},   "bonus": {"defense": 1}},
    {"name":"of the Glacier", "adds_def": {"ice": (1.2, 0.5)},       "bonus": {}},
    {"name":"of Embers",      "adds_def": {"fire": (1.2, 0.5)},      "bonus": {}},
    {"name":"of Storms",      "adds_def": {"lightning": (1.2, 0.5)}, "bonus": {}},
    {"name":"of the Fox",     "adds_def": {},                        "bonus": {"dexterity": 1}},
]

def _style_for_weapon(base: Dict[str, Any]) -> str:
    st = str(base.get('style') or '').lower()
    if st: return st
    sub = str(base.get('type') or base.get('subtype') or '').lower()
    if sub in ('wand','staff','focus'): return 'arcane'
    if sub in ('bow','crossbow','projectile','gun','handcannon'): return 'ranged'
    return 'physical'

def _scale_damage_map(dmg: Dict[str, Any], scale: float) -> Dict[str, int]:
    out: Dict[str,int] = {}
    for k, v in (dmg or {}).items():
        try:
            out[k] = max(0, int(round(float(v) * float(scale))))
        except Exception:
            pass
    return out

def _apply_affixes(base_dmg: Dict[str,int], base_bonus: Dict[str,int], base_traits: List[str], lvl: int, affixes: List[Dict[str,Any]], rng: random.Random) -> Tuple[Dict[str,int], Dict[str,int], List[str]]:
    dmg = dict(base_dmg)
    bonus = dict(base_bonus)
    traits = list(base_traits)
    for af in affixes:
        adds = af.get('adds') or {}
        for k, spec in adds.items():
            if k == 'physical_pct':
                # Percent increase to physical bucket
                pct, slope = spec
                inc = (pct + slope * max(0, lvl))
                phys = int(dmg.get('physical', 0))
                phys = int(round(phys * (1.0 + inc)))
                dmg['physical'] = phys
            else:
                base, per_lvl = spec
                add = int(round(float(base) + float(per_lvl) * max(0, lvl)))
                dmg[k] = int(dmg.get(k, 0)) + max(0, add)
        for b, val in (af.get('bonus') or {}).items():
            bonus[b] = int(bonus.get(b, 0)) + int(val)
        for t in (af.get('traits') or []):
            if t not in traits:
                traits.append(t)
    return dmg, bonus, traits

def _build_name(base_type: str, prefixes: List[str], suffixes: List[str]) -> str:
    core = base_type.title() if base_type else 'Weapon'
    if prefixes and suffixes:
        return f"{prefixes[0]} {core} {suffixes[0]}"
    if prefixes:
        return f"{prefixes[0]} {core}"
    if suffixes:
        return f"{core} {suffixes[0]}"
    return core

def _jitter(val: int, pct: float, rng: random.Random) -> int:
    span = max(1, int(abs(val) * pct))
    return max(0, int(val + rng.randint(-span, span)))


_LOOT_CACHE: Optional[Dict[str, Any]] = None
_MECH_LOOT_CACHE: Optional[Dict[str, Any]] = None


def _load_loot_config() -> Dict[str, Any]:
    global _LOOT_CACHE
    if _LOOT_CACHE is not None:
        return _LOOT_CACHE
    cfg: Dict[str, Any] = {
        'enabled': False,
        'rarity': {},
        'weapon_bases': {},
        'affix_prefix': [],
        'affix_suffix': [],
        'names': {},
        'drop_tables': {},
    }
    try:
        loot_dir = DATA_DIR / "loot"
        if not loot_dir.exists():
            _LOOT_CACHE = cfg
            return cfg

        def _read_json(path: Path) -> Any:
            if path.exists():
                with path.open('r', encoding='utf-8') as fh:
                    return json.load(fh)
            return None

        rarity = _read_json(loot_dir / 'rarity.json') or {}
        names = _read_json(loot_dir / 'names.json') or {}
        weapon_bases_raw = _read_json(loot_dir / 'weapon_bases.json') or []
        affix_prefix = _read_json(loot_dir / 'affixes_prefix.json') or []
        affix_suffix = _read_json(loot_dir / 'affixes_suffix.json') or []

        base_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(weapon_bases_raw, list):
            for entry in weapon_bases_raw:
                try:
                    btype = str(entry.get('type') or '')
                    if btype:
                        base_map[btype] = entry
                except Exception:
                    continue

        drop_tables: Dict[str, Any] = {}
        tables_dir = loot_dir / 'drop_tables'
        if tables_dir.exists() and tables_dir.is_dir():
            for fp in tables_dir.glob('*.json'):
                try:
                    with fp.open('r', encoding='utf-8') as fh:
                        drop_tables[fp.stem] = json.load(fh)
                except Exception:
                    continue

        cfg.update({
            'enabled': bool(base_map or rarity),
            'rarity': rarity if isinstance(rarity, dict) else {},
            'weapon_bases': base_map,
            'affix_prefix': affix_prefix if isinstance(affix_prefix, list) else [],
            'affix_suffix': affix_suffix if isinstance(affix_suffix, list) else [],
            'names': names if isinstance(names, dict) else {},
            'drop_tables': drop_tables,
        })
    except Exception:
        cfg['enabled'] = False
    _LOOT_CACHE = cfg
    return cfg


def _loot_get_in(d: Dict[str, Any], path: str, default=None):
    cur: Any = d
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _loot_set_in(d: Dict[str, Any], path: str, value: Any) -> None:
    cur = d
    parts = path.split('.')
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _loot_add_in(d: Dict[str, Any], path: str, value: float) -> None:
    cur = _loot_get_in(d, path, 0)
    if cur is None:
        cur = 0
    try:
        cur_val = float(cur)
    except Exception:
        cur_val = 0.0
    _loot_set_in(d, path, cur_val + value)


def _loot_allowed_for_item(rule: Dict[str, Any], base: Dict[str, Any]) -> bool:
    allow = rule.get('allow', {}) or {}
    if not allow:
        return True
    base_cat = str(base.get('category') or 'weapon')
    if allow.get('category') and base_cat not in allow['category']:
        return False
    base_type = str(base.get('type') or '')
    if allow.get('types') and base_type not in allow['types']:
        return False
    if allow.get('types_any') and base_type not in allow['types_any']:
        return False
    tags_any = allow.get('tags_any')
    if tags_any:
        tags = set(base.get('tags', []) or [])
        if not any(t in tags for t in tags_any):
            return False
    return True


def _loot_roll_affixes(n: int, pool: List[Dict[str, Any]], base: Dict[str, Any], rng: random.Random) -> List[Dict[str, Any]]:
    valid = [a for a in (pool or []) if _loot_allowed_for_item(a, base)]
    chosen: List[Dict[str, Any]] = []
    for _ in range(max(0, n)):
        if not valid:
            break
        weights = [max(0, int(a.get('weight', 1))) or 1 for a in valid]
        total = sum(weights)
        r = rng.uniform(0, total)
        upto = 0.0
        pick = valid[-1]
        for a, w in zip(valid, weights):
            upto += w
            if r <= upto:
                pick = a
                break
        chosen.append(pick)
        valid.remove(pick)
    return chosen


def _loot_apply_affix_mods(affix: Dict[str, Any], level: int, out: Dict[str, Any], rng: random.Random) -> None:
    for mod in affix.get('mods', []) or []:
        path = mod.get('path')
        if not path:
            continue
        flat_lo = mod.get('flat_min', mod.get('set', 0))
        flat_hi = mod.get('flat_max', flat_lo)
        try:
            lo = float(flat_lo)
            hi = float(flat_hi)
        except Exception:
            lo = hi = 0.0
        if hi < lo:
            lo, hi = hi, lo
        if hi > lo:
            flat = rng.uniform(lo, hi)
        else:
            flat = lo
        per_level = float(mod.get('add_per_level', 0.0) or 0.0)
        add_val = flat + per_level * max(0, level)
        if 'set' in mod:
            _loot_set_in(out, path, mod['set'])
        else:
            _loot_add_in(out, path, add_val)


def _load_mechanics_loot() -> Dict[str, Any]:
    global _MECH_LOOT_CACHE
    if _MECH_LOOT_CACHE is not None:
        return _MECH_LOOT_CACHE
    data = {'tables': {}, 'aliases': {}}
    try:
        path = DATA_DIR / 'mechanics' / 'loot_tables.json'
        if path.exists():
            data = load_json(str(path), {'tables': {}, 'aliases': {}})
    except Exception:
        data = {'tables': {}, 'aliases': {}}
    if not isinstance(data, dict):
        data = {'tables': {}, 'aliases': {}}
    data.setdefault('tables', {})
    data.setdefault('aliases', {})
    _MECH_LOOT_CACHE = data
    return data

# --------- Template helpers -------------------------------------------------
def _sample_range(spec: Any, rng: random.Random) -> Optional[int]:
    try:
        if isinstance(spec, (list, tuple)) and spec:
            lo = int(spec[0])
            hi = int(spec[-1]) if len(spec) > 1 else lo
        elif isinstance(spec, dict):
            lo = int(spec.get('min', spec.get('low', spec.get('base', 0))))
            hi = int(spec.get('max', spec.get('high', spec.get('max', lo))))
        else:
            lo = hi = int(spec)
        if hi < lo:
            lo, hi = hi, lo
        return int(rng.randint(lo, hi))
    except Exception:
        return None

def _template_map(template: Dict[str, Any], rng: random.Random) -> Dict[str, int]:
    out: Dict[str,int] = {}
    for key, spec in (template or {}).items():
        val = _sample_range(spec, rng)
        if val is not None:
            out[str(key)] = int(val)
    return out

# --------- Enchant helpers (optional integration with mechanics/enchants.json) ---------
def _normalize_damage_key(k: str) -> str:
    kk = str(k or '').lower()
    return {
        'phys': 'physical',
        'physical': 'physical',
        'fire': 'fire',
        'ice': 'ice',
        'frost': 'ice',
        'shock': 'lightning',
        'lightning': 'lightning',
        'poison': 'poison',
        'bleed': 'bleed',
        'arcane': 'arcane',
    }.get(kk, kk)

def _apply_weapon_enchant_effects(dmg: Dict[str,int], bonus: Dict[str,int], statuses: List[str], effect: Dict[str,Any]):
    for k, v in (effect or {}).items():
        nk = _normalize_damage_key(k)
        try:
            iv = int(v)
        except Exception:
            iv = 0
        if nk in ('physical','fire','ice','lightning','poison','bleed','arcane'):
            dmg[nk] = int(dmg.get(nk, 0)) + max(0, iv)
        elif nk in ('attack','atk'):
            bonus['attack'] = int(bonus.get('attack', 0)) + max(0, iv)

def _apply_gear_enchant_effects(defense: Dict[str,int], bonus: Dict[str,int], effect: Dict[str,Any]):
    for k, v in (effect or {}).items():
        kk = str(k or '').lower()
        try:
            iv = int(v)
        except Exception:
            iv = 0
        if kk.startswith('resist_'):
            # Map resist_<type> to defense map
            typ = kk.replace('resist_', '')
            defense[_normalize_damage_key(typ)] = int(defense.get(_normalize_damage_key(typ), 0)) + max(0, iv)
        elif kk in ('defense_bonus','defense'):
            bonus['defense'] = int(bonus.get('defense', 0)) + max(0, iv)


def gather_items() -> List[Dict]:
    items: List[Dict] = []
    items_dir = os.path.join(DATA_DIR, "items")
    if os.path.isdir(items_dir):
        for name in ["weapons.json","armour.json","accessories.json","clothing.json","consumables.json","materials.json","quest_items.json","trinkets.json"]:
            for it in safe_load_doc(os.path.join("items", name), "items"):
                items.append(it)
    return items

def gather_armour_sets() -> List[Dict]:
    """Group armour pieces into sets by their set_name and aggregate metadata.

    Each returned set dict contains:
      - name: display name of the set
      - id: a stable identifier derived from the name
      - pieces: list of {id, name, slot}
      - piece_names: flattened list of piece names (for searching)
      - slots: list of normalized equip slots present in the set
      - slot_names: duplicate of slots (for searching)
      - set_bonus: merged mapping of thresholds -> effect dict
      - count: number of pieces
    """
    try:
        armour_items = [it for it in safe_load_doc(os.path.join("items", "armour.json"), "items") if isinstance(it, dict)]
    except Exception:
        armour_items = []

    def _slugify(s: str) -> str:
        s = str(s or '').strip().lower()
        out = []
        for ch in s:
            if ch.isalnum(): out.append(ch)
            elif ch in (' ', '-', '_'):
                out.append('-')
        # collapse dashes
        slug = ''.join(out)
        while '--' in slug:
            slug = slug.replace('--', '-')
        return slug.strip('-') or 'set'

    sets: Dict[str, Dict[str, Any]] = {}
    rarity_order = {
        'common': 0,
        'uncommon': 1,
        'rare': 2,
        'exotic': 3,
        'legendary': 4,
        'mythic': 5,
    }
    for it in armour_items:
        set_name = it.get('set_name') or it.get('set')
        if not set_name:
            continue
        sid = _slugify(set_name)
        cur = sets.get(set_name)
        if cur is None:
            cur = {
                'name': set_name,
                'id': f'SET:{sid}',
                'pieces': [],
                'piece_names': [],
                'slots': [],
                'slot_names': [],
                'set_bonus': {},
                'count': 0,
                'rarity': 'common',
                '_rarity_rank': -1,
            }
            sets[set_name] = cur
        # determine slot
        slot = None
        try:
            eq = it.get('equip_slots') or []
            if isinstance(eq, list) and eq:
                slot = normalize_slot(str(eq[0]))
        except Exception:
            slot = None
        if not slot:
            try:
                slot = normalize_slot(str(it.get('type') or item_subtype(it) or ''))
            except Exception:
                slot = '-'
        piece_entry = {
            'id': it.get('id'),
            'name': item_name(it),
            'slot': slot or '-',
        }
        cur['pieces'].append(piece_entry)
        try:
            nm = piece_entry.get('name')
            if isinstance(nm, str):
                cur['piece_names'].append(nm)
        except Exception:
            pass
        if slot and slot not in cur['slots']:
            cur['slots'].append(slot)
            cur['slot_names'].append(slot)
        # merge set_bonus thresholds (union of keys)
        try:
            sb = it.get('set_bonus') or {}
            if isinstance(sb, dict):
                for thresh, eff in sb.items():
                    if thresh not in cur['set_bonus']:
                        cur['set_bonus'][thresh] = dict(eff) if isinstance(eff, dict) else eff
                    else:
                        # union missing effect keys (do not sum to avoid duplicating)
                        ex = cur['set_bonus'][thresh]
                        if isinstance(ex, dict) and isinstance(eff, dict):
                            for k, v in eff.items():
                                if k not in ex:
                                    ex[k] = v
        except Exception:
            pass
        cur['count'] = len(cur['pieces'])
        # track representative rarity as the highest among pieces
        try:
            r = str((it.get('rarity') or '')).lower()
            rr = rarity_order.get(r, -1)
            if rr > int(cur.get('_rarity_rank', -1)):
                cur['_rarity_rank'] = rr
                if r:
                    cur['rarity'] = r
        except Exception:
            pass

    # stable ordering by name; UI will re-sort
    # drop private temp rank field
    out = []
    for s in sets.values():
        if '_rarity_rank' in s:
            try:
                del s['_rarity_rank']
            except Exception:
                pass
        out.append(s)
    return out

def gather_npcs() -> List[Dict]:
    npcs: List[Dict] = []
    npcs_dir = os.path.join(DATA_DIR, "npcs")
    if os.path.isdir(npcs_dir):
        for name in ["allies.json","animals.json","citizens.json","enemies.json","calamities.json","villains.json"]:
            for n in safe_load_doc(os.path.join("npcs", name), "npcs"):
                npcs.append(n)
        # Also support directory-based categories like data/npcs/vilains/*.json or data/npcs/villains/*.json
        for subdir in ["vilains", "villains"]:
            p = os.path.join(npcs_dir, subdir)
            if os.path.isdir(p):
                try:
                    for fn in os.listdir(p):
                        if fn.lower().endswith(".json"):
                            rel = os.path.join("npcs", subdir, fn)
                            for n in safe_load_doc(rel, "npcs"):
                                npcs.append(n)
                except Exception:
                    pass
    if not npcs:
        npcs = [
            {"id":"NP00000001","name":"Lissar of the Birch","race":"wood_elf","romanceable":True, "hp": 14, "dex":5, "will":5, "greed":3,
             "desc":"An elf archer with bright eyes and a sly smile."},
            {"id":"NP00000002","name":"Grukk","race":"orc","hostile":True, "hp": 16, "dex":4, "will":3, "greed":5,
             "desc":"A hulking brute whose breath smells like old stew."}
        ]
    return npcs

def load_traits() -> List[Dict]:   return safe_load_doc("traits.json", "traits")
def load_enchants() -> List[Dict]: return safe_load_doc("enchants.json", "enchants")
def load_magic() -> List[Dict]:    return safe_load_doc("magic.json", "spells")
def load_status() -> List[Dict]:   return safe_load_doc("status.json", "status")

def load_curses() -> List[Dict]:
    """Load curses from mechanics/curses.json with tolerant schema.

    Supports either a top-level list or a dict containing a list under
    common keys like 'curses', 'entries', or 'list'.
    """
    path = DATA_DIR / "mechanics" / "curses.json"
    try:
        doc = load_json(str(path), [])
        if isinstance(doc, list):
            return [x for x in doc if isinstance(x, dict)]
        if isinstance(doc, dict):
            for key in ("curses", "entries", "list", "data"):
                v = doc.get(key)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
        return []
    except Exception:
        return []

# Tolerant loaders for top-level array documents (e.g., races, classes)
def load_races_list() -> List[Dict]:
    """Load Races with tolerant schema and flexible locations.

    Priority:
    1) data/npcs/races.json (current)
    2) data/races.json (legacy)
    3) data/npcs/races_index.json (minimal entries; fallback)

    Supports either a top-level list, or a dict with a 'races' list.
    """
    candidates = [
        DATA_DIR / "npcs" / "races.json",
        DATA_DIR / "races.json",
        DATA_DIR / "npcs" / "races_index.json",
    ]
    for path in candidates:
        try:
            if not path.exists() or path.stat().st_size == 0:
                continue
            doc = load_json(str(path), [])
            if isinstance(doc, list):
                return [x for x in doc if isinstance(x, dict)]
            if isinstance(doc, dict) and isinstance(doc.get("races"), list):
                return [x for x in doc.get("races") if isinstance(x, dict)]
        except Exception:
            continue
    return []

def load_classes_list() -> List[Dict]:
    """Load Classes from the project data with tolerant schema.

    Priority:
    1) data/mechanics/classes.json
    2) data/mechanics/class.json
    3) data/classes.json

    Supports top-level list, or dict with a 'classes' list.
    """
    candidates = [
        DATA_DIR / "mechanics" / "classes.json",
        DATA_DIR / "mechanics" / "class.json",
        DATA_DIR / "classes.json",
    ]
    for path in candidates:
        try:
            if not path.exists() or path.stat().st_size == 0:
                continue
            doc = load_json(str(path), [])
            if isinstance(doc, list):
                return [x for x in doc if isinstance(x, dict)]
            if isinstance(doc, dict) and isinstance(doc.get("classes"), list):
                return [x for x in doc.get("classes") if isinstance(x, dict)]
        except Exception:
            continue
    return []

# ---------- Class mechanics helpers ----------
def _class_by_name(classes: List[Dict], name: str) -> Optional[Dict[str, Any]]:
    nm = str(name or '').strip().lower()
    for c in (classes or []):
        try:
            if str(c.get('name') or '').strip().lower() == nm:
                return c
        except Exception:
            continue
    return None

# ======================== Core structures ========================
@dataclass
class Encounter:
    # Primary single targets (kept for compatibility with existing flows)
    npc: Optional[Dict] = None
    enemy: Optional[Dict] = None
    # Full lists as placed by the map editor
    npcs: List[Dict] = field(default_factory=list)
    items: List[Dict] = field(default_factory=list)
    # Other encounter aspects
    event: Optional[str] = None
    must_resolve: bool = False
    spotted: bool = False
    # Movement constraint: where you came from when entering a blocking tile
    allowed_back: Optional[Tuple[int,int]] = None
    # Deprecated single-item fields retained for backward compatibility
    item_here: Optional[Dict] = None
    item_searched: bool = False

@dataclass
class Tile:
    x: int
    y: int
    discovered: bool = False
    encounter: Optional[Encounter] = None
    visited: int = 0
    description: str = ""
    # Per-tile safety marker from the map editor: '', 'safe', or 'danger'
    safety: str = ""
    walkable: bool = False   # NEW: path support
    has_link: bool = False
    link_to_map: Optional[str] = None
    link_to_entry: Optional[str] = None

@dataclass
class Player:
    x: int = 0
    y: int = 0
    name: str = "Adventurer"
    race: str = "Human"
    role: str = "Wanderer"
    level: int = 1
    hp: int = 20
    max_hp: int = 20
    atk: Tuple[int,int] = (3,6)
    # Core attributes (custom system)
    phy: int = 5   # Physique (PHY)
    dex: int = 5   # Technique (DEX)
    vit: int = 5   # Vitality (VIT)
    arc: int = 5   # Arcane (ARC)
    kno: int = 5   # Knowledge (KNO)
    ins: int = 5   # Insight (INS)
    soc: int = 5   # Social (SOC)
    fth: int = 5   # Faith (FTH)
    affinity: Dict[str,int] = field(default_factory=dict)
    romance_flags: Dict[str,bool] = field(default_factory=dict)
    inventory: List[Dict] = field(default_factory=list)
    equipped_weapon: Optional[Dict] = None
    # Generic equipment slots for armour/clothing/accessory
    equipped_gear: Dict[str, Dict] = field(default_factory=dict)
    # Optional portrait reference (relative to project or assets/)
    portrait: Optional[str] = "images/player/player.png"

# Party member (ally) uses the same stat shape as Player for simplicity
@dataclass
class Ally:
    id: str
    name: str
    race: str = "Human"
    role: str = "Ally"
    level: int = 1
    xp: int = 0
    hp: int = 14
    max_hp: int = 14
    atk: Tuple[int,int] = (2,4)
    phy: int = 5
    dex: int = 5
    vit: int = 5
    arc: int = 5
    kno: int = 5
    ins: int = 5
    soc: int = 5
    fth: int = 5
    inventory: List[Dict] = field(default_factory=list)
    equipped_weapon: Optional[Dict] = None
    equipped_gear: Dict[str, Dict] = field(default_factory=dict)
    portrait: Optional[str] = None
    home_map: Optional[str] = None
    home_pos: Optional[Tuple[int, int]] = None
    home_payload: Optional[Dict[str, Any]] = None

def pick_enemy(npcs: List[Dict]) -> Optional[Dict]:
    hostile = [n for n in npcs if n.get("hostile")]
    return random.choice(hostile) if hostile else None

def pick_npc(npcs: List[Dict]) -> Optional[Dict]:
    friendly = [n for n in npcs if not n.get("hostile")]
    return random.choice(friendly) if friendly else None

def pick_item(items: List[Dict]) -> Optional[Dict]:
    return random.choice(items) if random.random() < 0.35 else None

def generate_path(width: int, height: int) -> List[Tuple[int, int]]:
    """Generate a connected path through the world"""
    path = [(0, 0)]  # Start at origin
    current = (0, 0)
    
    while len(path) < width * height // 3:  # Cover ~1/3 of tiles
        x, y = current
        # Add random connected tiles
        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        random.shuffle(directions)
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in path:
                path.append((nx, ny))
                current = (nx, ny)
                break
        else:
            # If stuck, jump to a random connected tile
            current = random.choice(path)
    
    return path

def grid_from_runtime(runtime: Dict[str, Any], items: List[Dict], npcs: List[Dict]) -> List[List[Tile]]:
    """Build a Tile grid from the scene_to_runtime() structure (editor or legacy).

    - walkable: from runtime['walkable']
    - encounters: map editor payloads to Encounter lists (npcs/items)
    """
    W = int(runtime.get('width', 12)); H = int(runtime.get('height', 8))
    grid: List[List[Tile]] = [[Tile(x=x, y=y) for x in range(W)] for y in range(H)]
    walk = runtime.get('walkable') or [[True]*W for _ in range(H)]
    payload = runtime.get('tiles') or {}

    for y in range(H):
        for x in range(W):
            t = grid[y][x]
            t.walkable = bool(walk[y][x]) if y < len(walk) and x < len(walk[y]) else True
            cell = payload.get((x, y))
            if cell:
                # Copy per-tile safety marker if present
                try:
                    t.safety = str(cell.get('encounter') or '').lower()
                except Exception:
                    t.safety = ''
                enc = Encounter()
                # Populate lists if provided by runtime
                enc.npcs = list(cell.get('npcs') or [])
                enc.items = list(cell.get('items') or [])
                # Backwards compatible single fields
                if cell.get('npc') and not enc.npcs:
                    enc.npcs = [cell.get('npc')]
                if cell.get('item') and not enc.items:
                    enc.items = [cell.get('item')]
                # Derive primary targets
                def _is_enemy(e: Dict) -> bool:
                    sub = (e.get('subcategory') or '').lower()
                    return sub in ('enemies','monsters','villains','vilains') or bool(e.get('hostile'))
                for e in enc.npcs:
                    if _is_enemy(e):
                        enc.enemy = e
                        break
                for e in enc.npcs:
                    if not _is_enemy(e):
                        enc.npc = e
                        break
                t.encounter = enc if (enc.npcs or enc.items or enc.event) else None

    # Mark link tiles for UI from runtime['links']
    for link in (runtime.get('links') or []):
        try:
            (lx, ly), _to, _kind, _entry = link
        except Exception:
            continue
        if 0 <= ly < H and 0 <= lx < W:
            t = grid[ly][lx]
            t.has_link = True
            t.link_to_map = _to or None
            t.link_to_entry = _entry or None
    return grid

# Find a nearest walkable coordinate given a desired spawn
def find_nearest_walkable(runtime: Dict[str, Any], sx: int, sy: int) -> Tuple[int, int]:
    W = int(runtime.get('width', 12)); H = int(runtime.get('height', 8))
    walk = runtime.get('walkable') or [[True]*W for _ in range(H)]

    def is_walk(x: int, y: int) -> bool:
        if not (0 <= x < W and 0 <= y < H):
            return False
        try:
            return bool(walk[y][x])
        except Exception:
            # If walk matrix is ragged, treat missing as non-walkable
            return False

    try:
        x0 = max(0, min(W-1, int(sx)))
        y0 = max(0, min(H-1, int(sy)))
    except Exception:
        x0, y0 = 0, 0

    if is_walk(x0, y0):
        return x0, y0

    from collections import deque as _dq
    q = _dq()
    q.append((x0, y0))
    seen = set([(x0, y0)])
    dirs = [(-1,0),(1,0),(0,-1),(0,1)]
    while q:
        x, y = q.popleft()
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen:
                continue
            if 0 <= nx < W and 0 <= ny < H:
                if is_walk(nx, ny):
                    return nx, ny
                seen.add((nx, ny))
                q.append((nx, ny))

    # Fallback: first walkable tile anywhere
    for yy in range(H):
        for xx in range(W):
            if is_walk(xx, yy):
                return xx, yy
    return 0, 0

# ======================== UI helpers (MODULE-LEVEL) ========================
try:
    import pygame as pg
except Exception:
    pg = None  # checked at runtime

# Provide type-only access to pygame for annotations without requiring runtime import
if TYPE_CHECKING:  # used by Pylance/mypy; ignored at runtime
    import pygame  # noqa: F401

# Optional AA polygon helper for smoother dots
try:
    from pygame import gfxdraw as gfx
except Exception:
    gfx = None
# Color palette for recent log entries (matches map dots)
LOG_COLORS = {
    'enemy':   (220,70,70),
    'monster': (170,110,240),
    'ally':    (80,200,120),
    'citizen': (80,150,240),
    'animal':  (245,210,80),
    'quest_item': (255,160,70),
    'item':    (240,240,240),
    'event':   (160,130,200),
    'link':    (255,105,180),
}

# Stat colors
STAT_COLORS = {
    'phy': (220,70,70),     # Physique: red
    'dex': (80,200,120),    # Technique: green
    'arc': (170,110,240),   # Arcane: purple
    'vit': (80,150,240),    # Vitality: blue
    'kno': (160,210,255),   # Knowledge: lighter blue
    'ins': (255,160,70),    # Insight: orange
    'soc': (255,105,180),   # Social: pink
    'fth': (245,210,80),    # Faith: yellow
}

# Rarity colors for item display (inventory/equipment)
RARITY_COLORS = {
    'common':    (200, 200, 210),   # light grey
    'uncommon':  (80, 200, 120),    # green
    'rare':      (80, 150, 240),    # blue
    'exotic':    (170, 110, 240),   # purple
    'legendary': (255, 160, 70),    # orange
    'mythic':    (245, 210, 80),    # gold
}

# Tags that should not appear in the Recent log unless explicitly logged
# without a tag (e.g., after talking to them). This hides low-signal noise
# from friendly presence markers.
LOG_HIDE_TAGS = {"ally", "citizen", "animal"}

def draw_text(surface, text, pos, color=(230,230,230), font=None, max_w=None):
    """Render text with optional word wrapping.

    Returns the pixel height consumed by the rendered text (number of lines * line_height).
    Callers may ignore the return value when fixed spacing is desired.
    """
    # If string is prefixed with a bullet (bell or dot), preserve it while parsing [tag]
    if isinstance(text, str):
        try:
            prefix = ''
            if text.startswith("\u0007 "):
                prefix, body = text[:2], text[2:]
            elif text.startswith("* "):
                prefix, body = text[:2], text[2:]
            else:
                body = text
            if body.startswith('['):
                close = body.find(']')
                if close != -1:
                    tag = body[1:close].strip().lower()
                    if color == (230,230,230):
                        color = LOG_COLORS.get(tag, color)
                    body = body[close+1:].lstrip()
            text = prefix + body
        except Exception:
            pass
    if font is None:
        if pg is None:
            raise RuntimeError("pygame not available")
        font = pg.font.Font(None, 18)
    line_h = font.get_linesize()
    if not max_w:
        surface.blit(font.render(text, True, color), pos)
        return line_h
    words = text.split(" ")
    x, y = pos
    line = ""
    lines = 0
    for w in words:
        test = (line + " " + w).strip()
        if font.size(test)[0] <= max_w:
            line = test
        else:
            surface.blit(font.render(line, True, color), (x, y))
            y += line_h
            lines += 1
            line = w
    if line:
        surface.blit(font.render(line, True, color), (x, y))
        lines += 1
    return max(0, lines * line_h)

# --- Portrait helpers for combat overlay ---
def _slugify_name(name: str) -> str:
    try:
        s = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower())
        return s.strip("_") or "portrait"
    except Exception:
        return "portrait"

def _first_existing_path(cands) -> Optional[Path]:
    for c in cands:
        try:
            p = Path(c)
            if not p.is_absolute():
                p1 = ROOT / p
                if p1.exists():
                    return p1
                p2 = ASSETS_DIR / p
                if p2.exists():
                    return p2
            if p.exists():
                return p
        except Exception:
            pass
    return None

def _load_portrait_cached(game, key: str, size: Tuple[int,int]):
    if pg is None:
        return None
    if not hasattr(game, "_portrait_cache"):
        game._portrait_cache = {}
    cache_key = (key, int(size[0]), int(size[1]))
    surf = game._portrait_cache.get(cache_key)
    if surf is not None:
        return surf
    path = _first_existing_path([key])
    if not path:
        return None
    try:
        img = pg.image.load(str(path)).convert_alpha()
        w, h = int(size[0]), int(size[1])
        if w <= 0 or h <= 0:
            return None
        iw, ih = img.get_width(), img.get_height()
        if iw <= 0 or ih <= 0:
            return None
        scale = min(w / float(iw), h / float(ih))
        tw, th = max(1, int(iw * scale)), max(1, int(ih * scale))
        img2 = pg.transform.smoothscale(img, (tw, th)) if hasattr(pg.transform, 'smoothscale') else pg.transform.scale(img, (tw, th))
        out = pg.Surface((w, h), pg.SRCALPHA)
        out.fill((0,0,0,0))
        out.blit(img2, ((w - tw)//2, (h - th)//2))
        game._portrait_cache[cache_key] = out
        return out
    except Exception:
        return None

def _enemy_portrait_candidates(enemy: Dict) -> List[str]:
    cands: List[str] = []
    if not isinstance(enemy, dict):
        return cands
    for k in ("portrait","image","img","sprite"):
        v = enemy.get(k)
        if isinstance(v, str) and v.strip():
            cands.append(v.strip())
    slug = _slugify_name(enemy.get("name") or enemy.get("id") or "enemy")
    for sub in ("portraits/enemies", "portraits/npcs", "portraits"):
        cands.append(f"{sub}/{slug}.png")
        cands.append(f"{sub}/{slug}.jpg")
    if isinstance(enemy.get("id"), str):
        eid = enemy["id"]
        for sub in ("portraits/enemies", "portraits/npcs", "portraits"):
            cands.append(f"{sub}/{eid}.png")
            cands.append(f"{sub}/{eid}.jpg")
    return cands

def _player_portrait_candidates(player) -> List[str]:
    cands: List[str] = []
    try:
        v = getattr(player, "portrait", None)
        if isinstance(v, str) and v.strip():
            cands.append(v.strip())
    except Exception:
        pass
    # Default player image location
    cands.append("images/player/player.png")
    slug = _slugify_name(getattr(player, 'name', 'player'))
    role = _slugify_name(getattr(player, 'role', ''))
    race = _slugify_name(getattr(player, 'race', ''))
    for sub in ("portraits/allies", "portraits/party", "portraits"):
        for nm in ("player", slug, role, race):
            if nm:
                cands.append(f"{sub}/{nm}.png")
                cands.append(f"{sub}/{nm}.jpg")
    return cands

class Button:
    def __init__(self, rect, label, cb, draw_bg: bool=True):
        if pg is None:
            raise RuntimeError("pygame not available")
        self.rect = pg.Rect(rect)
        self.label = label
        self.cb = cb
        # When False, we don't draw a filled bg, but still show a hover outline
        self.draw_bg = draw_bg

    def draw(self, surf):
        # Hover detection (no state is stored; computed each frame)
        try:
            mx, my = pg.mouse.get_pos()
            hov = self.rect.collidepoint(mx, my)
        except Exception:
            hov = False

        # Colors
        base_col   = (60,60,70)
        hover_col  = (73,80,99)
        border_col = (110,110,130)
        accent_col = (122,162,247)

        if self.draw_bg:
            pg.draw.rect(surf, hover_col if hov else base_col, self.rect, border_radius=8)
            pg.draw.rect(surf, accent_col if hov else border_col, self.rect, 2, border_radius=8)
            if self.label:
                label_font = pg.font.Font(None, 18)
                label = label_font.render(self.label, True, (240,240,255))
                surf.blit(label, (self.rect.x + 10, self.rect.y + (self.rect.h - label.get_height())//2))
        else:
            # Invisible hit area: on hover, show subtle outline to indicate interactivity
            if hov:
                pg.draw.rect(surf, accent_col, self.rect, 2, border_radius=8)

    def handle(self, event):
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            self.cb()

PANEL_W_FIXED = 380  # Fixed width for left/right sidebars

# Angle of diamond side relative to horizontal (deg). 26.565 ~ classic 2:1.
ISO_ANGLE_DEG = 35
ISO_ROT_DEG = -25.0

# Map zoom multiplier (1.0 = default size). Increase to zoom in, decrease to zoom out.
MAP_ZOOM = 10.0

# Dot layout tuning
# Extra inset from tile edges in tile-space units (fraction of half-extent)
DOT_EDGE_INSET = 0.12  # 0.0..0.25 typical; higher = further from edges
# Scale for row/column spacing (lower compacts dots toward center)
DOT_SPACING_SCALE = 0.88
# Visual size scale for dots (1.0 original, <1 smaller)
DOT_SIZE_SCALE = 0.88

# Shared UI palette
COL_PLAYER = (122, 162, 247)  # accent color for player highlighting

def draw_grid(surf, game):
    # Dynamic view area and camera
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)
    # Background for map area
    pg.draw.rect(surf, (26,26,32), view_rect)
    # Fog-of-war overlay: start as a full overlay, then carve holes for revealed tiles
    outside_fog = pg.Surface((view_w, view_h), pg.SRCALPHA)
    outside_fog.fill((8, 10, 14, 190))

    W = getattr(game, 'W', 12); H = getattr(game, 'H', 8)
    # Slightly zoomed view target (used to choose pixel size)
    vis_w_tiles = min(10, max(1, W))
    vis_h_tiles = min(6, max(1, H))
    margin = 16

    # Choose isometric diamond width that fits the view
    # Bounding width of an WxH iso grid is approximately (W+H)*half_w
    # and height is (W+H)*half_h. We keep a gentle zoom using vis_*.
    target_w = max(1, vis_w_tiles + vis_h_tiles)
    tile_w = max(20, min(96, int((view_w - 2*margin) / target_w)))
    # Apply code-configurable zoom
    tile_w = max(8, int(tile_w * float(MAP_ZOOM)))
    # Derive diamond height from tilt angle; build rotated basis
    ang_pitch = max(1e-3, math.radians(float(ISO_ANGLE_DEG)))
    tile_h = max(1, int(round(tile_w * math.tan(ang_pitch))))
    # Fit height too: shrink tile_w if vertical bound would overflow
    max_total_h = max(1, (view_h - 2*margin))
    total_h_for_tile = int(target_w * (tile_h * 0.5))  # (vis_w+vis_h) * half_h
    if total_h_for_tile > max_total_h:
        scale = max_total_h / float(total_h_for_tile)
        tile_w = max(20, int(tile_w * scale))
        tile_h = max(1, int(round(tile_w * math.tan(ang_pitch))))
    hx, hy = tile_w * 0.5, tile_h * 0.5
    ex0x, ex0y = +hx, +hy
    ey0x, ey0y = -hx, +hy
    ang_rot = math.radians(float(ISO_ROT_DEG))
    ca, sa = math.cos(ang_rot), math.sin(ang_rot)
    exx = ca * ex0x - sa * ex0y
    exy = sa * ex0x + ca * ex0y
    eyx = ca * ey0x - sa * ey0y
    eyy = sa * ey0x + ca * ey0y
    # Save on game for other UI uses (treat as square size)
    game.tile_px = tile_w

    # Camera: center on player's tile center in rotated-square space
    px_world = (game.player.x + 0.5) * exx + (game.player.y + 0.5) * eyx
    py_world = (game.player.x + 0.5) * exy + (game.player.y + 0.5) * eyy
    cam_x = px_world - view_w * 0.5
    cam_y = py_world - view_h * 0.5

    # Colors (match editor palette more closely)
    COL_ENEMY    = (160,160,170)  # grey
    COL_ALLY     = (80,200,120)
    COL_CITIZEN  = (80,150,240)
    COL_MONSTER  = (220,70,70)    # red
    COL_VILLAIN  = (170,110,240)  # purple
    COL_ANIMAL   = (245,210,80)
    COL_ITEM     = (240,240,240)
    COL_QITEM    = (255,160,70)
    COL_EVENT    = (160,130,200)
    COL_LINK     = (255,105,180)  # match editor's link color (pink)
    COL_PLAYER   = (122,162,247)  # accent
    # Pixel-style outline colors
    EDGE_DARK  = (16,18,22)
    EDGE_LIGHT = (92,98,120)

    # Prepare diamond mask block removed (squares do not need it)

    depth = max(4, int(tile_h * 0.35))
    origin_x, origin_y = view_rect.x + margin, view_rect.y + margin

    # Compute passable-tiles reachability within N steps (fog-of-war radius)
    # Only tiles reachable via walkable neighbors are considered visible.
    max_steps = 1
    vis: Set[Tuple[int,int]] = set()
    try:
        sx, sy = int(game.player.x), int(game.player.y)
        from collections import deque as _dq
        q = _dq()
        q.append((sx, sy, 0))
        seen = set()
        while q:
            x0, y0, d = q.popleft()
            if (x0, y0) in seen: 
                continue
            seen.add((x0, y0))
            vis.add((x0, y0))
            if d >= max_steps:
                continue
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                nx, ny = x0 + dx, y0 + dy
                if 0 <= nx < W and 0 <= ny < H:
                    try:
                        if getattr(game.grid[ny][nx], 'walkable', False):
                            q.append((nx, ny, d+1))
                    except Exception:
                        pass
        # Persist discovery: any currently visible tile becomes 'discovered'
        try:
            for (vx, vy) in vis:
                try:
                    game.grid[vy][vx].discovered = True
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        # Fallback: only current tile visible
        vis = {(int(getattr(game.player, 'x', 0)), int(getattr(game.player, 'y', 0)))}

    for y in range(H):
        for x in range(W):
            # Center in rotated-square space
            cx = origin_x + ((x + 0.5) * exx + (y + 0.5) * eyx) - cam_x
            cy = origin_y + ((x + 0.5) * exy + (y + 0.5) * eyy) - cam_y
            # Top square corners
            p0 = (cx - 0.5*exx - 0.5*eyx, cy - 0.5*exy - 0.5*eyy)
            p1 = (cx + 0.5*exx - 0.5*eyx, cy + 0.5*exy - 0.5*eyy)
            p2 = (cx + 0.5*exx + 0.5*eyx, cy + 0.5*exy + 0.5*eyy)
            p3 = (cx - 0.5*exx + 0.5*eyx, cy - 0.5*exy + 0.5*eyy)
            # Bounding box for quick cull
            minx = int(min(p0[0], p1[0], p2[0], p3[0]))
            maxx = int(max(p0[0], p1[0], p2[0], p3[0]))
            miny = int(min(p0[1], p1[1], p2[1], p3[1]))
            maxy = int(max(p0[1], p1[1], p2[1], p3[1]))
            br = pg.Rect(minx, miny, max(1, maxx-minx), max(1, maxy-miny))
            if not br.colliderect(view_rect):
                continue
            tile = game.grid[y][x]
            is_vis = (x, y) in vis
            is_revealed = is_vis or bool(getattr(tile, 'discovered', False))
            # Compute top polygon once; only revealed tiles will carve holes
            top_poly = [
                (int(p0[0]), int(p0[1])),
                (int(p1[0]), int(p1[1])),
                (int(p2[0]), int(p2[1])),
                (int(p3[0]), int(p3[1]))
            ]
            if is_revealed:
                _local = [(px - view_rect.x, py - view_rect.y) for (px, py) in top_poly]
                pg.draw.polygon(outside_fog, (0,0,0,0), _local)
            if tile.walkable:
                base = (42,44,56)
                # Neighbor presence (used to hide outer perimeter edges/faces)
                has_left   = (x - 1) >= 0
                has_right  = (x + 1) < W
                has_top    = (y - 1) >= 0
                has_bottom = (y + 1) < H

                # Extruded sides (compute once)
                p0d = (p0[0], p0[1] + depth)
                p1d = (p1[0], p1[1] + depth)
                p2d = (p2[0], p2[1] + depth)
                p3d = (p3[0], p3[1] + depth)
                face_r = [(int(p1[0]),int(p1[1])),(int(p2[0]),int(p2[1])),(int(p2d[0]),int(p2d[1])),(int(p1d[0]),int(p1d[1]))]
                face_f = [(int(p2[0]),int(p2[1])),(int(p3[0]),int(p3[1])),(int(p3d[0]),int(p3d[1])),(int(p2d[0]),int(p2d[1]))]
                col_r = (int(base[0]*0.85), int(base[1]*0.85), int(base[2]*0.85))
                col_f = (int(base[0]*0.70), int(base[1]*0.70), int(base[2]*0.70))

                # Draw internal side faces only (avoid perimeter cliff look)
                side_outline_w = 3 if is_revealed else 2
                if has_right:
                    pg.draw.polygon(surf, col_r, face_r)
                    pg.draw.lines(surf, EDGE_DARK, False, face_r + [face_r[0]], side_outline_w)
                    if is_revealed:
                        # Top bevel highlight on internal right edge
                        pg.draw.line(surf, EDGE_LIGHT, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), 2)
                        pg.draw.line(surf, EDGE_DARK,  (int(p1d[0]), int(p1d[1])), (int(p2d[0]), int(p2d[1])), 3)
                if has_bottom:
                    pg.draw.polygon(surf, col_f, face_f)
                    pg.draw.lines(surf, EDGE_DARK, False, face_f + [face_f[0]], side_outline_w)
                    if is_revealed:
                        # Top bevel highlight on internal front/bottom edge
                        pg.draw.line(surf, EDGE_LIGHT, (int(p2[0]), int(p2[1])), (int(p3[0]), int(p3[1])), 2)
                        pg.draw.line(surf, EDGE_DARK,  (int(p2d[0]), int(p2d[1])), (int(p3d[0]), int(p3d[1])), 3)

                # Top face (top_poly already computed above)
                pg.draw.polygon(surf, base, top_poly)

                # Edge-specific top outlines: draw only where there is an adjacent tile
                def _edge(a, b):
                    return (int(a[0]), int(a[1])), (int(b[0]), int(b[1]))
                e_top    = _edge(p0, p1)  # neighbor at (x, y-1)
                e_right  = _edge(p1, p2)  # neighbor at (x+1, y)
                e_bottom = _edge(p2, p3)  # neighbor at (x, y+1)
                e_left   = _edge(p3, p0)  # neighbor at (x-1, y)

                def draw_edge(edge, do_draw: bool):
                    if not do_draw:
                        return
                    a, b = edge
                    pg.draw.line(surf, EDGE_DARK, a, b, 3)
                    pg.draw.line(surf, EDGE_LIGHT, a, b, 2)

                draw_edge(e_top, has_top)
                draw_edge(e_right, has_right)
                draw_edge(e_bottom, has_bottom)
                draw_edge(e_left, has_left)

                # (Puzzle piece connectors removed per request)
            # Overlay markers (centered dots)
            dot_colors = []
            if tile.encounter:
                enc = tile.encounter
                has: Set[str] = set()
                # NPC categories
                for e in getattr(enc, 'npcs', []) or []:
                    sub = (e.get('subcategory') or '').lower()
                    if sub == 'enemies':
                        has.add('enemy')
                    elif sub == 'allies':
                        has.add('ally')
                    elif sub == 'citizens':
                        has.add('citizen')
                    elif sub == 'monsters':
                        has.add('monster')
                    elif sub == 'villains':
                        has.add('villain')
                    elif sub == 'animals':
                        has.add('animal')
                    else:
                        if e.get('hostile'): has.add('enemy')
                        else: has.add('ally')
                # Items
                its = getattr(enc, 'items', []) or []
                if its:
                    if any((it.get('subcategory','').lower() == 'quest_items') for it in its):
                        has.add('quest_item')
                    if any((it.get('subcategory','').lower() != 'quest_items') for it in its):
                        has.add('item')
                # Events
                if enc.event:
                    has.add('event')
                order = ['enemy','villain','ally','citizen','aberration','calamity','monster','animal','quest_item','item','event']
                color_map = {
                    'enemy': COL_ENEMY,
                    'villain': COL_VILLAIN,
                    'ally': COL_ALLY,
                    'citizen': COL_CITIZEN,
                    'aberration': COL_MONSTER,
                    'calamity': COL_MONSTER,
                    'monster': COL_MONSTER,
                    'animal': COL_ANIMAL,
                    'quest_item': COL_QITEM,
                    'item': COL_ITEM,
                    'event': COL_EVENT,
                }
                for k in order:
                    if k in has:
                        dot_colors.append(color_map[k])
            if tile.has_link:
                dot_colors.append(COL_LINK)
            if is_revealed and dot_colors:
                # layout centered: 1 center; 2 side-by-side; 3 triangle; 4 2x2; >4 balanced rows
                pad = max(2, int(tile_w) // 16)
                n = len(dot_colors)
                if n <= 2:
                    row_counts = [n]
                else:
                    rows = int(math.ceil(math.sqrt(n)))
                    base = n // rows
                    extra = n % rows
                    row_counts = [base] * (rows - extra) + [base + 1] * extra
                rows_cnt = len(row_counts)
                max_cols = max(row_counts)
                gap = max(2, int(tile_w) // 16)
                avail_w = br.w - 2*pad
                avail_h = br.h - 2*pad
                r_w = (avail_w - (max_cols - 1) * gap) / (2 * max_cols) if max_cols else max(4, int(tile_w)//8)
                r_h = (avail_h - (rows_cnt - 1) * gap) / (2 * rows_cnt) if rows_cnt else max(4, int(tile_w)//8)
                rad = int(max(3, min(r_w, r_h, int(tile_w) // 8)))
                # apply visual scale for smaller dots
                r_eff = max(2, int(rad * float(DOT_SIZE_SCALE)))
                gap_x = 2*rad + gap
                gap_y = 2*rad + gap
                total_h = rows_cnt * (2*rad) + (rows_cnt - 1) * gap
                start_y = br.y + (br.h - total_h)//2 + rad
                idx = 0

                # Draw a flat ellipse via the tile basis (exact orientation)
                ex_norm = math.hypot(exx, exy)
                ey_norm = math.hypot(eyx, eyy)
                denom = max(ex_norm, ey_norm, 1e-6)
                scale = float(r_eff) / denom
                steps = max(28, int(20 + r_eff * 1.2))

                def draw_flat_dot(cx, cy, color):
                    pts = []
                    for i in range(steps):
                        t = (2.0 * math.pi) * (i / steps)
                        dx = scale * (math.cos(t) * exx + math.sin(t) * eyx)
                        dy = scale * (math.cos(t) * exy + math.sin(t) * eyy)
                        pts.append((int(round(cx + dx)), int(round(cy + dy))))
                    # top fill only (no 3D extrusion)
                    if gfx is not None:
                        gfx.filled_polygon(surf, pts, color)
                        gfx.aapolygon(surf, pts, (10,10,12))
                    else:
                        pg.draw.polygon(surf, color, pts)
                        pg.draw.lines(surf, (10,10,12), False, pts + [pts[0]], 1)

                # Compute oriented positions using tile-space (u along ex, v along ey)
                u_margin = r_eff / max(ex_norm, 1e-6)
                v_margin = r_eff / max(ey_norm, 1e-6)
                u_max = max(0.0, 0.5 - u_margin - float(DOT_EDGE_INSET))
                v_max = max(0.0, 0.5 - v_margin - float(DOT_EDGE_INSET))
                # convert pixel gaps to tile-space gaps
                ugap = (2*r_eff + gap) / max(ex_norm, 1e-6)
                vgap = (2*r_eff + gap) / max(ey_norm, 1e-6)
                # base spacings
                base_sv = 2*r_eff / max(ey_norm, 1e-6) + vgap
                for ri, cnt in enumerate(row_counts):
                    # spacing along v (rows), centered around 0
                    if rows_cnt > 1:
                        max_spacing_v = (2*v_max) / (rows_cnt - 1)
                        spacing_v = min(base_sv, max_spacing_v) * float(DOT_SPACING_SCALE)
                        v_off = (ri - (rows_cnt - 1) * 0.5) * spacing_v
                    else:
                        v_off = 0.0
                    # spacing along u (columns), centered within the row
                    base_su = 2*r_eff / max(ex_norm, 1e-6) + ugap
                    if cnt > 1:
                        max_spacing_u = (2*u_max) / (cnt - 1)
                        spacing_u = min(base_su, max_spacing_u) * float(DOT_SPACING_SCALE)
                    else:
                        spacing_u = 0.0
                    for cj in range(cnt):
                        if idx >= n: break
                        if cnt > 1:
                            u_off = (cj - (cnt - 1) * 0.5) * spacing_u
                        else:
                            u_off = 0.0
                        # center in screen space
                        dcx = u_off * exx + v_off * eyx
                        dcy = u_off * exy + v_off * eyy
                        draw_flat_dot(cx + dcx, cy + dcy, dot_colors[idx])
                        idx += 1

            # (Removed) Per-tile fog overlay; global overlay now handles fog for unrevealed tiles and outside area uniformly

    # Fog outside the map area: overlay after tiles so only outside-of-grid remains dark
    surf.blit(outside_fog, (view_rect.x, view_rect.y))

    # Player marker: subtly highlight the tile you're standing on
    px = origin_x + px_world - cam_x
    py = origin_y + py_world - cam_y
    if 0 <= (px - view_rect.x) <= view_w and 0 <= (py - view_rect.y) <= view_h:
        q0 = (px - 0.5*exx - 0.5*eyx, py - 0.5*exy - 0.5*eyy)
        q1 = (px + 0.5*exx - 0.5*eyx, py + 0.5*exy - 0.5*eyy)
        q2 = (px + 0.5*exx + 0.5*eyx, py + 0.5*exy + 0.5*eyy)
        q3 = (px - 0.5*exx + 0.5*eyx, py - 0.5*exy + 0.5*eyy)
        poly = [(int(q0[0]), int(q0[1])), (int(q1[0]), int(q1[1])), (int(q2[0]), int(q2[1])), (int(q3[0]), int(q3[1]))]

        # Translucent fill to make the current tile stand out a bit more
        minx = min(p[0] for p in poly)
        maxx = max(p[0] for p in poly)
        miny = min(p[1] for p in poly)
        maxy = max(p[1] for p in poly)
        pad = 2
        ow, oh = max(1, (maxx - minx) + 2*pad), max(1, (maxy - miny) + 2*pad)
        overlay = pg.Surface((ow, oh), pg.SRCALPHA)
        local_poly = [(p[0] - (minx - pad), p[1] - (miny - pad)) for p in poly]
        tint = (*COL_PLAYER, 64)  # slight alpha
        pg.draw.polygon(overlay, tint, local_poly)
        surf.blit(overlay, (minx - pad, miny - pad))

        # Crisp pixel outline around player diamond
        pg.draw.polygon(surf, (10,12,16), poly, 4)
        pg.draw.polygon(surf, (30,34,44), poly, 2)
        pg.draw.polygon(surf, COL_PLAYER, poly, 1)

    # (Removed) Map outer boundary outline per request

def draw_panel(surf, game):
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)
    # Left panel (reserved area)
    pg.draw.rect(surf, (18,18,24), (0,0, panel_w, win_h))
    pg.draw.rect(surf, (70,74,92), (0,0, panel_w, win_h), 1)
    x0 = max(0, win_w - panel_w)
    pg.draw.rect(surf, (18,18,24), (x0,0, panel_w, win_h))
    pg.draw.rect(surf, (70,74,92), (x0,0, panel_w, win_h), 1)
    header_font = pg.font.Font(None, 22)
    draw_text(surf, f"RPGenesis v{get_version()} - Field Log", (x0+16, 12), font=header_font)

    # Left panel content: Party header + player stats
    yL = 12
    draw_text(surf, "Party", (16, yL), font=header_font); yL += 26
    draw_text(surf, f"You: {game.player.name}", (16, yL)); yL += 18
    draw_text(surf, f"Race: {game.player.race}", (16, yL)); yL += 18
    draw_text(surf, f"Class: {game.player.role}", (16, yL)); yL += 18
    draw_text(surf, f"Level: {getattr(game.player,'level',1)}  XP: {getattr(game.player,'xp',0)}/{game._xp_needed(getattr(game.player,'level',1))}", (16, yL)); yL += 18
    draw_text(surf, f"HP: {game.player.hp}/{game.player.max_hp}", (16, yL)); yL += 18
    mn,mx = game.player.atk
    draw_text(surf, f"ATK: {mn}-{mx}", (16, yL)); yL += 18
    # Core Attributes
    draw_text(surf, f"Physique (PHY): {game.player.phy}", (16, yL), color=STAT_COLORS['phy']); yL += 18
    draw_text(surf, f"Technique (DEX): {game.player.dex}", (16, yL), color=STAT_COLORS['dex']); yL += 18
    draw_text(surf, f"Vitality (VIT): {game.player.vit}", (16, yL), color=STAT_COLORS['vit']); yL += 18
    draw_text(surf, f"Arcane (ARC): {game.player.arc}", (16, yL), color=STAT_COLORS['arc']); yL += 18
    draw_text(surf, f"Knowledge (KNO): {game.player.kno}", (16, yL), color=STAT_COLORS['kno']); yL += 18
    draw_text(surf, f"Insight (INS): {game.player.ins}", (16, yL), color=STAT_COLORS['ins']); yL += 18
    draw_text(surf, f"Social (SOC): {game.player.soc}", (16, yL), color=STAT_COLORS['soc']); yL += 18
    draw_text(surf, f"Faith (FTH): {game.player.fth}", (16, yL), color=STAT_COLORS['fth']); yL += 18

    # Scrollable right panel content (below header, above buttons)
    content_top = 44
    buttons_top = win_h - 210
    view_h = max(0, buttons_top - content_top)
    content_clip = pg.Rect(x0, content_top, panel_w, view_h)
    _prev_clip = surf.get_clip(); surf.set_clip(content_clip)
    if not hasattr(game, 'ui_scroll'):
        game.ui_scroll = 0
    y = content_top - max(0, int(getattr(game, 'ui_scroll', 0)))

    # (In combat, the modal handles enemy/allies UI; sidebar remains Field Log)

    # Tile / Equipped summary
    t = game.tile()
    draw_text(surf, f"Tile ({t.x},{t.y})", (x0+16, y)); y += 22
    # Area safety marker from map editor
    try:
        if getattr(t, 'safety', '') == 'safe':
            draw_text(surf, "Area: Safe", (x0+16, y), color=(80,200,120)); y += 18
        elif getattr(t, 'safety', '') == 'danger':
            draw_text(surf, "Area: Danger", (x0+16, y), color=(220,70,70)); y += 18
    except Exception:
        pass
    desc_font = pg.font.Font(None, 22)
    draw_text(surf, t.description, (x0+16, y), max_w=panel_w-32, font=desc_font); y += desc_font.get_linesize() * 2
    # Equipped summary removed: use Equipment overlay to view gear
    y += 8

    # Encounter info
    if t.encounter:
        if t.encounter.enemy:
            s = t.encounter.enemy.get("name","Enemy")
            spotted = " (alerted)" if t.encounter.spotted else " (unaware)"
            draw_text(surf, f"Enemy: {s}{spotted}", (x0+16, y)); y += 20
            est = t.encounter.enemy.get('status', [])
            if est:
                draw_text(surf, "Status: " + ", ".join(est), (x0+28, y)); y += 18
        if t.encounter.npc:
            npcname = t.encounter.npc.get('name','Stranger')
            npcrace = t.encounter.npc.get('race') or 'unknown'
            draw_text(surf, f"NPC: {npcname} (Race: {npcrace})", (x0+16, y)); y += 18
        if t.encounter.event:
            draw_text(surf, f"Event: {t.encounter.event}", (x0+16, y)); y += 18
        # Search status: show remaining items if any
        remaining = len((getattr(t.encounter, 'items', None) or []))
        if remaining > 0:
            draw_text(surf, f"Searchable: {remaining} item(s) remain.", (x0+16, y), (200,200,240)); y += 18
        else:
            draw_text(surf, "Area already searched.", (x0+16, y), (160,160,180)); y += 18

    # Player + log
    y += 6
    draw_text(surf, f"HP: {game.player.hp}/{game.player.max_hp}", (x0+16, y)); y += 18
    draw_text(surf, f"Inventory: {len(game.player.inventory)}", (x0+16, y)); y += 24
    draw_text(surf, "Recent:", (x0+16, y)); y += 16
    for line in game.log:
        block_h = draw_text(surf, f"- {line}", (x0+20, y), max_w=panel_w-36)
        # Add slight spacing between wrapped entries
        y += int(block_h) + 4

    # Update scroll bounds and restore clip
    content_total_h = y - content_top
    game.ui_scroll_max = max(0, content_total_h - view_h)
    surf.set_clip(_prev_clip)

    # Buttons
    y0 = win_h - 210
    buttons = []
    def add(label, cb):
        nonlocal y0
        buttons.append(Button((x0+16, y0, panel_w-32, 34), label, cb)); y0 += 38

    if game.mode == "combat":
        # Show a dedicated combat overlay in the map area
        buttons += draw_combat_overlay(surf, game)
    elif game.mode == "death":
        # Death screen overlay with options
        buttons += draw_death_overlay(surf, game)
    elif game.mode == "dialogue":
        add("Talk",  lambda: game.handle_dialogue_choice("Talk"))
        add("Insult", lambda: game.handle_dialogue_choice("Insult"))
        # Offer Recruit when speaking to an ally-type NPC
        try:
            if getattr(game, 'current_npc', None) and str((game.current_npc.get('subcategory') or '')).lower() == 'allies':
                add("Recruit", lambda: game.handle_dialogue_choice("Recruit"))
        except Exception:
            pass
        add("Leave", lambda: game.handle_dialogue_choice("Leave"))
        add("Inventory", lambda: game.open_overlay('inventory'))
        add("Equipment", lambda: game.open_overlay('equip'))
    elif game.mode == "inventory":
        # Draw a full overlay inventory covering the center and right side
        buttons += draw_inventory_overlay(surf, game)
    elif getattr(game, 'mode', '') == "equip":
        # Draw equipment screen over map area, keep sidebars
        buttons += draw_equip_overlay(surf, game)
    elif getattr(game, 'mode', '') == "save":
        buttons += draw_save_overlay(surf, game)
    elif getattr(game, 'mode', '') == "load":
        buttons += draw_load_overlay(surf, game)
    elif getattr(game, 'mode', '') == "database":
        buttons += draw_database_overlay(surf, game)
    # Removed standalone 'battlefield' mode; battlefield now only appears within combat overlay
    else:
        add("Search Area", game.search_tile)
        # Enemy present: allow direct attack always
        if t.encounter and t.encounter.enemy:
            # If not spotted yet, flag as spotted when attacking to enter combat
            def _attack_now():
                try:
                    if not getattr(t.encounter, 'spotted', False):
                        t.encounter.spotted = True
                except Exception:
                    pass
                # Collect all hostile NPCs on this tile if present
                hostiles = []
                try:
                    def _is_enemy(e: Dict) -> bool:
                        sub = (e.get('subcategory') or '').lower()
                        return sub in ('enemies','monsters','aberrations','calamities','villains','vilains') or bool(e.get('hostile'))
                    for e in (t.encounter.npcs or []):
                        if isinstance(e, dict) and _is_enemy(e):
                            hostiles.append(e)
                except Exception:
                    pass
                if hostiles:
                    game.start_combat_group(hostiles)
                else:
                    game.start_combat(t.encounter.enemy)
            add("Attack", _attack_now)
            # When enemy is unaware, offer a single combined avoid option
            if not t.encounter.spotted:
                add("Avoid (Sneak/Bypass)", game.avoid_enemy)
        if t.encounter and (t.encounter.npc or (t.encounter.npcs and len(t.encounter.npcs) > 0)):
            # List all friendly NPCs on this tile and allow choosing one to talk to
            try:
                def _is_enemy_e(e: Dict) -> bool:
                    sub = (e.get('subcategory') or '').lower()
                    return sub in ('enemies','monsters','aberrations','calamities','villains','vilains') or bool(e.get('hostile'))
                friendlies = [e for e in (t.encounter.npcs or []) if isinstance(e, dict) and not _is_enemy_e(e)]
                if not friendlies and t.encounter.npc:
                    friendlies = [t.encounter.npc]
            except Exception:
                friendlies = [t.encounter.npc] if t.encounter and t.encounter.npc else []

            # Add a button per friendly to begin dialogue
            for npc in friendlies[:6]:
                nm = str(npc.get('name') or 'Someone')
                add(f"Talk: {nm}",      lambda npc=npc: (setattr(game, 'current_npc', npc), setattr(game, 'mode', 'dialogue')))
            # Quick recruit entry remains for allies for convenience
            try:
                for npc in friendlies[:6]:
                    if str((npc or {}).get('subcategory') or '').lower() == 'allies':
                        add(f"Ask To Join: {npc.get('name','Ally')}", lambda npc=npc: (setattr(game, 'current_npc', npc), game.handle_dialogue_choice("Recruit")))
                        break
            except Exception:
                pass
        # Travel via link if present
        if getattr(t, 'link_to_map', None):
            dest = t.link_to_map
            add(f"Travel to {dest}", game.travel_link)
            add("Leave NPC", lambda: game.handle_dialogue_choice("Leave"))
        add("Inventory", lambda: game.open_overlay('inventory'))
        add("Equipment", lambda: game.open_overlay('equip'))
        add("Database", lambda: game.open_overlay('database'))
        # Removed standalone Battlefield menu entry; battlefield appears only during combat
        add("Save Game", lambda: game.open_overlay('save'))
        add("Load Game", lambda: game.open_overlay('load'))

    # Keep side action buttons within window bounds by shifting them up if needed
    try:
        side_btns = [b for b in buttons if isinstance(getattr(b, 'rect', None), pg.Rect) and b.rect.x == x0+16 and b.rect.w == (panel_w-32)]
        if side_btns:
            step = 38
            needed = len(side_btns) * step
            # Place as low as possible but fully visible; never above the header
            base_y = max(44, min(win_h - 210, win_h - needed - 12))
            # expose for scroll-area calculations
            try: game._buttons_top = int(base_y)
            except Exception: pass
            ycur = int(base_y)
            for b in side_btns:
                b.rect.y = ycur
                b.rect.h = 34
                b.rect.x = x0 + 16
                b.rect.w = panel_w - 32
                ycur += step
    except Exception:
        pass

    for b in buttons: b.draw(surf)
    return buttons

def draw_inventory_panel(surf, game, x0, panel_w):
    """Returns list of Button objects for the inventory sub-panel."""
    buttons = []
    # panel header
    y = 320
    pg.draw.line(surf, (70,74,92), (x0+12, y-6), (x0+panel_w-12, y-6), 1)
    draw_text(surf, "Inventory", (x0+16, y)); y += 20

    # pagination state
    if not hasattr(game, "inv_page"): game.inv_page = 0
    if not hasattr(game, "inv_sel"): game.inv_sel = None

    per_page = 6
    total = len(game.player.inventory)
    pages = max(1, (total + per_page - 1)//per_page)
    page = max(0, min(game.inv_page, pages-1))
    start = page*per_page
    items = game.player.inventory[start:start+per_page]

    # list items as clickable rows
    row_h = 26
    for i, it in enumerate(items):
        r = pg.Rect(x0+16, y+i*row_h, panel_w-32, row_h-4)
        sel = (game.inv_sel == start+i)
        pg.draw.rect(surf, (52,56,70) if sel else (34,36,46), r, border_radius=6)
        pg.draw.rect(surf, (90,94,112), r, 1, border_radius=6)
        label = f"{item_name(it)}  [{item_type(it)}/{item_subtype(it)}]"
        draw_text(surf, label, (r.x+8, r.y+5))
        def make_sel(idx):
            return lambda idx=idx: setattr(game, 'inv_sel', idx)
        buttons.append(Button(r, "", make_sel(start+i)))

    y += per_page*row_h + 4

    # info & actions for selected item
    if game.inv_sel is not None and 0 <= game.inv_sel < total:
        it = game.player.inventory[game.inv_sel]
        draw_text(surf, (item_desc(it) or "-"), (x0+16, y), max_w=panel_w-32); y += 36
        subtype = str(item_subtype(it)).lower()
        typ = str(item_type(it)).lower()
        if typ == "weapon":
            buttons.append(Button((x0+16, y, 160, 30), "Equip Weapon", lambda: game.equip_weapon(it)))
            y += 34
        # Drop button
        buttons.append(Button((x0+16, y, 160, 30), "Drop", lambda: game.drop_item(game.inv_sel)))
        # Close
        buttons.append(Button((x0+16+170, y, 160, 30), "Close", lambda: game.close_overlay()))
    else:
        # Pager + Close when nothing selected
        buttons.append(Button((x0+16, y, 110, 28), "Prev Page", lambda: setattr(game,'inv_page', max(0, game.inv_page-1))))
        buttons.append(Button((x0+16+120, y, 110, 28), "Next Page", lambda: setattr(game,'inv_page', min(pages-1, game.inv_page+1))))
        buttons.append(Button((x0+16+240, y, 90, 28), "Close", lambda: game.close_overlay()))

    return buttons

def draw_combat_overlay(surf, game):
    """Battle overlay centered over the map area with enemy info and big actions.

    Returns list of Button objects for click handling.
    """
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)

    # Map view area (between left and right panels)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)

    # Dim background only over the map area
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10, 10, 14, 160))
    surf.blit(dim, (view_rect.x, view_rect.y))

    # Modal rectangle (wider, closer to sidebars)
    modal_w = max(640, int(view_w * 0.95))
    modal_h = max(360, int(view_h * 0.72))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)

    # Panel
    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (96,102,124), modal, 2, border_radius=10)
    pg.draw.rect(surf, (56,60,76), modal.inflate(-8, -8), 1, border_radius=8)

    # Header
    title_font = pg.font.Font(None, 30)
    subtitle_font = pg.font.Font(None, 22)
    # Compact fonts for stat bars
    stat_name_font = pg.font.Font(None, 20)
    stat_label_font = pg.font.Font(None, 16)
    surf.blit(title_font.render("Battle", True, (235,235,245)), (modal.x + 16, modal.y + 12))

    # Content layout: sidebars (allies/enemies) and big center battlefield with action bar
    pad = 12
    content = modal.inflate(-2*pad, -2*pad)
    # Turn order bar at the top of the battle scene
    try:
        if getattr(game, 'mode', '') == 'combat':
            order = list(getattr(game, 'turn_order', []) or [])
            if order:
                # Place under the title area
                order_area = pg.Rect(content.x, content.y + 36, content.w, 26)
                # Background strip
                pg.draw.rect(surf, (30,32,42), order_area, border_radius=8)
                pg.draw.rect(surf, (70,74,92), order_area, 1, border_radius=8)
                n = len(order)
                gap = 6
                chip_h = 20
                # Compute chip width to fit all within area
                chip_w = max(60, min(160, int((order_area.w - gap*(n-1) - 10) / max(1, n))))
                x = order_area.x + 5
                y = order_area.y + (order_area.h - chip_h)//2
                cur_idx = int(getattr(game, 'turn_index', 0) or 0)
                def _chip_color(t):
                    if t == 'enemy': return (220,70,70)
                    if t == 'ally': return (80,200,120)
                    if t == 'player': return (80,150,240)
                    return (96,102,124)
                label_font = pg.font.Font(None, 18)
                for i, ent in enumerate(order):
                    t = str(ent.get('type',''))
                    nm = str(ent.get('name') or t.title())
                    # Trim overly long names
                    max_chars = max(6, int(chip_w/9))
                    if len(nm) > max_chars:
                        nm = nm[:max_chars-1] + '...'
                    r = pg.Rect(x, y, chip_w, chip_h)
                    col = _chip_color(t)
                    # Current actor emphasis
                    is_cur = (i == cur_idx)
                    bg = col if is_cur else (max(col[0]-30,24), max(col[1]-30,24), max(col[2]-30,24))
                    pg.draw.rect(surf, bg, r, border_radius=7)
                    pg.draw.rect(surf, (240,240,248) if is_cur else (200,205,220), r, 2 if is_cur else 1, border_radius=7)
                    # Small type dot
                    dot_r = 5
                    try:
                        pg.draw.circle(surf, (245,245,250), (r.x+10, r.centery), dot_r)
                        pg.draw.circle(surf, col, (r.x+10, r.centery), dot_r-2)
                    except Exception:
                        pass
                    # Label
                    try:
                        txt = label_font.render(nm, True, (245,245,250))
                        surf.blit(txt, (r.x + 20, r.y + (r.h - txt.get_height())//2))
                    except Exception:
                        pass
                    x += chip_w + gap
    except Exception:
        # Never break combat UI on draw errors
        pass
    # Make side info panels slightly narrower to widen the battlefield
    side_w = max(200, int(content.w * 0.21))
    # Leave room for the title + turn-order bar
    top_offset = 68
    left = pg.Rect(content.x, content.y + top_offset, side_w, content.h - top_offset)
    right = pg.Rect(content.right - side_w, content.y + top_offset, side_w, content.h - top_offset)
    center = pg.Rect(left.right + 8, content.y + top_offset, right.left - (left.right + 8), content.h - top_offset)
    # Split center into battlefield (top) + actions (bottom)
    act_h = max(96, int(center.h * 0.22))
    bf_area = pg.Rect(center.x, center.y, center.w, center.h - act_h - 8)
    act_area = pg.Rect(center.x, bf_area.bottom + 8, center.w, act_h)
    # Draw frames first so battlefield always sits on top within its center region
    for r in (left, right, act_area):
        pg.draw.rect(surf, (30,32,42), r, border_radius=8)
        pg.draw.rect(surf, (70,74,92), r, 1, border_radius=8)
    # Draw battlefield scene centered on top of frames
    try:
        _draw_battlefield_canvas(surf, game, bf_area)
    except Exception:
        pass
    # (frames already drawn above)

    # Enemy panel (now on the right) supports multiple enemies
    CARD_OUTER_GAP = 16  # vertical spacing from container and between stat boxes
    enemies_list = list(getattr(game, 'current_enemies', []) or [])
    if not enemies_list:
        enemy = getattr(game, 'current_enemy', None) or (getattr(game.tile().encounter, 'enemy', None) if game.tile().encounter else None)
        if enemy:
            enemies_list = [enemy]
    current_target = getattr(game, 'current_enemy', None)
    def _make_target_cb(idx: int):
        return lambda idx=idx: game.select_enemy_target(idx)

    ex = right.x + 12; ey = right.y + 12
    for idx_e, enemy in enumerate(enemies_list):
        # Start of this enemy's stat card block (for enclosing box)
        card_y0 = ey
        ehp_cur = 0
        ehp_max = 0
        try:
            if hasattr(game, 'current_enemies') and hasattr(game, 'current_enemies_hp') and game.current_enemies:
                # derive hp from parallel list when available
                if idx_e < len(game.current_enemies_hp):
                    ehp_cur = int(game.current_enemies_hp[idx_e])
                    if hasattr(game, 'current_enemies_max_hp') and idx_e < len(game.current_enemies_max_hp):
                        ehp_max = int(game.current_enemies_max_hp[idx_e])
                    else:
                        ehp_max = int(enemy.get('hp', ehp_cur) or ehp_cur)
                else:
                    ehp_cur = int(enemy.get('hp', 12)); ehp_max = ehp_cur
            else:
                ehp_cur = int(getattr(game, 'current_enemy_hp', 0) or (enemy.get('hp', 12) if isinstance(enemy, dict) else 0))
                ehp_max = int((enemy.get('hp', ehp_cur) if isinstance(enemy, dict) else ehp_cur) or max(1, ehp_cur))
        except Exception:
            ehp_cur = int(enemy.get('hp', 12) if isinstance(enemy, dict) else 12); ehp_max = ehp_cur
        ename = str(enemy.get('name', 'Enemy'))
        # Ensure long enemy names wrap within the stat box
        ey += draw_text(surf, ename, (ex, ey), font=stat_name_font, max_w=right.w - 24)
        # Subtle divider under name
        try:
            pg.draw.line(surf, (70,74,92), (right.x + 12, ey + 4), (right.right - 12, ey + 4), 1)
        except Exception:
            pass
        ey += 8
        # Enemy race (if available)
        try:
            erace = str(enemy.get('race') or enemy.get('Race') or '')
        except Exception:
            erace = ''
        # Fallback: lookup enemy by id/name in loaded NPCs to get race
        if not erace:
            try:
                eid = str(enemy.get('id') or '')
                ename_lc = str(enemy.get('name') or '').lower()
                for _n in (getattr(game, 'npcs', []) or []):
                    if not isinstance(_n, dict):
                        continue
                    nid = str(_n.get('id') or '')
                    nm  = str(_n.get('name') or '').lower()
                    if (eid and nid == eid) or (ename_lc and nm == ename_lc):
                        erace = str(_n.get('race') or _n.get('Race') or '')
                        if erace:
                            break
            except Exception:
                pass
        if erace:
            ey += draw_text(surf, f"Race: {erace}", (ex, ey), font=stat_label_font, max_w=right.w - 24)
        # HP bar (compact)
        bar_w, bar_h = right.w - 24, 12
        rect = pg.Rect(ex, ey, bar_w, bar_h)
        pg.draw.rect(surf, (40,42,56), rect, border_radius=6)
        frac = max(0.0, min(1.0, ehp_cur / float(max(1, ehp_max))))
        fill = rect.inflate(-4, -4)
        fill.w = int((rect.w - 4) * frac)
        pg.draw.rect(surf, (200,70,70), fill, border_radius=5)
        pg.draw.rect(surf, (96,102,124), rect, 1, border_radius=6)
        # HP label (compact) + race inline
        hp_txt = f"HP: {ehp_cur}/{ehp_max}"
        # Wrap HP label text to keep within borders
        _label_y = ey + bar_h + 6
        _label_h = draw_text(surf, hp_txt, (ex, _label_y), font=stat_label_font, max_w=right.w - 24)
        ey = _label_y + _label_h + 4
        # Status
        try:
            est = [str(s) for s in (enemy.get('status') or [])]
        except Exception:
            est = []
        if est:
            ey += draw_text(surf, "Status: " + ", ".join(est), (ex, ey), font=stat_label_font, max_w=right.w - 24) + 2
        # Flavor/desc if present
        desc = str(enemy.get('desc') or enemy.get('description') or '')
        if desc:
            ey += draw_text(surf, desc, (ex, ey), font=stat_label_font, max_w=right.w - 24) + 2
        # Draw enclosing outline box for this enemy's stats (inner padding)
        card_pad_x, card_pad_y = 10, 8
        card_x = right.x + card_pad_x
        card_w = right.w - 2*card_pad_x
        card_h = (ey - card_y0) + 2*card_pad_y
        card_r = pg.Rect(card_x, max(right.y + CARD_OUTER_GAP, card_y0 - card_pad_y), card_w, max(24, card_h))
        # Draw refined border with inner accent
        is_selected = (enemy is current_target)
        border_col = (122,162,247) if is_selected else (70,74,92)
        border_w = 2 if is_selected else 1
        pg.draw.rect(surf, border_col, card_r, border_w, border_radius=6)
        try:
            inner_col = (96,102,140) if is_selected else (56,60,76)
            pg.draw.rect(surf, inner_col, card_r.inflate(-4, -4), 1, border_radius=5)
        except Exception:
            pass
        buttons.append(Button(card_r, '', _make_target_cb(idx_e), draw_bg=False))
        # Spacing between enemies
        ey = card_r.bottom + CARD_OUTER_GAP
    if not enemies_list:
        draw_text(surf, "No target.", (ex, ey), font=stat_label_font, max_w=right.w - 24)

    # Allies (left sidebar): player + party stats
    rx, ry = left.x + 12, left.y + 12
    def draw_actor_card(actor):
        nonlocal rx, ry
        card_y0 = ry
        pname = f"{getattr(actor,'name','')}"
        ry += draw_text(surf, pname, (rx, ry), font=stat_name_font, max_w=left.w - 24)
        # Subtle divider under name
        try:
            pg.draw.line(surf, (70,74,92), (left.x + 12, ry + 4), (left.right - 12, ry + 4), 1)
        except Exception:
            pass
        ry += 8
        # Race
        try:
            prace = str(getattr(actor, 'race', '') or '')
        except Exception:
            prace = ''
        if prace:
            ry += draw_text(surf, f"Race: {prace}", (rx, ry), font=stat_label_font, max_w=left.w - 24)
        # HP bar
        php_cur = int(getattr(actor, 'hp', 0)); php_max = int(getattr(actor, 'max_hp', max(1, php_cur)))
        pbar = pg.Rect(rx, ry, left.w - 24, 12)
        pg.draw.rect(surf, (40,42,56), pbar, border_radius=6)
        pfill = pbar.inflate(-4, -4)
        pfill.w = int((pbar.w - 4) * max(0.0, min(1.0, php_cur / float(max(1, php_max)))))
        pg.draw.rect(surf, (120,200,120), pfill, border_radius=5)
        pg.draw.rect(surf, (96,102,124), pbar, 1, border_radius=6)
        ry += 14 + draw_text(surf, f"HP: {php_cur}/{php_max}", (rx, ry + 14), font=stat_label_font, max_w=left.w - 24) + 10
        # Equipped summary
        try:
            weapon_obj = getattr(actor, 'equipped_weapon', None)
            if not weapon_obj:
                gear_map = getattr(actor, 'equipped_gear', {}) or {}
                if isinstance(gear_map, dict):
                    weapon_obj = gear_map.get('weapon_main')
        except Exception:
            weapon_obj = getattr(actor, 'equipped_weapon', None)
        wep = _combat_item_label(weapon_obj, "Unarmed")
        ry += draw_text(surf, f"Weapon: {wep}", (rx, ry), font=stat_label_font, max_w=left.w - 24)
        ry += 4
        # Enclosing card
        p_pad_x, p_pad_y = 10, 8
        p_card_x = left.x + p_pad_x
        p_card_w = left.w - 2*p_pad_x
        p_card_h = (ry - card_y0) + 2*p_pad_y
        p_card_r = pg.Rect(p_card_x, max(left.y + CARD_OUTER_GAP, card_y0 - p_pad_y), p_card_w, max(24, p_card_h))
        pg.draw.rect(surf, (70,74,92), p_card_r, 1, border_radius=6)
        try:
            pg.draw.rect(surf, (56,60,76), p_card_r.inflate(-4, -4), 1, border_radius=5)
        except Exception:
            pass
        ry = p_card_r.bottom + 10

    # Player card
    draw_actor_card(game.player)
    # Party members cards
    for ally in (getattr(game, 'party', []) or []):
        draw_actor_card(ally)

    # Action buttons grid (2 columns) centered in action area
    bx, by = act_area.x + 12, act_area.y + 12
    # Actions header
    try:
        _act_fnt = pg.font.Font(None, 20)
        surf.blit(_act_fnt.render("Actions", True, (220,225,240)), (bx, by))
        pg.draw.line(surf, (70,74,92), (act_area.x + 10, by + 18), (act_area.right - 10, by + 18), 1)
        by += 24
    except Exception:
        pass
    bw = (act_area.w - 24 - 8) // 2
    bh = 36
    gap = 8
    def add_btn(x, y, label, cb):
        buttons.append(Button((x, y, bw, bh), label, cb))

    add_btn(bx, by, "Attack", game.attack); add_btn(bx + bw + gap, by, "Cast Spell", game.cast_spell); by += bh + gap
    add_btn(bx, by, "Talk", game.talk_enemy)
    if getattr(game, 'can_bribe', False):
        add_btn(bx + bw + gap, by, "Offer Bribe", game.offer_bribe)
    else:
        # Reserve space for consistent layout
        pass
    by += bh + gap
    add_btn(bx, by, "Flee", game.flee)
    add_btn(bx + bw + gap, by, "Inventory", lambda: game.open_overlay('inventory')); by += bh + gap
    add_btn(bx, by, "Equipment", lambda: game.open_overlay('equip'))
    # Removed Database option from battle scene

    return buttons

def draw_inventory_overlay(surf, game):
    """Centered inventory modal over the map area, with border.

    Keeps the right sidebar intact. Returns list of Button objects for clicks.
    """
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)

    # Map view area (between left and right panels)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)

    # Centered modal rect inside the map view
    inset = 24
    modal_w = max(420, int(view_w * 0.82))
    modal_h = max(320, int(view_h * 0.82))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)

    # Dim background only over the map area
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10, 10, 14, 140))
    surf.blit(dim, (view_rect.x, view_rect.y))

    # Modal panel with border
    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (96,102,124), modal, 2, border_radius=10)
    # Inner outline for extra readability
    pg.draw.rect(surf, (56,60,76), modal.inflate(-8, -8), 1, border_radius=8)

    # Title
    title_font = pg.font.Font(None, 30)
    title_surf = title_font.render("Inventory", True, (235,235,245))
    surf.blit(title_surf, (modal.x + 16, modal.y + 12))
    # Header buttons: Equipment and Back
    def _to_equip(): setattr(game, 'mode', 'equip')
    buttons.append(Button((modal.right - 230, modal.y + 10, 110, 28), "Equipment", _to_equip))
    def _db_back():
        try:
            if hasattr(game, 'close_overlay') and callable(getattr(game, 'close_overlay')):
                game.close_overlay()
            else:
                # Main menu database context: signal exit via mode='explore'
                setattr(game, 'mode', 'explore')
        except Exception:
            try:
                setattr(game, 'mode', 'explore')
            except Exception:
                pass
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", _db_back))

    # Layout inside modal: icons grid left, details right
    pad = 16
    content = modal.inflate(-2*pad, -2*pad)
    grid_area = pg.Rect(content.x, content.y + 36, int(content.w * 0.52), content.h - 52)
    det_area  = pg.Rect(content.x + grid_area.w + 12, content.y + 36, content.w - grid_area.w - 12, content.h - 52)

    # Draw boxes
    for r in (grid_area, det_area):
        pg.draw.rect(surf, (30,32,42), r, border_radius=8)
        pg.draw.rect(surf, (70,74,92), r, 1, border_radius=8)

    # State
    if not hasattr(game, 'inv_page'): game.inv_page = 0
    if not hasattr(game, 'inv_sel'):  game.inv_sel = None

    items = game.player.inventory
    total = len(items)

    # Icon grid sizing (bigger buttons/icons)
    icon = max(64, min(96, grid_area.w // 5))  # aim ~4 cols, larger tiles
    gap = max(12, icon // 5)
    # Label font and height tuned to icon size (support 2 lines)
    lab_font = pg.font.Font(None, max(20, icon // 3))
    lab_h = lab_font.get_linesize()
    lab_lines = 2
    cols = max(3, (grid_area.w - gap) // (icon + gap))
    rows = max(2, (grid_area.h - gap) // (icon + lab_lines*lab_h + gap))
    per_page = max(1, cols * rows)
    pages = max(1, (total + per_page - 1) // per_page)
    game.inv_page = max(0, min(game.inv_page, pages-1))
    start = game.inv_page * per_page
    end = min(total, start + per_page)

    # Hover position (for highlight only)
    mx, my = pg.mouse.get_pos()

    # Color by major type
    def type_color(it: dict) -> Tuple[int,int,int]:
        t = item_major_type(it)
        return {
            'weapon': (140,120,220),
            'armour': (120,170,220), 'armor': (120,170,220),
            'clothing': (120,170,220),
            'accessory': (200,160,220), 'accessories': (200,160,220),
            'consumable': (180,220,140), 'consumables': (180,220,140),
            'material': (220,180,120), 'materials': (220,180,120),
            'trinket': (220,200,150), 'trinkets': (220,200,150),
            'quest': (220,150,150), 'quest_item': (220,150,150), 'quest_items': (220,150,150),
        }.get(t, (180,190,210))

    # Draw icons grid
    x = grid_area.x + gap
    y = grid_area.y + gap
    # Helper to check if an item is currently equipped by the player
    def _is_equipped_by_player(it: dict) -> bool:
        try:
            p = game.player
            if getattr(p, 'equipped_weapon', None) is it: return True
            # legacy focus slot removed
            for v in (getattr(p, 'equipped_gear', {}) or {}).values():
                if v is it: return True
        except Exception:
            pass
        return False
    for i in range(start, end):
        it = items[i]
        col = (i - start) % cols
        row = (i - start) // cols
        r = pg.Rect(x + col * (icon + gap), y + row * (icon + 24 + gap), icon, icon)
        # Icon background
        base = (38,40,52)
        border = (90,94,112)
        sel = (game.inv_sel == i)
        hov = r.collidepoint(mx, my)
        if sel:
            pg.draw.rect(surf, (48,52,68), r, border_radius=6)
            pg.draw.rect(surf, (122,162,247), r, 2, border_radius=6)
        else:
            pg.draw.rect(surf, (48,52,68) if hov else base, r, border_radius=6)
            pg.draw.rect(surf, border, r, 1, border_radius=6)
        # Colored inner tag stripe (rarity color when available)
        tag = r.inflate(-10, -10)
        tag.h = max(8, icon // 6)
        _rar = str((it.get('rarity') or '')).lower()
        _rc = RARITY_COLORS.get(_rar)
        pg.draw.rect(surf, _rc if _rc else type_color(it), (tag.x, tag.y, tag.w, tag.h), border_radius=4)
        # Icon glyph (first letter of type)
        glyph = (str(item_type(it)) or '?')[:1].upper()
        gfont = pg.font.Font(None, max(18, icon // 2))
        gs = gfont.render(glyph, True, (235,235,245))
        surf.blit(gs, (r.centerx - gs.get_width()//2, r.centery - gs.get_height()//2))
        # Equipped marker (top-right corner)
        try:
            if _is_equipped_by_player(it):
                # Small gold dot with a checkmark
                mr = max(6, icon // 8)
                cx, cy = r.right - mr - 4, r.y + mr + 4
                pg.draw.circle(surf, (12,14,18), (cx, cy), mr + 2)              # dark outline
                pg.draw.circle(surf, RARITY_COLORS.get('mythic', (245,210,80)), (cx, cy), mr)
                # Tiny check
                try:
                    chk = pg.font.Font(None, max(14, icon // 5)).render('[OK]', True, (18,18,22))
                    surf.blit(chk, (cx - chk.get_width()//2, cy - chk.get_height()//2 - 1))
                except Exception:
                    # Fallback: draw a simple tick with lines
                    pg.draw.line(surf, (18,18,22), (cx - mr//2, cy), (cx - mr//6, cy + mr//3), 2)
                    pg.draw.line(surf, (18,18,22), (cx - mr//6, cy + mr//3), (cx + mr//2, cy - mr//3), 2)
        except Exception:
            pass
        # Label (name) under icon - multi-line (up to 2), colored by rarity
        name = item_name(it)
        lab_y = r.bottom + 4
        max_w = icon
        # Simple two-line word wrap with ellipsis on the last line
        words = str(name).split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if lab_font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                else:
                    # Single long word: truncate with ellipsis
                    t = w
                    while len(t) > 1 and lab_font.size(t + '...')[0] > max_w:
                        t = t[:-1]
                    lines.append(t + '...')
                    cur = ""
                    break
                cur = w
                if len(lines) >= lab_lines - 1:
                    # finalize last line with ellipsis
                    t = cur
                    while len(t) > 1 and lab_font.size(t + '...')[0] > max_w:
                        t = t[:-1]
                    lines.append((t + '...') if t else '')
                    cur = ""
                    break
        if cur and len(lines) < lab_lines:
            lines.append(cur)
        # Render lines centered under icon
        name_col = _rc if _rc else (220,220,230)
        for li, text in enumerate(lines[:lab_lines]):
            ts = lab_font.render(text, True, name_col)
            surf.blit(ts, (r.centerx - ts.get_width()//2, lab_y + li*lab_h))
        # Clickable button area: include icon + label block
        click_rect = pg.Rect(r.x, r.y, r.w, r.h + lab_lines*lab_h + 6)
        def make_sel(idx):
            return lambda idx=idx: setattr(game, 'inv_sel', idx)
        buttons.append(Button(click_rect, "", make_sel(i), draw_bg=False))

    # Pager controls (bottom-left of grid area)
    pager_y = grid_area.bottom - 30
    buttons.append(Button((grid_area.x + 10, pager_y, 110, 26), "Prev Page", lambda: setattr(game,'inv_page', max(0, game.inv_page-1))))
    buttons.append(Button((grid_area.x + 10 + 120, pager_y, 110, 26), "Next Page", lambda: setattr(game,'inv_page', min(pages-1, game.inv_page+1))))

    # Details area for the selected item
    if game.inv_sel is not None and 0 <= game.inv_sel < total:
        it = items[game.inv_sel]
        name_font = pg.font.Font(None, 28)
        _rar = str((it.get('rarity') or '')).lower(); _rc = RARITY_COLORS.get(_rar)
        draw_text(surf, item_name(it), (det_area.x + 12, det_area.y + 10), color=_rc or (235,235,245), font=name_font)
        y2 = det_area.y + 48
        typ = item_type(it); sub = item_subtype(it)
        wt = item_weight(it); val = item_value(it)
        draw_text(surf, f"Type: {typ} / {sub}", (det_area.x + 12, y2)); y2 += 22
        draw_text(surf, f"Weight: {wt}", (det_area.x + 12, y2)); y2 += 22
        draw_text(surf, f"Value: {val}", (det_area.x + 12, y2)); y2 += 26
        desc = item_desc(it) or ""
        # Detailed stats
        try:
            rarity = str(it.get('rarity') or '').title()
            if rarity:
                y2 += draw_text(surf, f"Rarity: {rarity}", (det_area.x + 12, y2))
        except Exception:
            pass
        # Show combat-relevant stats
        mtyp = item_major_type(it)
        if mtyp == 'weapon':
            mn, mx, _, _ = _weapon_stats(it)
            y2 += draw_text(surf, f"Damage: {mn}-{mx}", (det_area.x + 12, y2))
            dmg_map = it.get('damage_type') or {}
            if isinstance(dmg_map, dict) and dmg_map:
                parts = []
                for k, v in dmg_map.items():
                    try: parts.append(f"{k}+{int(v)}")
                    except Exception: pass
                if parts:
                    y2 += draw_text(surf, "Types: " + ", ".join(parts), (det_area.x + 12, y2))
            tr = str(it.get('weapon_trait') or it.get('trait') or '')
            if tr:
                y2 += draw_text(surf, f"Trait: {tr}", (det_area.x + 12, y2))
        elif mtyp in ('armour','armor','clothing','accessory','accessories'):
            def_map = it.get('defense_type') or {}
            if isinstance(def_map, dict) and def_map:
                # Show up to 5 defenses per line
                parts = []
                for k, v in def_map.items():
                    try: parts.append(f"{k}+{int(v)}")
                    except Exception: pass
                if parts:
                    y2 += draw_text(surf, "Defense: " + ", ".join(parts), (det_area.x + 12, y2))
            tr = str(it.get('armour_trait') or it.get('armor_trait') or it.get('trait') or '')
            if tr:
                y2 += draw_text(surf, f"Trait: {tr}", (det_area.x + 12, y2))
            # Show bonuses
            b = it.get('bonus') or {}
            if isinstance(b, dict) and b:
                parts = []
                for k, v in b.items():
                    try: parts.append(f"{k}+{int(v)}")
                    except Exception: pass
                if parts:
                    y2 += draw_text(surf, "Bonus: " + ", ".join(parts), (det_area.x + 12, y2))
        # Description at the end
        desc = item_desc(it) or ""
        if desc:
            y2 += 6
            draw_text(surf, desc, (det_area.x + 12, y2), max_w=det_area.w - 24); y2 += 90

        # Action buttons along bottom of details
        bx = det_area.x + 12; by = det_area.bottom - 34
        mtyp = item_major_type(it)
        sub_l = str(sub).lower()
        if mtyp == 'weapon':
            buttons.append(Button((bx, by, 160, 28), "Equip Weapon", lambda it=it: game.equip_item(it))); bx += 170
        elif mtyp in ('armour','armor','clothing','accessory','accessories'):
            buttons.append(Button((bx, by, 160, 28), "Equip", lambda it=it: game.equip_item(it))); bx += 170
        if item_is_consumable(it):
            buttons.append(Button((bx, by, 140, 28), "Consume", lambda idx=game.inv_sel: game.consume_item(idx))); bx += 150
        if not item_is_quest(it):
            buttons.append(Button((bx, by, 120, 28), "Drop", lambda idx=game.inv_sel: game.drop_item(idx))); bx += 130

    # Back button moved to header above

    # Tooltips removed per request

    return buttons

def draw_death_overlay(surf, game):
    """Centered death modal with choices: Main Menu or Load Last Save.

    Returns list of Button objects for click handling.
    """
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)

    # Map view area (between left and right panels)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)

    # Dim background only over the map area
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10, 10, 14, 190))
    surf.blit(dim, (view_rect.x, view_rect.y))

    # Modal panel
    modal_w = max(520, int(view_w * 0.6))
    modal_h = max(240, int(view_h * 0.36))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)

    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (150,64,64), modal, 2, border_radius=10)
    pg.draw.rect(surf, (56,60,76), modal.inflate(-8, -8), 1, border_radius=8)

    # Title and message
    title_font = pg.font.Font(None, 34)
    msg_font = pg.font.Font(None, 22)
    surf.blit(title_font.render("You Have Fallen", True, (240,220,220)), (modal.x + 16, modal.y + 14))
    info = "Choose an option: return to main menu or load your most recent save."
    draw_text(surf, info, (modal.x + 16, modal.y + 54), font=msg_font, max_w=modal.w - 32)

    # Buttons
    bw = 180; bh = 40; gap = 16
    by = modal.bottom - bh - 24
    total_w = bw*2 + gap
    bx = modal.x + (modal.w - total_w)//2

    def _to_menu():
        # Signal the game loop to return to main menu
        setattr(game, '_req_main_menu', True)

    def _load_last():
        try:
            slot = _latest_save_slot()
        except Exception:
            slot = None
        if slot is None:
            game.say("No saves available to load.")
            return
        ok = game.load_from_slot(int(slot))
        if not ok:
            game.say("Failed to load the last save.")

    buttons.append(Button((bx, by, bw, bh), "Main Menu", _to_menu))
    buttons.append(Button((bx + bw + gap, by, bw, bh), "Load Last Save", _load_last))

    return buttons

def _ensure_battlefield_demo(game):
    # Prepare a simple demo lineup if none exists yet
    if not hasattr(game, 'bf_allies'):
        game.bf_allies = [
            'images/player/player.png',
            'images/allies/fighter.png',
            'images/allies/witch.png',
        ]
    if not hasattr(game, 'bf_enemies'):
        game.bf_enemies = [
            'images/enemies/demon_girl.png',
            'images/enemies/demon_girl_large.png',
        ]
    if not hasattr(game, '_bf_cache'):
        game._bf_cache = {}

def _load_sprite_cached(game, key: str, max_size: Tuple[int,int]):
    if pg is None:
        return None
    if not hasattr(game, '_bf_cache'):
        game._bf_cache = {}
    cache_key = (key, int(max_size[0]), int(max_size[1]))
    surf = game._bf_cache.get(cache_key)
    if surf is not None:
        return surf
    # Reuse portrait path resolver
    path = _first_existing_path([key])
    if not path:
        return None
    try:
        img = pg.image.load(str(path)).convert_alpha()
        iw, ih = img.get_width(), img.get_height()
        if iw <= 0 or ih <= 0:
            return None
        mw, mh = int(max_size[0]), int(max_size[1])
        scale = min(mw / float(iw), mh / float(ih))
        tw, th = max(1, int(iw * scale)), max(1, int(ih * scale))
        out = pg.transform.smoothscale(img, (tw, th)) if hasattr(pg.transform, 'smoothscale') else pg.transform.scale(img, (tw, th))
        game._bf_cache[cache_key] = out
        return out
    except Exception:
        return None

def _draw_battlefield_canvas(surf, game, bf: Rect, hover_side: Optional[str] = None, hover_index: int = -1):
    """Draw the battlefield scene (sky, ground, and unit sprites) into bf rect."""
    # Sky gradient
    sky = pg.Surface((bf.w, bf.h), pg.SRCALPHA)
    top_col = (32,36,48)
    mid_col = (38,42,56)
    for y in range(bf.h):
        t = y / max(1, bf.h)
        r = int(top_col[0]*(1-t) + mid_col[0]*t)
        g = int(top_col[1]*(1-t) + mid_col[1]*t)
        b = int(top_col[2]*(1-t) + mid_col[2]*t)
        pg.draw.line(sky, (r,g,b), (0, y), (bf.w, y))
    surf.blit(sky, (bf.x, bf.y))
    # Ground
    ground_h = int(bf.h * 0.36)
    ground = pg.Rect(bf.x, bf.bottom - ground_h, bf.w, ground_h)
    pg.draw.rect(surf, (46,50,62), ground)
    # Ground stripes/hatching
    for i in range(0, ground_h, 14):
        c = (54,58,72) if (i//14)%2==0 else (50,54,66)
        pg.draw.rect(surf, c, pg.Rect(ground.x, ground.y + i, ground.w, 8))
    # Horizon line
    pg.draw.line(surf, (96,102,124), (bf.x, ground.y), (bf.right, ground.y), 2)

    # Slot layout
    cols, rows = 3, 2
    slot_w = int(bf.w * 0.36)
    left_area = pg.Rect(bf.x + 20, ground.y - int(ground_h*0.65), slot_w, int(ground_h*0.65))
    right_area= pg.Rect(bf.right - 20 - slot_w, left_area.y, slot_w, left_area.h)
    def slot_center(area: Rect, c: int, r: int) -> Tuple[int,int]:
        cx = area.x + int((c + 0.5) * (area.w / cols))
        cy = area.y + int((r + 0.6) * (area.h / rows))
        return cx, cy

    # gather participants based on current combat state
    allies: List[str] = []
    enemies: List[str] = []

    # Resolve a first-existing key from candidate paths, else fallback
    def _pick_key(cands: List[str], fallback: str) -> str:
        p = _first_existing_path(cands)
        if p is not None:
            try:
                # Return as project-relative string
                return str(p.relative_to(ASSETS_DIR))
            except Exception:
                return str(p)
        return fallback

    # Ally: player portrait/sprite + party allies
    try:
        pcands = _player_portrait_candidates(game.player)
    except Exception:
        pcands = []
    allies.append(_pick_key(pcands + ['images/player/player.png'], 'images/player/player.png'))
    # Add party ally portraits
    try:
        for a in (getattr(game, 'party', []) or [])[:5]:
            acands: List[str] = []
            img = getattr(a, 'portrait', None)
            if img: acands.append(str(img))
            # Heuristic fallback by name/slug under images/allies
            try:
                slug = _slugify_name(getattr(a,'name','ally'))
                for sub in ('images/allies','images/npcs','images'):
                    acands.append(f"{sub}/{slug}.png"); acands.append(f"{sub}/{slug}.jpg")
            except Exception:
                pass
            allies.append(_pick_key(acands + ['images/allies/fighter.png'], 'images/allies/fighter.png'))
    except Exception:
        pass

    # Enemies: support multiple current enemies; else single fallback
    cur_list = list(getattr(game, 'current_enemies', []) or [])
    if not cur_list:
        enemy = getattr(game, 'current_enemy', None) or (getattr(game.tile().encounter, 'enemy', None) if game.tile().encounter else None)
        if enemy:
            cur_list = [enemy]
    if cur_list:
        for enemy in cur_list:
            try:
                slug = _slugify_name(enemy.get('name') or enemy.get('id') or 'enemy')
            except Exception:
                slug = 'enemy'
            eid = str(enemy.get('id') or '')
            ecands: List[str] = []
            for k in ('sprite','image','portrait','img'):
                v = enemy.get(k)
                if isinstance(v, str) and v.strip():
                    ecands.append(v.strip())
            for sub in ('images/enemies','images/npcs','images'):
                ecands.append(f"{sub}/{slug}.png"); ecands.append(f"{sub}/{slug}.jpg")
                if eid:
                    ecands.append(f"{sub}/{eid}.png"); ecands.append(f"{sub}/{eid}.jpg")
            enemies.append(_pick_key(ecands, 'images/enemies/default.png'))
    else:
        enemies = list(getattr(game, 'bf_enemies', []) or [])

    # Draw team helper
    def draw_team(area: Rect, items: List[str], flip=False, side_name: str = ''):
        # Slightly increase sprite zoom for better character focus
        SCALE = 2.1
        max_w = int((area.w / cols) * SCALE) - 8
        max_h = int((area.h / rows) * SCALE) - 6
        for idx, key in enumerate(items[:cols*rows]):
            r = idx // cols
            c = idx % cols
            cx, cy = slot_center(area, c, r)
            # Shadow
            sh_w = max(18, int(max_w * 0.55))
            sh_h = max(6, int(max_h * 0.18))
            sh = pg.Surface((sh_w, sh_h), pg.SRCALPHA)
            pg.draw.ellipse(sh, (10,10,12,90), pg.Rect(0,0,sh_w, sh_h))
            surf.blit(sh, (cx - sh_w//2, ground.y - sh_h//2))
            # Sprite
            spr = _load_sprite_cached(game, key, (max_w, max_h))
            if spr is not None:
                img = pg.transform.flip(spr, True, False) if flip else spr
                ix, iy = (cx - img.get_width()//2, ground.y - img.get_height())
                # First draw the sprite
                surf.blit(img, (ix, iy))
                # Then draw the highlight outline on top (so it doesn't get hidden)
                if hover_side and side_name == hover_side and (hover_index < 0 or hover_index == idx):
                    try:
                        if not hasattr(game, '_bf_outline'):
                            game._bf_outline = {}
                        okey = (key, int(img.get_width()), int(img.get_height()), bool(flip))
                        outline_pts = game._bf_outline.get(okey)
                        if outline_pts is None:
                            m = pg.mask.from_surface(img)
                            outline_pts = m.outline()
                            if not outline_pts:
                                outline_pts = [(0,0),(img.get_width(),0),(img.get_width(),img.get_height()),(0,img.get_height())]
                            game._bf_outline[okey] = outline_pts
                        pts = [(ix + p[0], iy + p[1]) for p in outline_pts]
                        # Outer accent stroke
                        try:
                            pg.draw.lines(surf, COL_PLAYER, True, pts, 3)
                        except Exception:
                            pg.draw.polygon(surf, COL_PLAYER, pts, 3)
                        # Inner dark stroke for readability
                        try:
                            pg.draw.lines(surf, (20,22,28), True, pts, 1)
                        except Exception:
                            pass
                    except Exception:
                        glow = pg.Rect(ix-4, iy-4, img.get_width()+8, img.get_height()+8)
                        pg.draw.rect(surf, COL_PLAYER, glow, 3, border_radius=8)
            # Slot indicator
            pg.draw.circle(surf, (92,98,120), (cx, ground.y), 3)

    draw_team(left_area, allies, flip=False, side_name='allies')
    draw_team(right_area, enemies, flip=True, side_name='enemies')
def draw_battlefield_overlay(surf, game):
    """Simple battlefield view: a center arena with ally/enemy slots and sprites.

    Returns list of Buttons for interaction (Back only for now).
    """
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)

    # Map view area (between side panels)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)

    # Dim background over the map area
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10, 10, 14, 160))
    surf.blit(dim, (view_rect.x, view_rect.y))

    # Battlefield rect inside view - widen nearly to sidebars
    margin = 10
    bf = pg.Rect(view_rect.x + margin, view_rect.y + margin, view_rect.w - 2*margin, view_rect.h - 2*margin)
    # Sky gradient
    sky = pg.Surface((bf.w, bf.h), pg.SRCALPHA)
    top_col = (32,36,48)
    mid_col = (38,42,56)
    for y in range(bf.h):
        t = y / max(1, bf.h)
        r = int(top_col[0]*(1-t) + mid_col[0]*t)
        g = int(top_col[1]*(1-t) + mid_col[1]*t)
        b = int(top_col[2]*(1-t) + mid_col[2]*t)
        pg.draw.line(sky, (r,g,b), (0, y), (bf.w, y))
    surf.blit(sky, (bf.x, bf.y))
    # Ground
    ground_h = int(bf.h * 0.36)
    ground = pg.Rect(bf.x, bf.bottom - ground_h, bf.w, ground_h)
    pg.draw.rect(surf, (46,50,62), ground)
    # Ground stripes
    for i in range(0, ground_h, 14):
        c = (54,58,72) if (i//14)%2==0 else (50,54,66)
        pg.draw.rect(surf, c, pg.Rect(ground.x, ground.y + i, ground.w, 8))
    # Horizon line
    pg.draw.line(surf, (96,102,124), (bf.x, ground.y), (bf.right, ground.y), 2)

    # Slots (3x2 per side)
    cols, rows = 3, 2
    slot_w = int(bf.w * 0.36)
    left_area = pg.Rect(bf.x + 20, ground.y - int(ground_h*0.65), slot_w, int(ground_h*0.65))
    right_area= pg.Rect(bf.right - 20 - slot_w, left_area.y, slot_w, left_area.h)
    def slot_center(area: Rect, c: int, r: int) -> Tuple[int,int]:
        cx = area.x + int((c + 0.5) * (area.w / cols))
        cy = area.y + int((r + 0.6) * (area.h / rows))
        return cx, cy

    # Ensure demo participants
    _ensure_battlefield_demo(game)
    allies = list(getattr(game, 'bf_allies', []) or [])
    enemies = list(getattr(game, 'bf_enemies', []) or [])

    # Draw shadows and sprites
    def draw_team(area: Rect, items: List[str], flip=False):
        SCALE = 1.9
        max_w = int((area.w / cols) * SCALE) - 8
        max_h = int((area.h / rows) * SCALE) - 6
        for idx, key in enumerate(items[:cols*rows]):
            r = idx // cols
            c = idx % cols
            cx, cy = slot_center(area, c, r)
            # Shadow ellipse on ground
            sh_w = max(18, int(max_w * 0.55))
            sh_h = max(6, int(max_h * 0.18))
            sh = pg.Surface((sh_w, sh_h), pg.SRCALPHA)
            pg.draw.ellipse(sh, (10,10,12,90), pg.Rect(0,0,sh_w, sh_h))
            surf.blit(sh, (cx - sh_w//2, ground.y - sh_h//2))
            # Sprite
            spr = _load_sprite_cached(game, key, (max_w, max_h))
            if spr is not None:
                img = pg.transform.flip(spr, True, False) if flip else spr
                surf.blit(img, (cx - img.get_width()//2, ground.y - img.get_height()))
            # Slot indicator (optional subtle)
            pg.draw.circle(surf, (92,98,120), (cx, ground.y), 3)

    draw_team(left_area, allies, flip=False)
    draw_team(right_area, enemies, flip=True)

    # Frame
    pg.draw.rect(surf, (96,102,124), bf, 2, border_radius=10)

    # Header + Back button
    title = pg.font.Font(None, 30).render("Battlefield", True, (235,235,245))
    surf.blit(title, (bf.x + 12, bf.y + 8))
    buttons.append(Button((bf.right - 112, bf.y + 8, 100, 28), "Back", lambda: setattr(game,'mode','explore')))

    return buttons

def draw_equip_overlay(surf, game):
    """Centered equipment screen with silhouette and slot squares.

    Keeps the right sidebar intact. Returns list of Button objects.
    """
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)

    # Map view area
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)

    # Modal
    modal_w = max(540, int(view_w * 0.86))
    modal_h = max(380, int(view_h * 0.86))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)

    # Dim background
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10, 10, 14, 140))
    surf.blit(dim, (view_rect.x, view_rect.y))

    # Panel
    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (96,102,124), modal, 2, border_radius=10)
    pg.draw.rect(surf, (56,60,76), modal.inflate(-8, -8), 1, border_radius=8)

    # Header + target selector
    title_font = pg.font.Font(None, 30)
    try:
        total_targets = 1 + len(getattr(game, 'party', []) or [])
        if not hasattr(game, 'equip_target_idx'):
            game.equip_target_idx = 0
        game.equip_target_idx = max(0, min(game.equip_target_idx, total_targets-1))
    except Exception:
        total_targets = 1; game.equip_target_idx = 0
    def _equip_target():
        return game.player if game.equip_target_idx == 0 else (game.party[game.equip_target_idx-1])
    target = _equip_target()
    title = f"Equipment - {getattr(target, 'name', 'Unknown')}"
    surf.blit(title_font.render(title, True, (235,235,245)), (modal.x + 16, modal.y + 12))
    def _prev(): setattr(game, 'equip_target_idx', (game.equip_target_idx - 1) % total_targets)
    def _next(): setattr(game, 'equip_target_idx', (game.equip_target_idx + 1) % total_targets)
    buttons.append(Button((modal.x + 360, modal.y + 10, 28, 28), "<", lambda: _prev()))
    buttons.append(Button((modal.x + 392, modal.y + 10, 28, 28), ">", lambda: _next()))
    buttons.append(Button((modal.right - 230, modal.y + 10, 110, 28), "Inventory", lambda: setattr(game,'mode','inventory')))
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: game.close_overlay()))

    # Layout left silhouette, right list
    pad = 16
    content = modal.inflate(-2*pad, -2*pad)
    sil_area = pg.Rect(content.x, content.y + 36, int(content.w * 0.54), content.h - 52)
    list_area = pg.Rect(content.x + sil_area.w + 12, content.y + 36, content.w - sil_area.w - 12, content.h - 52)
    for r in (sil_area, list_area):
        pg.draw.rect(surf, (30,32,42), r, border_radius=8)
        pg.draw.rect(surf, (70,74,92), r, 1, border_radius=8)

    # Try to draw the actual sprite; fall back to silhouette image/shapes
    sil_img = None
    try:
        candidates = []
        try:
            if getattr(target, 'portrait', None):
                candidates.append(os.path.join(ROOT, 'assets', str(getattr(target, 'portrait'))))
        except Exception:
            pass
        candidates += [
            os.path.join(ROOT, 'assets', 'images', 'player', 'player.png'),
            os.path.join(ROOT, 'assets', 'images', 'ui', 'silhouette.png'),
        ]
        for img_path in candidates:
            if os.path.exists(img_path):
                img = pg.image.load(img_path).convert_alpha()
                iw, ih = img.get_size()
                # Pixel-crisp scaling:
                # - If upscaling: use integer multiple (nearest-neighbor)
                # - If downscaling: divide by an integer factor to keep pixels sharp
                pad_w, pad_h = max(1, sil_area.w-40), max(1, sil_area.h-40)
                if iw <= pad_w and ih <= pad_h:
                    # Upscale by integer factor
                    k = max(1, min(pad_w // iw, pad_h // ih))
                    new_w, new_h = iw * k, ih * k
                else:
                    # Downscale by integer divisor
                    import math as _math
                    denom = max(2, int(_math.ceil(max(iw / pad_w, ih / pad_h))))
                    new_w, new_h = max(1, iw // denom), max(1, ih // denom)
                new_size = (int(new_w), int(new_h))
                sil_img = pg.transform.scale(img, new_size)
                break
        if sil_img is not None:
            surf.blit(sil_img, sil_img.get_rect(center=sil_area.center))
    except Exception:
        sil_img = None

    # If no image, draw a simple silhouette shape
    if sil_img is None:
        cx, cy = sil_area.center
        # Head
        pg.draw.circle(surf, (38,40,52), (cx, sil_area.y + int(sil_area.h*0.12)), max(14, sil_area.w//12))
        # Torso
        torso = pg.Rect(0,0, int(sil_area.w*0.22), int(sil_area.h*0.34))
        torso.center = (cx, sil_area.y + int(sil_area.h*0.42))
        pg.draw.rect(surf, (38,40,52), torso, border_radius=12)
        # Legs
        legs = pg.Rect(0,0, int(sil_area.w*0.18), int(sil_area.h*0.32))
        legs.center = (cx, sil_area.y + int(sil_area.h*0.70))
        pg.draw.rect(surf, (38,40,52), legs, border_radius=12)

    # Slot positions (normalized in sil_area)
    slot_sz = max(56, min(90, sil_area.w // 5))
    def at(nx: float, ny: float) -> "pygame.Rect":
        px = sil_area.x + int(nx * sil_area.w) - slot_sz//2
        py = sil_area.y + int(ny * sil_area.h) - slot_sz//2
        return pg.Rect(px, py, slot_sz, slot_sz)

    SLOT_POS = {
        'head':         (0.50, 0.12),
        # Necklace aligned to the gap between left and center columns
        'neck':         (0.34, 0.30),
        'back':         (0.60, 0.30),
        'torso':        (0.50, 0.42),
        # Move hands down to ring row; move bracelet to former gloves position; add charm at former bracelet position
        'hands':        (0.82, 0.54),
        'ring':         (0.18, 0.54),
        # Bracelet aligned to the gap between center and right columns
        'bracelet':     (0.66, 0.42),
        'charm':        (0.18, 0.42),
        # Legs moved up slightly; feet added below
        'legs':         (0.50, 0.60),
        'feet':         (0.50, 0.72),
        # Move both weapon slots up slightly
        'weapon_main':  (0.18, 0.76),
        'weapon_off':   (0.82, 0.76),
    }

    # Optional slot position overrides from data/ui/equip_slots.json
    try:
        cfg_path = UI_DIR / 'equip_slots.json'
        cfg = load_json(str(cfg_path), {}) if cfg_path.exists() else {}
        overrides = cfg.get('slot_positions') if isinstance(cfg, dict) else None
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                try:
                    nx, ny = float(v[0]), float(v[1])
                    # clamp to [0,1]
                    nx = 0.0 if nx < 0 else (1.0 if nx > 1 else nx)
                    ny = 0.0 if ny < 0 else (1.0 if ny > 1 else ny)
                    SLOT_POS[k] = (nx, ny)
                except Exception:
                    pass
    except Exception:
        pass

    # Helper to draw a small icon for an item
    def type_color(it: dict) -> Tuple[int,int,int]:
        t = item_major_type(it)
        return {
            'weapon': (140,120,220),
            'armour': (120,170,220), 'armor': (120,170,220),
            'clothing': (120,170,220),
            'accessory': (200,160,220), 'accessories': (200,160,220),
            'consumable': (180,220,140), 'consumables': (180,220,140),
            'material': (220,180,120), 'materials': (220,180,120),
            'trinket': (220,200,150), 'trinkets': (220,200,150),
            'quest': (220,150,150), 'quest_item': (220,150,150), 'quest_items': (220,150,150),
        }.get(t, (180,190,210))

    # Draw slots
    mx, my = pg.mouse.get_pos()
    sel_slot = getattr(game, 'equip_sel_slot', None)
    for key, (nx, ny) in SLOT_POS.items():
        r = at(nx, ny)
        eq = getattr(target, 'equipped_gear', {}).get(key)
        hov = r.collidepoint(mx, my)
        _rar = str(((eq or {}).get('rarity') or '')).lower() if eq else ''
        _rc = RARITY_COLORS.get(_rar)
        base = (44,48,62) if (hov or key == sel_slot) else (38,40,52)
        pg.draw.rect(surf, base, r, border_radius=8)
        border_col = _rc if _rc else ((96,102,124) if (hov or key == sel_slot) else (70,74,92))
        pg.draw.rect(surf, border_col, r, 2, border_radius=8)
        # Slot label
        lab = SLOT_LABELS.get(key, key.title())
        f = pg.font.Font(None, 18)
        ls_col = _rc if _rc else (210,210,220)
        ls = f.render(lab, True, ls_col)
        surf.blit(ls, (r.centerx - ls.get_width()//2, r.bottom + 4))
        # If equipped, draw small icon glyph
        if eq:
            tag = r.inflate(-10, -10)
            tag.h = max(8, slot_sz // 6)
            _rar = str((eq.get('rarity') or '')).lower()
            _rc = RARITY_COLORS.get(_rar)
            pg.draw.rect(surf, _rc if _rc else type_color(eq), (tag.x, tag.y, tag.w, tag.h), border_radius=4)
            glyph = (str(item_type(eq)) or '?')[:1].upper()
            gfont = pg.font.Font(None, max(18, slot_sz // 2))
            gs = gfont.render(glyph, True, (235,235,245))
            surf.blit(gs, (r.centerx - gs.get_width()//2, r.centery - gs.get_height()//2))
        # Click handler for selecting slot
        def make_sel(k=key):
            return lambda k=k: setattr(game, 'equip_sel_slot', k)
        buttons.append(Button(r, "", make_sel(key), draw_bg=False))

    # Right list: items that can go to selected slot
    fnt = pg.font.Font(None, 22)
    # Stats header for target
    stats_font = pg.font.Font(None, 20)
    draw_text(surf, f"HP: {getattr(target,'hp',0)}/{getattr(target,'max_hp',0)}   ATK: {getattr(target,'atk',(0,0))[0]}-{getattr(target,'atk',(0,0))[1]}", (list_area.x + 12, list_area.y - 26), font=stats_font)
    header = f"Select for: {SLOT_LABELS.get(sel_slot, '-')}" if sel_slot else "Select a slot"
    draw_text(surf, header, (list_area.x + 12, list_area.y - 4), font=fnt)

    pager_y = list_area.bottom - 34
    if sel_slot:
        # Filter items
        pool = [it for it in game.player.inventory if (slot_accepts(sel_slot, it) or (normalize_slot(sel_slot) in ('weapon_main','weapon_off') and item_type(it).lower() == 'weapon'))]
        # List rows
        row_h = 28
        per_page = max(6, (list_area.h // row_h) - 2)
        # Maintain a separate page selection for equip list
        if not hasattr(game, 'equip_page'): game.equip_page = 0
        total = len(pool)
        pages = max(1, (total + per_page - 1)//per_page)
        game.equip_page = max(0, min(game.equip_page, pages-1))
        start = game.equip_page * per_page
        items = pool[start:start+per_page]
        y = list_area.y + 8
        for i, it in enumerate(items):
            r = pg.Rect(list_area.x + 8, y + i*row_h, list_area.w - 16, row_h - 4)
            pg.draw.rect(surf, (34,36,46), r, border_radius=6)
            pg.draw.rect(surf, (90,94,112), r, 1, border_radius=6)
            label = f"{item_name(it)}  [{item_type(it)}/{item_subtype(it)}]"
            _rar = str((it.get('rarity') or '')).lower()
            _rc = RARITY_COLORS.get(_rar)
            # optional left rarity stripe for clarity
            try:
                stripe = r.inflate(0, -8)
                stripe.w = 4
                pg.draw.rect(surf, _rc if _rc else (90,94,112), stripe, border_radius=3)
            except Exception:
                pass
            draw_text(surf, label, (r.x+12, r.y+6), color=_rc or (220,220,230))
            def make_equip(it=it, slot=sel_slot):
                return lambda it=it, slot=slot: game.equip_item_to_slot(slot, it)
            buttons.append(Button(r, "", make_equip(), draw_bg=False))

        # Pager and Unequip
        buttons.append(Button((list_area.x + 8, pager_y, 110, 26), "Prev Page", lambda: setattr(game,'equip_page', max(0, game.equip_page-1))))
        buttons.append(Button((list_area.x + 8 + 120, pager_y, 110, 26), "Next Page", lambda: setattr(game,'equip_page', min(pages-1, game.equip_page+1))))
        # Unequip if there is an item in slot
        if getattr(target, 'equipped_gear', {}).get(sel_slot):
            buttons.append(Button((list_area.right - 130, pager_y, 110, 26), "Unequip", lambda slot=sel_slot: game.unequip_slot(slot)))

    if getattr(game, 'equip_target_idx', 0) > 0 and isinstance(target, Ally):
        buttons.append(Button((list_area.right - 250, pager_y, 110, 26), "Dismiss", lambda: game.dismiss_selected_ally()))

    return buttons

def _list_save_slots() -> List[Tuple[int, Optional[Dict[str, Any]]]]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    slots: List[Tuple[int, Optional[Dict[str, Any]]]] = []
    for i in range(1, 7):
        path = SAVE_DIR / f"slot{i}.json"
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    slots.append((i, json.load(f)))
            except Exception:
                slots.append((i, None))
        else:
            slots.append((i, None))
    return slots

def _render_slot_card(surf, r, slot_idx: int, data: Optional[Dict[str, Any]]):
    pg.draw.rect(surf, (34,36,46), r, border_radius=8)
    pg.draw.rect(surf, (90,94,112), r, 1, border_radius=8)
    f_title = pg.font.Font(None, 24)
    f_body  = pg.font.Font(None, 18)
    title = f"Slot {slot_idx}"
    surf.blit(f_title.render(title, True, (220,220,235)), (r.x+10, r.y+8))
    if data and isinstance(data, dict):
        ts = str(data.get('timestamp',''))
        mp = str(data.get('map_name') or data.get('map_id') or '')
        pos = data.get('pos') or [0,0]
        p   = data.get('player') or {}
        name = str(p.get('name','Adventurer'))
        lvl = int(p.get('level', 1)) if str(p.get('level', '1')).isdigit() else 1
        hp = f"{int(p.get('hp',0))}/{int(p.get('max_hp',0))}"
        inv = len(p.get('inventory') or [])
        pt_s = int(data.get('playtime_s') or 0)
        h = pt_s // 3600; m = (pt_s % 3600) // 60; s = pt_s % 60
        pt_fmt = f"{h:02d}:{m:02d}:{s:02d}"
        # left column text
        y = r.y + 34
        draw_text(surf, f"Saved: {ts}", (r.x+10, y), font=f_body); y += 18
        draw_text(surf, f"Map: {mp}", (r.x+10, y), font=f_body); y += 18
        draw_text(surf, f"Pos: ({int(pos[0])},{int(pos[1])})", (r.x+10, y), font=f_body); y += 18
        draw_text(surf, f"Player: {name}  Lvl: {lvl}  HP: {hp}", (r.x+10, y), font=f_body); y += 18
        draw_text(surf, f"Inventory: {inv}   Playtime: {pt_fmt}", (r.x+10, y), font=f_body)
        # mini map preview on right side
        try:
            preview_w = min(120, r.w // 3)
            mini = pg.Rect(r.right - preview_w - 8, r.y + 8, preview_w, r.h - 16)
            pg.draw.rect(surf, (26,28,36), mini, border_radius=6)
            pg.draw.rect(surf, (80,84,100), mini, 1, border_radius=6)
            scene = load_scene_by_name('map', mp)
            runtime = scene_to_runtime(scene)
            W, H = int(runtime.get('width',12)), int(runtime.get('height',8))
            walk = runtime.get('walkable') or [[True]*W for _ in range(H)]
            cell = max(2, min(8, (mini.w-8) // max(1, W)))
            offx = mini.x + (mini.w - (cell*W))//2
            offy = mini.y + (mini.h - (cell*H))//2
            for yy in range(H):
                for xx in range(W):
                    clr = (52,56,70) if walk[yy][xx] else (28,30,38)
                    pg.draw.rect(surf, clr, (offx+xx*cell, offy+yy*cell, cell-1, cell-1))
            try:
                px, py = int(pos[0]), int(pos[1])
                if 0 <= px < W and 0 <= py < H:
                    pg.draw.rect(surf, (200,220,120), (offx+px*cell, offy+py*cell, cell-1, cell-1))
            except Exception:
                pass
        except Exception:
            pass
    else:
        draw_text(surf, "Empty", (r.x+10, r.y+34), font=f_body)

def draw_save_overlay(surf, game):
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)
    # Dim
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10,10,14,140)); surf.blit(dim, (view_rect.x, view_rect.y))
    # Modal
    modal_w = max(540, int(view_w * 0.86))
    modal_h = max(380, int(view_h * 0.86))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)
    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (96,102,124), modal, 2, border_radius=10)
    title_font = pg.font.Font(None, 30)
    surf.blit(title_font.render("Save Game", True, (235,235,245)), (modal.x + 16, modal.y + 12))
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: game.close_overlay()))

    # Slots grid 2x3
    pad = 16
    content = modal.inflate(-2*pad, -2*pad)
    cols, rows = 2, 3
    cell_w = (content.w - (cols + 1) * pad) // cols
    cell_h = (content.h - (rows + 1) * pad) // rows
    slots = _list_save_slots()
    idx = 0
    for r_i in range(rows):
        for c_i in range(cols):
            idx += 1
            x = content.x + pad + c_i * (cell_w + pad)
            y = content.y + pad + r_i * (cell_h + pad)
            rect = pg.Rect(x, y, cell_w, cell_h)
            data = slots[idx-1][1]
            _render_slot_card(surf, rect, idx, data)
            buttons.append(Button(rect, "", lambda slot=idx: game.save_to_slot(slot), draw_bg=False))
    return buttons

def draw_load_overlay(surf, game):
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)
    # Dim
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10,10,14,140)); surf.blit(dim, (view_rect.x, view_rect.y))
    # Modal
    modal_w = max(540, int(view_w * 0.86))
    modal_h = max(380, int(view_h * 0.86))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)
    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (96,102,124), modal, 2, border_radius=10)
    title_font = pg.font.Font(None, 30)
    surf.blit(title_font.render("Load Game", True, (235,235,245)), (modal.x + 16, modal.y + 12))
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: game.close_overlay()))

    # Slots grid 2x3
    pad = 16
    content = modal.inflate(-2*pad, -2*pad)
    cols, rows = 2, 3
    cell_w = (content.w - (cols + 1) * pad) // cols
    cell_h = (content.h - (rows + 1) * pad) // rows
    slots = _list_save_slots()
    idx = 0
    for r_i in range(rows):
        for c_i in range(cols):
            idx += 1
            x = content.x + pad + c_i * (cell_w + pad)
            y = content.y + pad + r_i * (cell_h + pad)
            rect = pg.Rect(x, y, cell_w, cell_h)
            data = slots[idx-1][1]
            _render_slot_card(surf, rect, idx, data)
            buttons.append(Button(rect, "", lambda slot=idx: game.load_from_slot(slot), draw_bg=False))
    return buttons

def draw_database_overlay(surf, game):
    """Database browser: view Items, NPCs, Races, Traits, Enchants, Magic, Status, Classes.

    Centered modal over the map area; returns list of Buttons for click handling.
    """
    buttons: List[Button] = []
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)

    # Map view area (between left and right panels)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)

    # Dim background
    dim = pg.Surface((view_rect.w, view_rect.h), pg.SRCALPHA)
    dim.fill((10, 10, 14, 140))
    surf.blit(dim, (view_rect.x, view_rect.y))

    # Modal rect
    inset = 24
    modal_w = max(640, int(view_w * 0.90))
    modal_h = max(420, int(view_h * 0.90))
    modal_x = view_rect.x + (view_w - modal_w)//2
    modal_y = view_rect.y + (view_h - modal_h)//2
    modal = pg.Rect(modal_x, modal_y, modal_w, modal_h)

    # Panel
    pg.draw.rect(surf, (24,26,34), modal, border_radius=10)
    pg.draw.rect(surf, (96,102,124), modal, 2, border_radius=10)
    pg.draw.rect(surf, (56,60,76), modal.inflate(-8, -8), 1, border_radius=8)

    # Header with tabs
    if not hasattr(game, '_db_font_30'): game._db_font_30 = pg.font.Font(None, 30)
    if not hasattr(game, '_db_font_26'): game._db_font_26 = pg.font.Font(None, 26)
    if not hasattr(game, '_db_font_22'): game._db_font_22 = pg.font.Font(None, 22)
    if not hasattr(game, '_db_font_20'): game._db_font_20 = pg.font.Font(None, 20)
    title_font = game._db_font_30
    surf.blit(title_font.render("Database", True, (235,235,245)), (modal.x + 16, modal.y + 12))
    def _db_back():
        try:
            if hasattr(game, 'close_overlay') and callable(getattr(game, 'close_overlay')):
                game.close_overlay()
            else:
                # In main menu database view, signal exit via mode='explore'
                setattr(game, 'mode', 'explore')
        except Exception:
            try:
                setattr(game, 'mode', 'explore')
            except Exception:
                pass
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", _db_back))

    # Initialize state on first open
    if not hasattr(game, 'db_cat'): game.db_cat = 'Items'
    if not hasattr(game, 'db_sub'): game.db_sub = 'All'
    if not hasattr(game, 'db_page'): game.db_page = 0
    if not hasattr(game, 'db_sel'): game.db_sel = None
    # Sorting state for database view
    if not hasattr(game, 'db_sort_key'): game.db_sort_key = 'Name'
    if not hasattr(game, 'db_sort_desc'): game.db_sort_desc = False  # False=A-Z, True=Z-A
    if not hasattr(game, 'db_sort_open'): game.db_sort_open = False
    if not hasattr(game, 'db_cache'):
        # Build cache of datasets
        def _safe(rel, key):
            return safe_load_doc(rel, key)
        # Items by subcategory
        items_all = gather_items()
        items = {
            'All': items_all,
            'Weapons':      _safe(os.path.join('items','weapons.json'), 'items'),
            'Armour':       _safe(os.path.join('items','armour.json'), 'items'),
            'Accessories':  _safe(os.path.join('items','accessories.json'), 'items'),
            'Clothing':     _safe(os.path.join('items','clothing.json'), 'items'),
            'Consumables':  _safe(os.path.join('items','consumables.json'), 'items'),
            'Materials':    _safe(os.path.join('items','materials.json'), 'items'),
            'Quest Items':  _safe(os.path.join('items','quest_items.json'), 'items'),
            'Trinkets':     _safe(os.path.join('items','trinkets.json'), 'items'),
        }
        # NPCs by subcategory
        npcs_all = gather_npcs()
        villains_list: List[Dict] = []
        try:
            villains_list.extend(_safe(os.path.join('npcs','villains.json'), 'npcs'))
        except Exception:
            pass
        try:
            base_dir = DATA_DIR / 'npcs'
            for subdir in ['vilains', 'villains']:
                p = base_dir / subdir
                if p.exists() and p.is_dir():
                    for fn in os.listdir(p):
                        if fn.lower().endswith('.json'):
                            rel = os.path.join('npcs', subdir, fn)
                            villains_list.extend(_safe(rel, 'npcs'))
        except Exception:
            pass
        npcs = {
            'All':         npcs_all,
            'Allies':      _safe(os.path.join('npcs','allies.json'), 'npcs'),
            'Animals':     _safe(os.path.join('npcs','animals.json'), 'npcs'),
            'Citizens':    _safe(os.path.join('npcs','citizens.json'), 'npcs'),
            'Enemies':     _safe(os.path.join('npcs','enemies.json'), 'npcs'),
            'Aberrations': _safe(os.path.join('npcs','calamities.json'), 'npcs'),
            'Villains':    villains_list,
        }
        game.db_cache = {
            'Items': items,
            'Armour Sets': gather_armour_sets(),
            'NPCs': npcs,
            'Races': list(getattr(game, 'races', []) or []),
            'Traits': list(getattr(game, 'traits', []) or []),
            'Enchants': list(getattr(game, 'enchants', []) or []),
            'Magic': list(getattr(game, 'magic', []) or []),
            'Status': list(getattr(game, 'status', []) or []),
            'Classes': list(getattr(game, 'classes', []) or []),
            'Curses': list(getattr(game, 'curses', []) or []),
        }

    # Tabs
    tab_font = game._db_font_22
    tab_y = modal.y + 50
    tab_x = modal.x + 16
    tab_h = 28
    tab_pad = 10
    tabs = ['Items','Armour Sets','NPCs','Races','Traits','Enchants','Magic','Status','Classes','Curses']
    for name in tabs:
        tw = max(90, tab_font.size(name)[0] + 20)
        r = pg.Rect(tab_x, tab_y, tw, tab_h)
        sel = (game.db_cat == name)
        pg.draw.rect(surf, (50,54,68) if sel else (34,36,46), r, border_radius=8)
        pg.draw.rect(surf, (110,110,130), r, 2, border_radius=8)
        surf.blit(tab_font.render(name, True, (235,235,245)), (r.x + 10, r.y + 5))
        def make_tab(n=name):
            def _cb(n=n):
                setattr(game,'db_cat', n)
                setattr(game,'db_page', 0)
                setattr(game,'db_sel', None)
                # Reset filters to defaults when switching tabs
                try:
                    setattr(game,'db_sub', 'All')
                except Exception:
                    pass
                try:
                    setattr(game,'db_query', '')
                    setattr(game,'db_name_only', False)
                    setattr(game,'db_starts_with', False)
                    setattr(game,'db_filter_focus', False)
                    setattr(game,'db_filters_open', False)
                    setattr(game,'db_sort_open', False)
                except Exception:
                    pass
                try:
                    # Default sort by Name ascending
                    setattr(game,'db_sort_key', 'Name')
                    setattr(game,'db_sort_desc', False)
                except Exception:
                    pass
                try:
                    # Clear field selection for the new category
                    if isinstance(getattr(game, 'db_fields_sel', {}), dict):
                        game.db_fields_sel[n] = []
                except Exception:
                    pass
            return _cb
        buttons.append(Button(r, "", make_tab(name), draw_bg=False))
        tab_x += tw + tab_pad

    # Content areas
    pad = 16
    content = modal.inflate(-2*pad, -2*pad)
    content.y = tab_y + tab_h + 12
    content.h = modal.bottom - pad - content.y
    list_area = pg.Rect(content.x, content.y + 36, int(content.w * 0.48), content.h - 36)
    det_area  = pg.Rect(content.x + list_area.w + 12, content.y, content.w - list_area.w - 12, content.h)
    for r in (pg.Rect(content.x, content.y, content.w, 28), list_area, det_area):
        if r is list_area or r is det_area:
            pg.draw.rect(surf, (30,32,42), r, border_radius=8)
            pg.draw.rect(surf, (70,74,92), r, 1, border_radius=8)

    # Subcategory chips for Items/NPCs
    chip_font = game._db_font_20
    chip_y = content.y
    chip_x = content.x + 6
    chips = []
    if game.db_cat == 'Items':
        chips = ['All','Weapons','Armour','Accessories','Clothing','Consumables','Materials','Quest Items','Trinkets']
    elif game.db_cat == 'NPCs':
        chips = ['All','Allies','Animals','Citizens','Enemies','Aberrations','Villains']
    if chips:
        for ch in chips:
            cw = max(80, chip_font.size(ch)[0] + 18)
            r = pg.Rect(chip_x, chip_y, cw, 26)
            sel = (game.db_sub == ch)
            pg.draw.rect(surf, (48,52,68) if sel else (36,38,48), r, border_radius=8)
            pg.draw.rect(surf, (96,102,124), r, 1, border_radius=8)
            surf.blit(chip_font.render(ch, True, (230,230,240)), (r.x + 8, r.y + 4))
            def make_chip(c=ch):
                return lambda c=c: (setattr(game,'db_sub', c), setattr(game,'db_page',0), setattr(game,'db_sel', None))
            buttons.append(Button(r, "", make_chip(ch), draw_bg=False))
            chip_x += cw + 8
    else:
        # Title for non-chip categories
        surf.blit(pg.font.Font(None, 22).render(game.db_cat, True, (220,220,235)), (content.x + 6, content.y + 4))

    # Filter UI state
    if not hasattr(game, 'db_query'): game.db_query = ''
    if not hasattr(game, 'db_name_only'): game.db_name_only = False
    if not hasattr(game, 'db_starts_with'): game.db_starts_with = False
    if not hasattr(game, 'db_filter_focus'): game.db_filter_focus = False
    if not hasattr(game, 'db_filters_open'): game.db_filters_open = False
    if not hasattr(game, 'db_fields_sel'): game.db_fields_sel = {}

    # Resolve dataset (sorted view)
    entries: List[Dict] = []
    cat = game.db_cat
    sub = game.db_sub if (cat in ('Items','NPCs')) else None
    # Select base entries from cache
    if cat in ('Items','NPCs'):
        data_map: Dict[str, List[Dict]] = game.db_cache.get(cat, {}) or {}
        base = list(data_map.get(sub or 'All', []))
    else:
        base = list(game.db_cache.get(cat, []) or [])

    # Sort configuration
    sort_key = getattr(game, 'db_sort_key', 'Name') or 'Name'
    desc = bool(getattr(game, 'db_sort_desc', False))

    def _safe_str(x: Any) -> str:
        try:
            return str(x or '')
        except Exception:
            return ''

    def _sort_val_items(obj: Dict) -> tuple:
        if sort_key == 'Type':
            slot_key = ''
            try:
                eq = obj.get('equip_slots') or []
                if isinstance(eq, list) and eq:
                    slot_key = normalize_slot(str(eq[0]))
                else:
                    slot_key = normalize_slot(str(obj.get('slot') or item_subtype(obj) or ''))
                if str(item_major_type(obj)).lower() == 'weapon':
                    slot_key = 'weapon'
            except Exception:
                slot_key = ''
            return (_safe_str(slot_key).lower(), _safe_str(item_name(obj)).lower())
        if sort_key == 'Rarity':
            rr = {'common':0,'uncommon':1,'rare':2,'exotic':3,'legendary':4,'mythic':5}
            try:
                r = rr.get(_safe_str(obj.get('rarity')).lower(), -1)
            except Exception:
                r = -1
            return (r, _safe_str(item_name(obj)).lower())
        # default Name
        return (_safe_str(item_name(obj)).lower(), _safe_str(obj.get('id')).lower())

    def _sort_val_npcs(obj: Dict) -> tuple:
        if sort_key == 'Race':
            return (_safe_str(obj.get('race')).lower(), _safe_str(obj.get('name') or obj.get('id')).lower())
        if sort_key == 'Sex':
            return (_safe_str(obj.get('sex')).lower(), _safe_str(obj.get('name') or obj.get('id')).lower())
        if sort_key == 'Type':
            return (_safe_str(obj.get('type')).lower(), _safe_str(obj.get('name') or obj.get('id')).lower())
        # default Name
        return (_safe_str(obj.get('name') or obj.get('id')).lower(), _safe_str(obj.get('id')).lower())

    def _sort_val_other(obj: Any) -> tuple:
        if isinstance(obj, dict):
            return (_safe_str(obj.get('name') or obj.get('id')).lower(), _safe_str(obj.get('id')).lower())
        s = _safe_str(obj).lower()
        return (s, s)

    def _sort_val_sets(obj: Dict) -> tuple:
        if sort_key == 'Pieces':
            try:
                cnt = int(obj.get('count') or len(obj.get('pieces') or []))
            except Exception:
                cnt = 0
            return (cnt, _safe_str(obj.get('name') or obj.get('id')).lower())
        if sort_key == 'Type':
            try:
                slots = sorted([_safe_str(s).lower() for s in (obj.get('slots') or [])])
                slot0 = slots[0] if slots else ''
            except Exception:
                slot0 = ''
            return (slot0, _safe_str(obj.get('name') or obj.get('id')).lower())
        if sort_key == 'Rarity':
            rr = {'common':0,'uncommon':1,'rare':2,'exotic':3,'legendary':4,'mythic':5}
            try:
                r = rr.get(_safe_str((obj.get('rarity') or '')).lower(), -1)
            except Exception:
                r = -1
            return (r, _safe_str(obj.get('name') or obj.get('id')).lower())
        return (_safe_str(obj.get('name') or obj.get('id')).lower(), _safe_str(obj.get('id')).lower())

    try:
        if cat == 'Items':
            entries = sorted(base, key=_sort_val_items, reverse=desc)
        elif cat == 'NPCs':
            entries = sorted(base, key=_sort_val_npcs, reverse=desc)
        elif cat == 'Armour Sets':
            entries = sorted(base, key=_sort_val_sets, reverse=desc)
        else:
            entries = sorted(base, key=_sort_val_other, reverse=desc)
    except Exception:
        entries = base

    # Apply free-text filter to entries to produce filtered list for current view
    def _entry_name(obj: Any) -> str:
        try:
            if isinstance(obj, dict):
                return str(obj.get('name') or obj.get('id') or '')
            return str(obj or '')
        except Exception:
            return ''

    def _flatten(obj: Any) -> str:
        # Build a lowercase haystack of keys and values across object
        parts: List[str] = []
        try:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    try:
                        if isinstance(k, str):
                            parts.append(k)
                    except Exception:
                        pass
                    if isinstance(v, dict):
                        for v2 in v.values():
                            if isinstance(v2, (str, int, float)):
                                parts.append(str(v2))
                    elif isinstance(v, list):
                        for v2 in v:
                            if isinstance(v2, (str, int, float)):
                                parts.append(str(v2))
                    elif isinstance(v, (str, int, float)):
                        parts.append(str(v))
            else:
                parts.append(str(obj))
        except Exception:
            pass
        return ' '.join(parts).lower()

    qkey = (
        game.db_cat,
        game.db_sub if game.db_cat in ('Items','NPCs') else None,
        bool(game.db_name_only),
        bool(game.db_starts_with),
        (game.db_query or '').strip(),
        tuple(sorted(game.db_fields_sel.get(game.db_cat, []))),
        getattr(game, 'db_sort_key', 'Name'),
        bool(getattr(game, 'db_sort_desc', False)),
    )
    if getattr(game, '_db_prev_filter_key', None) != qkey:
        game.db_page = 0
        game.db_sel = None
        game._db_prev_filter_key = qkey

    query = (game.db_query or '').strip().lower()
    filtered = entries
    if query:
        if game.db_starts_with:
            filtered = [e for e in entries if _entry_name(e).lower().startswith(query)]
        elif game.db_name_only:
            filtered = [e for e in entries if query in _entry_name(e).lower()]
        else:
            # tokenized AND-match across selected fields (or all if none selected)
            tokens = [t for t in re.split(r"\s+", query) if t]
            selected = list(game.db_fields_sel.get(cat, []))
            # Build map from label to path tuple
            def _field_options_for(cat: str) -> List[Tuple[str, Tuple[str, ...]]]:
                if cat == 'NPCs':
                    return [
                        ('Name', ('name','id')),
                        ('Race', ('race',)),
                        ('Sex',  ('sex',)),
                        ('Type', ('type',)),
                        ('Appearance', ('appearance.eye_color','appearance.hair_color','appearance.build','appearance.skin_tone')),
                        ('Description', ('desc','description','bio')),
                    ]
                if cat == 'Items':
                    return [
                        ('Name', ('name','id')),
                        ('Type', ('category','slot','item_type','Type','type','subtype','SubType')),
                        ('Description', ('desc','description','flavor')),
                    ]
                if cat == 'Armour Sets':
                    return [
                        ('Name', ('name','id')),
                        ('Pieces', ('piece_names','slot_names')),
                        ('Bonuses', ('set_bonus',)),
                    ]
                if cat == 'Races':
                    return [
                        ('Name', ('name','id')),
                        ('Group', ('race_group',)),
                        ('Appearance', ('appearance',)),
                        ('Nature & Culture', ('nature_and_culture',)),
                        ('Combat', ('combat',)),
                        ('Flavor', ('spice',)),
                    ]
                if cat == 'Curses':
                    return [
                        ('Name', ('name','id')),
                        ('Summary', ('summary',)),
                        ('Requires', ('requires',)),
                        ('State', ('state',)),
                        ('Acquisition', ('acquisition',)),
                        ('Weakness', ('weakness',)),
                        ('Powers', ('powers',)),
                        ('Cures', ('cures',)),
                    ]
                return [
                    ('Name', ('name','id')),
                    ('Details', ('effect','effects','tags','applies_to','school','damage','mp','summary','requires','weakness','powers','cures','state','acquisition')),
                ]
            path_map = {lab: paths for (lab, paths) in _field_options_for(cat)}
            # Helper: get values by paths
            def _vals_by_paths(obj, paths: Tuple[str,...]) -> List[str]:
                out: List[str] = []
                for p in paths:
                    try:
                        cur = obj
                        for part in p.split('.'):
                            if isinstance(cur, dict):
                                cur = cur.get(part)
                            else:
                                cur = None; break
                        if cur is None: continue
                        if isinstance(cur, (list, tuple)):
                            for v in cur:
                                if isinstance(v, (str,int,float)):
                                    out.append(str(v))
                        elif isinstance(cur, dict):
                            for v in cur.values():
                                if isinstance(v, (str,int,float)):
                                    out.append(str(v))
                        elif isinstance(cur, (str,int,float)):
                            out.append(str(cur))
                    except Exception:
                        pass
                return out
            def _hay_sel(x):
                if not selected:
                    return _flatten(x)
                buf: List[str] = []
                for lab in selected:
                    paths = path_map.get(lab)
                    if not paths: continue
                    buf.extend(_vals_by_paths(x, paths))
                return ' '.join(buf).lower()
            _cache = {}
            def hay(x):
                k=id(x); v=_cache.get(k)
                if v is None:
                    v=_hay_sel(x); _cache[k]=v
                return v
            filtered = [e for e in entries if all(t in hay(e) for t in tokens)]

    # List rendering with pagination (two columns, left-to-right)
    total = len(filtered)
    row_h = 52  # taller rows for readability
    inner_pad = 8
    col_gap = 12
    num_cols = 2
    col_w = max(140, (list_area.w - inner_pad*2 - col_gap) // num_cols)
    # Reserve space for filter input row
    filter_h = 32
    rows_vis = max(3, (list_area.h - inner_pad*2 - filter_h - 28) // row_h)
    per_page = max(1, rows_vis * num_cols)
    pages = max(1, (total + per_page - 1)//per_page)
    game.db_page = max(0, min(int(getattr(game,'db_page',0)), pages-1))
    start = game.db_page * per_page
    end = min(total, start + per_page)

    name_font = game._db_font_26
    if not hasattr(game, '_db_label_cache'):
        game._db_label_cache = {}
    list_x0 = list_area.x + inner_pad
    # Draw filter input + toggles
    inp_w = max(100, list_area.w - 2*inner_pad - 600)
    inp_rect = pg.Rect(list_x0, list_area.y + inner_pad, inp_w, 28)
    is_focus = bool(getattr(game, 'db_filter_focus', False))
    pg.draw.rect(surf, (38,40,52), inp_rect, border_radius=6)
    pg.draw.rect(surf, (122,162,247) if is_focus else (96,102,124), inp_rect, 2, border_radius=6)
    # Render query text
    q_show = game.db_query or ''
    q_font = game._db_font_20
    qs = q_font.render(q_show, True, (235,235,245))
    surf.blit(qs, (inp_rect.x + 8, inp_rect.y + (inp_rect.h - qs.get_height())//2))
    # Caret (blink simple based on time)
    try:
        import time as _t
        if is_focus and int(_t.time()*2)%2 == 0:
            cx = inp_rect.x + 8 + qs.get_width() + 1
            pg.draw.line(surf, (235,235,245), (cx, inp_rect.y + 6), (cx, inp_rect.bottom - 6), 2)
    except Exception:
        pass
    # Input click handler
    buttons.append(Button(inp_rect, "", lambda: setattr(game,'db_filter_focus', True), draw_bg=False))
    # Toggle chips: Name Only, Starts With
    tog_w = 120
    tog_h = 28
    tog1 = pg.Rect(inp_rect.right + 10, inp_rect.y, tog_w, tog_h)
    tog2 = pg.Rect(tog1.right + 10, inp_rect.y, tog_w, tog_h)
    for rect, label, val_name in ((tog1, 'Name Only', 'db_name_only'), (tog2, 'Starts With', 'db_starts_with')):
        on = bool(getattr(game, val_name, False))
        pg.draw.rect(surf, (58,62,78) if on else (36,38,48), rect, border_radius=8)
        pg.draw.rect(surf, (122,162,247) if on else (96,102,124), rect, 2, border_radius=8)
        ts = q_font.render(label, True, (230,230,240))
        surf.blit(ts, (rect.x + (rect.w - ts.get_width())//2, rect.y + (rect.h - ts.get_height())//2))
        def make_toggle(vn=val_name):
            return lambda vn=vn: setattr(game, vn, not bool(getattr(game, vn, False)))
        buttons.append(Button(rect, "", make_toggle(val_name), draw_bg=False))

    # Dropdown for selecting which fields to search
    dd_w = 130
    dd_h = 28
    dd_rect = pg.Rect(tog2.right + 10, inp_rect.y, dd_w, dd_h)
    is_open = bool(getattr(game, 'db_filters_open', False))
    pg.draw.rect(surf, (36,38,48), dd_rect, border_radius=8)
    pg.draw.rect(surf, (96,102,124), dd_rect, 2, border_radius=8)
    dd_label = ('Fields v' if not is_open else 'Fields ^')
    ds = q_font.render(dd_label, True, (230,230,240))
    surf.blit(ds, (dd_rect.x + (dd_rect.w - ds.get_width())//2, dd_rect.y + (dd_rect.h - ds.get_height())//2))
    def _toggle_fields():
        game.db_filters_open = not bool(getattr(game,'db_filters_open', False))
        if game.db_filters_open:
            game.db_sort_open = False
    buttons.append(Button(dd_rect, "", _toggle_fields, draw_bg=False))

    # Sort controls: dropdown for field + order toggle
    def _sort_options_for(cat: str) -> List[str]:
        if cat == 'Items':
            return ['Rarity','Type','Name']
        if cat == 'NPCs':
            return ['Name','Race','Sex','Type']
        if cat == 'Armour Sets':
            return ['Rarity','Type','Pieces']
        return ['Name']

    sort_opts = _sort_options_for(cat)
    sort_w = 130
    sort_h = dd_h
    sort_rect = pg.Rect(dd_rect.right + 10, inp_rect.y, sort_w, sort_h)
    sort_open = bool(getattr(game, 'db_sort_open', False))
    pg.draw.rect(surf, (36,38,48), sort_rect, border_radius=8)
    pg.draw.rect(surf, (96,102,124), sort_rect, 2, border_radius=8)
    cur_sort = getattr(game, 'db_sort_key', 'Name')
    sort_label = f"Sort: {cur_sort}"
    ss = q_font.render(sort_label, True, (230,230,240))
    surf.blit(ss, (sort_rect.x + (sort_rect.w - ss.get_width())//2, sort_rect.y + (sort_rect.h - ss.get_height())//2))
    def _toggle_sort_dd():
        game.db_sort_open = not bool(getattr(game, 'db_sort_open', False))
        if game.db_sort_open:
            game.db_filters_open = False
    buttons.append(Button(sort_rect, "", _toggle_sort_dd, draw_bg=False))

    # Direction toggle (A-Z / Z-A)
    ord_w = 70
    ord_rect = pg.Rect(sort_rect.right + 10, inp_rect.y, ord_w, sort_h)
    ord_desc = bool(getattr(game,'db_sort_desc', False))
    pg.draw.rect(surf, (36,38,48), ord_rect, border_radius=8)
    pg.draw.rect(surf, (96,102,124), ord_rect, 2, border_radius=8)
    ord_label = 'Z-A' if ord_desc else 'A-Z'
    ord_surf = q_font.render(ord_label, True, (230,230,240))
    surf.blit(ord_surf, (ord_rect.x + (ord_rect.w - ord_surf.get_width())//2, ord_rect.y + (ord_rect.h - ord_surf.get_height())//2))
    def _toggle_dir():
        game.db_sort_desc = not bool(getattr(game, 'db_sort_desc', False))
    buttons.append(Button(ord_rect, "", _toggle_dir, draw_bg=False))

    # Define available field options per category
    def _field_options_for(cat: str) -> List[Tuple[str, Tuple[str, ...]]]:
        if cat == 'NPCs':
            return [
                ('Name', ('name','id')),
                ('Race', ('race',)),
                ('Sex',  ('sex',)),
                ('Type', ('type',)),
                ('Appearance', ('appearance.eye_color','appearance.hair_color','appearance.build','appearance.skin_tone')),
                ('Description', ('desc','description','bio')),
            ]
        if cat == 'Items':
            return [
                ('Name', ('name','id')),
                ('Type', ('category','slot','item_type','Type','type','subtype','SubType')),
                ('Description', ('desc','description','flavor')),
            ]
        if cat == 'Armour Sets':
            # Use flattened helper fields gathered in gather_armour_sets
            return [
                ('Name', ('name','id')),
                ('Pieces', ('piece_names','slot_names')),
                ('Bonuses', ('set_bonus',)),
            ]
        if cat == 'Races':
            return [
                ('Name', ('name','id')),
                ('Group', ('race_group',)),
                ('Appearance', ('appearance',)),
                ('Nature & Culture', ('nature_and_culture',)),
                ('Combat', ('combat',)),
                ('Flavor', ('spice',)),
            ]
        # Default for other categories
        return [
                ('Name', ('name','id')),
                ('Details', ('effect','effects','tags','applies_to','school','damage','mp','summary','requires','weakness','powers','cures','state','acquisition')),
            ]
    field_opts = _field_options_for(cat)
    # Maintain selection per category
    sel_labels: Set[str] = set(game.db_fields_sel.get(cat, []))
    # Dropdown panel (drawn after list to ensure it stays on top) -- see bottom of function

    list_y0 = list_area.y + inner_pad + filter_h

    # Dot colors matching the map overlay
    COL_ENEMY    = (160,160,170)
    COL_ALLY     = (80,200,120)
    COL_CITIZEN  = (80,150,240)
    COL_MONSTER  = (220,70,70)
    COL_VILLAIN  = (170,110,240)
    COL_ANIMAL   = (245,210,80)
    COL_ITEM     = (240,240,240)
    COL_QITEM    = (255,160,70)

    def _npc_color(n: Dict) -> Tuple[int,int,int]:
        # Prefer explicit subcategory chip when selected
        subcat = (game.db_sub or '').lower() if cat == 'NPCs' else ''
        mapping = {
            'allies': COL_ALLY,
            'animals': COL_ANIMAL,
            'citizens': COL_CITIZEN,
            'enemies': COL_ENEMY,
            'aberrations': COL_MONSTER,
            'villains': COL_VILLAIN,
        }
        if subcat in mapping:
            return mapping[subcat]
        # Heuristics when viewing 'All'
        try:
            t = str(n.get('type') or '').lower()
        except Exception:
            t = ''
        if 'villain' in t: return COL_VILLAIN
        if ('monster' in t) or ('aberration' in t) or ('calam' in t): return COL_MONSTER
        if 'animal' in t: return COL_ANIMAL
        if 'citizen' in t: return COL_CITIZEN
        try:
            if bool(n.get('hostile')): return COL_ENEMY
        except Exception:
            pass
        return COL_ALLY

    def _entry_dot_color(obj: Any) -> Optional[Tuple[int,int,int]]:
        # Keep colored dots for NPCs only
        if cat == 'NPCs' and isinstance(obj, dict):
            return _npc_color(obj)
        return None

    for i in range(start, end):
        it = filtered[i]
        local = i - start
        col = local % num_cols
        row = local // num_cols
        x = list_x0 + col * (col_w + col_gap)
        y = list_y0 + row * row_h
        r = pg.Rect(x, y, col_w, row_h-4)
        sel = (game.db_sel == i)
        pg.draw.rect(surf, (52,56,70) if sel else (34,36,46), r, border_radius=6)
        pg.draw.rect(surf, (90,94,112), r, 1, border_radius=6)
        # Label by category
        label = "?"
        try:
            if cat == 'Items':
                label = f"{item_name(it)}"
            elif cat == 'Armour Sets':
                try:
                    cnt = int(it.get('count') or len(it.get('pieces') or []))
                except Exception:
                    cnt = len(it.get('pieces') or []) if isinstance(it, dict) else 0
                label = f"{str(it.get('name') or it.get('id') or '?')} ({cnt} pcs)"
            elif cat == 'NPCs':
                label = str(it.get('name') or it.get('id') or '?')
            elif cat == 'Races':
                label = str(it.get('name') or it.get('id') or '?')
            elif cat in ('Traits','Enchants','Magic','Status','Classes','Curses'):
                label = str(it.get('name') or it.get('id') or '?')
        except Exception:
            label = str(it)
        # Compute label color (rarity for Items and Armour Sets; default otherwise)
        lab_color = (230,230,240)
        if cat == 'Items' and isinstance(it, dict):
            try:
                _rar = str((it.get('rarity') or '')).lower()
                lab_color = RARITY_COLORS.get(_rar, lab_color)
            except Exception:
                pass
        elif cat == 'Armour Sets' and isinstance(it, dict):
            try:
                _rar = str((it.get('rarity') or '')).lower()
                lab_color = RARITY_COLORS.get(_rar, lab_color)
            except Exception:
                pass
        cache_key = (label, int(name_font.get_height()), lab_color)
        lab_surf = game._db_label_cache.get(cache_key)
        if lab_surf is None:
            lab_surf = name_font.render(label, True, lab_color)
            game._db_label_cache[cache_key] = lab_surf
        ty = r.y + max(4, (r.h - lab_surf.get_height())//2)
        # Draw dot (if applicable) and adjust text x
        dot = _entry_dot_color(it)
        text_x = r.x + 10
        if dot is not None:
            rad = max(4, min(8, r.h // 6))
            cx = r.x + 10 + rad
            cy = r.y + r.h//2
            pg.draw.circle(surf, (10,10,12), (int(cx), int(cy)), rad+1)
            pg.draw.circle(surf, dot, (int(cx), int(cy)), rad)
            text_x = cx + rad + 6
        surf.blit(lab_surf, (text_x, ty))
        def make_sel(idx=i):
            return lambda idx=idx: setattr(game,'db_sel', idx)
        if not (is_open or sort_open):
            buttons.append(Button(r, "", make_sel(i), draw_bg=False))

    # Pager controls (bottom-left)
    pager_y = list_area.bottom - 30
    buttons.append(Button((list_area.x + 8, pager_y, 110, 26), "Prev Page", lambda: setattr(game,'db_page', max(0, game.db_page-1))))
    buttons.append(Button((list_area.x + 8 + 120, pager_y, 110, 26), "Next Page", lambda: setattr(game,'db_page', min(pages-1, game.db_page+1))))

    # Draw dropdown panel last so it overlays the list
    if is_open:
        panel = pg.Rect(dd_rect.x, dd_rect.bottom + 6, max(dd_w, 240), 8 + 30 + ((len(field_opts)+1)//2)*30)
        pg.draw.rect(surf, (30,32,42), panel, border_radius=8)
        pg.draw.rect(surf, (70,74,92), panel, 1, border_radius=8)
        # Quick actions
        qa_w = 90; qa_h = 24
        qa_all = pg.Rect(panel.x + 8, panel.y + 8, qa_w, qa_h)
        qa_none= pg.Rect(qa_all.right + 8, panel.y + 8, qa_w, qa_h)
        for rect, lab, mode in ((qa_all,'Select All','all'), (qa_none,'Clear','none')):
            pg.draw.rect(surf, (36,38,48), rect, border_radius=6)
            pg.draw.rect(surf, (96,102,124), rect, 1, border_radius=6)
            t = q_font.render(lab, True, (230,230,240))
            surf.blit(t, (rect.x + (rect.w - t.get_width())//2, rect.y + (rect.h - t.get_height())//2))
            if mode == 'all':
                buttons.append(Button(rect, "", lambda: (game.db_fields_sel.__setitem__(cat, [fo[0] for fo in field_opts])), draw_bg=False))
            else:
                buttons.append(Button(rect, "", lambda: (game.db_fields_sel.__setitem__(cat, [])), draw_bg=False))
        # Options grid
        sel_labels = set(game.db_fields_sel.get(cat, []))
        grid_x = panel.x + 8
        grid_y = qa_all.bottom + 8
        col_w2 = (panel.w - 8 - 8 - 8) // 2
        for idx, (lab, _paths) in enumerate(field_opts):
            cx = grid_x + (idx % 2) * (col_w2 + 8)
            cy = grid_y + (idx // 2) * 30
            r = pg.Rect(cx, cy, col_w2, 26)
            on = (lab in sel_labels)
            pg.draw.rect(surf, (58,62,78) if on else (36,38,48), r, border_radius=6)
            pg.draw.rect(surf, (122,162,247) if on else (96,102,124), r, 1, border_radius=6)
            ts = q_font.render(lab, True, (230,230,240))
            surf.blit(ts, (r.x + 8, r.y + (r.h - ts.get_height())//2))
            def make_toggle_field(label=lab):
                def _cb(label=label):
                    s = set(game.db_fields_sel.get(cat, []))
                    if label in s: s.remove(label)
                    else: s.add(label)
                    game.db_fields_sel[cat] = list(s)
                return _cb
            buttons.append(Button(r, "", make_toggle_field(lab), draw_bg=False))

    # Sort dropdown panel
    if sort_open:
        s_panel_h = 8 + len(sort_opts)*28 + 8
        s_panel = pg.Rect(sort_rect.x, sort_rect.bottom + 6, sort_w, s_panel_h)
        pg.draw.rect(surf, (30,32,42), s_panel, border_radius=8)
        pg.draw.rect(surf, (70,74,92), s_panel, 1, border_radius=8)
        y0 = s_panel.y + 8
        for opt in sort_opts:
            r = pg.Rect(s_panel.x + 8, y0, s_panel.w - 16, 24)
            on = (opt == cur_sort)
            pg.draw.rect(surf, (58,62,78) if on else (36,38,48), r, border_radius=6)
            pg.draw.rect(surf, (122,162,247) if on else (96,102,124), r, 1, border_radius=6)
            ts = q_font.render(opt, True, (230,230,240))
            surf.blit(ts, (r.x + 8, r.y + (r.h - ts.get_height())//2))
            def _make_set_sort(label=opt):
                def _cb(label=label):
                    # Set sort key; keep current direction toggle
                    game.db_sort_key = label
                    game.db_sort_open = False
                return _cb
            buttons.append(Button(r, "", _make_set_sort(opt), draw_bg=False))
            y0 += 28

    # Details panel
    det_font = pg.font.Font(None, 20)
    head_font = pg.font.Font(None, 24)
    if game.db_sel is not None and 0 <= game.db_sel < total:
        it = filtered[game.db_sel]
        # Title
        title = str(it.get('name') or it.get('id') or '?') if isinstance(it, dict) else str(it)
        surf.blit(head_font.render(title, True, (235,235,245)), (det_area.x + 12, det_area.y + 10))
        yy = det_area.y + 40

        def line(txt: str):
            nonlocal yy
            yy += draw_text(surf, txt, (det_area.x + 12, yy), max_w=det_area.w - 24, font=det_font) + 2

        try:
            if cat == 'Items':
                wt = item_weight(it)
                val = item_value(it)
                t = str(item_type(it) or '-')
                s = str(item_subtype(it) or '-')
                line(f"ID: {it.get('id','-')}")
                line(f"Type: {t} / {s}")
                line(f"Weight: {wt}")
                line(f"Value: {val}")
                desc = item_desc(it) or '-'
                yy += 4; line("Description:")
                line(desc)
            elif cat == 'Armour Sets':
                try:
                    cnt = int(it.get('count') or len(it.get('pieces') or []))
                except Exception:
                    cnt = len(it.get('pieces') or []) if isinstance(it, dict) else 0
                slots = it.get('slots') or []
                line(f"ID: {it.get('id','-')}")
                line(f"Pieces: {cnt}")
                if slots:
                    line("Slots: " + ", ".join([str(s) for s in slots]))
                # Set bonuses by threshold
                sb = it.get('set_bonus') or {}
                if isinstance(sb, dict) and sb:
                    try:
                        # sort thresholds numerically if possible
                        def _th_key(x):
                            try: return int(str(x))
                            except Exception: return 0
                        yy += 4; line("Set Bonuses:")
                        for th in sorted(sb.keys(), key=_th_key):
                            eff = sb.get(th) or {}
                            if isinstance(eff, dict):
                                kv = ", ".join([f"{k}+{v}" for k,v in eff.items()]) if eff else "-"
                                line(f"- {th} pieces: {kv}")
                            else:
                                line(f"- {th} pieces: {eff}")
                    except Exception:
                        pass
                # Pieces list
                pcs = it.get('pieces') or []
                if isinstance(pcs, list) and pcs:
                    yy += 4; line("Pieces:")
                    for p in pcs:
                        try:
                            pn = p.get('name') or p.get('id') or '?'
                            ps = p.get('slot') or '-'
                            line(f"- {pn} [{ps}]")
                        except Exception:
                            line(f"- {p}")
            elif cat == 'NPCs':
                line(f"ID: {it.get('id','-')}")
                line(f"Race: {it.get('race') or '-'}")
                flags = []
                for k in ('hostile','romanceable'):
                    try:
                        if bool(it.get(k)): flags.append(k)
                    except Exception: pass
                if flags:
                    line("Flags: " + ", ".join(flags))
                for k in ('hp','dex','will','greed'):
                    if k in it:
                        line(f"{k.upper()}: {it.get(k)}")
                # Appearance section (if provided)
                ap = it.get('appearance')
                if ap:
                    yy += 4; line("Appearance:")
                    if isinstance(ap, dict):
                        # Pretty-print common appearance fields
                        for k, v in ap.items():
                            try:
                                label = str(k).replace('_',' ').title()
                                line(f"- {label}: {v}")
                            except Exception:
                                line(f"- {k}: {v}")
                    else:
                        line(str(ap))
                # Description section: support several common keys
                desc = it.get('desc') or it.get('description') or it.get('bio')
                if desc:
                    yy += 4; line("Description:")
                    line(str(desc))
            elif cat == 'Races':
                line(f"ID: {it.get('id','-')}")
                rg = it.get('race_group'); line(f"Group: {rg if rg else '-'}")
                for k, lab in (('appearance','Appearance'), ('nature_and_culture','Nature & Culture'), ('combat','Combat'), ('spice','Flavor')):
                    if it.get(k):
                        yy += 4; line(lab + ":")
                        line(str(it.get(k)))
            elif cat in ('Traits','Enchants'):
                line(f"ID: {it.get('id','-')}")
                if it.get('applies_to'):
                    line(f"Applies To: {it.get('applies_to')}")
                eff = it.get('effect') or {}
                if eff:
                    yy += 4; line("Effect:")
                    for k,v in eff.items():
                        line(f"- {k}: {v}")
            elif cat == 'Magic':
                line(f"ID: {it.get('id','-')}")
                if it.get('school'): line(f"School: {it.get('school')}")
                if it.get('mp') is not None: line(f"MP: {it.get('mp')}")
                dmg = it.get('damage') or {}
                if isinstance(dmg, dict) and ('min' in dmg or 'max' in dmg):
                    line(f"Damage: {dmg.get('min','?')} - {dmg.get('max','?')}")
                if it.get('applies_status'): line(f"Applies Status: {it.get('applies_status')}")
            elif cat == 'Curses':
                line(f"ID: {it.get('id','-')}")
                if it.get('requires'): line(f"Requires: {it.get('requires')}")
                if it.get('state'): line(f"State: {it.get('state')}")
                if it.get('summary'):
                    yy += 4; line("Summary:")
                    line(str(it.get('summary')))
                for key, lab in (("acquisition","Acquisition"),("powers","Powers"),("weakness","Weakness"),("cures","Cures"),("empowerment","Empowerment")):
                    arr = it.get(key) or []
                    if isinstance(arr, list) and arr:
                        yy += 4; line(lab + ":")
                        for v in arr:
                            line(f"- {v}")
                if it.get('sustenance'):
                    line(f"Sustenance: {it.get('sustenance')}")
                ao = it.get('appearance_overrides') or {}
                if isinstance(ao, dict) and ao:
                    yy += 4; line("Appearance Overrides:")
                    for k,v in ao.items():
                        if isinstance(v, list):
                            line(f"- {k}: " + ", ".join([str(x) for x in v]))
                        else:
                            line(f"- {k}: {v}")
            elif cat == 'Status':
                line(f"ID: {it.get('id','-')}")
                tags = it.get('tags') or []
                if tags: line("Tags: " + ", ".join([str(t) for t in tags]))
                eff = it.get('effects') or {}
                if eff:
                    yy += 4; line("Effects:")
                    for k,v in eff.items():
                        if isinstance(v, dict):
                            line(f"- {k}:")
                            for k2,v2 in v.items():
                                line(f"   * {k2}: {v2}")
                        else:
                            line(f"- {k}: {v}")
            elif cat == 'Classes':
                # Unknown schema; show raw keys
                if isinstance(it, dict):
                    for k,v in it.items():
                        line(f"{k}: {v}")
        except Exception:
            pass

    return buttons

# ======================== Game class + loop ========================
class Game:
    def __init__(self, start_map: Optional[str]=None, start_entry: Optional[str]=None, start_pos: Optional[Tuple[int,int]]=None, char_config: Optional[Dict[str, Any]] = None):
        random.seed()
        # Stable world seed (persisted in saves)
        try:
            self.world_seed = int(random.getrandbits(32))
        except Exception:
            self.world_seed = int(random.randint(0, 2**31-1))
        self.items   = gather_items()
        self.item_catalog: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.items_by_rarity: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for base in (self.items or []):
            if not isinstance(base, dict):
                continue
            clone = copy.deepcopy(base)
            item_id = str(clone.get('id') or '').strip()
            if item_id:
                self.item_catalog[item_id].append(clone)
            rarity = str(clone.get('rarity') or 'common').lower()
            self.items_by_rarity[rarity].append(clone)
        self.npcs    = gather_npcs()
        self.traits  = load_traits()
        self.enchants= load_enchants()
        self.magic   = load_magic()
        self.status  = load_status()
        self.curses  = load_curses()
        # Additional lore datasets
        self.races   = load_races_list()
        self.classes = load_classes_list()
        # Load start map from world_map.json and build grid from editor/runtime
        wm_map, wm_entry, wm_pos = get_game_start()
        sel_map = start_map or wm_map or "Jungle of Hills"
        # Stable map identifier (filename-style without .json) for link matching
        if isinstance(sel_map, str) and sel_map.lower().endswith('.json'):
            sel_map_id = sel_map[:-5]
        else:
            sel_map_id = sel_map
        entry_name = start_entry if start_entry is not None else wm_entry
        pos = start_pos if start_pos is not None else wm_pos
        scene = load_scene_by_name('map', sel_map)
        runtime = scene_to_runtime(scene)
        self.W, self.H = int(runtime.get('width', 12)), int(runtime.get('height', 8))
        self.tile_px = int(runtime.get('tile_size', 32))
        self.grid    = grid_from_runtime(runtime, self.items, self.npcs)
        self.current_map_name = runtime.get('name', sel_map)
        # Track a stable ID separate from display name to match links reliably
        self.current_map_id = sel_map_id
        self._restore_returning_allies_for_map(self.current_map_id)
        self.player  = Player()
        # Apply character creation config if provided
        if isinstance(char_config, dict):
            try:
                nm = char_config.get('name');  self.player.name = nm or self.player.name
                rc = char_config.get('race');  self.player.race = rc or self.player.race
                rl = char_config.get('role');  self.player.role = rl or self.player.role
                ap = char_config.get('appearance') or {}
                setattr(self.player, 'appearance', dict(ap))
                setattr(self.player, 'backstory', str(char_config.get('backstory') or ''))
            except Exception:
                pass
        # Level/class setup
        if not getattr(self.player, 'level', None):
            self.player.level = 1
        if not getattr(self.player, 'xp', None):
            self.player.xp = 0
        # If role is placeholder and classes are available, pick the first class by default
        try:
            if (str(getattr(self.player, 'role', '')).strip().lower() in ('', 'wanderer')) and self.classes:
                self.player.role = str(self.classes[0].get('name') or 'Adventurer')
        except Exception:
            pass
        # Party system
        self.party: List[Ally] = []  # allies that can join
        self.returning_allies: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # Equipment target index for overlay: 0=player, 1..N=ally index+1
        self.equip_target_idx: int = 0
        # Position player: entry takes precedence, else pos, else (0,0)
        if entry_name:
            px, py = find_entry_coords(scene, entry_name)
        elif pos:
            try:
                px, py = int(pos[0]), int(pos[1])
            except Exception:
                px, py = 0, 0
        else:
            px, py = 0, 0
        # Ensure spawn is on a walkable tile
        px, py = find_nearest_walkable(runtime, px, py)
        self.player.x = max(0, min(self.W-1, px))
        self.player.y = max(0, min(self.H-1, py))
        # Mark starting tile discovered
        try:
            self.grid[self.player.y][self.player.x].discovered = True
        except Exception:
            pass
        self.log = ["You arrive at the edge of the wilds."]
        self.mode = "explore"
        self.current_enemy_hp = 0
        self.current_enemy = None
        self.current_npc = None
        self.can_bribe = False
        self.inv_page = 0
        self.inv_sel = None
        self.equip_sel_slot = None
        # Playtime tracker (milliseconds)
        self.playtime_ms = 0

        # Do not auto-equip placeholders; player equips via Inventory/Equipment
        weps  = [it for it in self.items if str(item_type(it)).lower() == 'weapon']
        if not self.player.inventory and weps:
            # Seed a couple items into inventory only (no auto-equip)
            # Randomize the starting items using a stable context so they carry combat stats
            try:
                ctx0 = f"start:{getattr(self,'world_seed',0)}:inv:0"
                it0 = self._roll_weapon_item(weps[0], ctx0) if not weps[0].get('_rolled') else weps[0]
            except Exception:
                it0 = weps[0]
            self.player.inventory.append(it0)
            if len(weps) > 1:
                try:
                    ctx1 = f"start:{getattr(self,'world_seed',0)}:inv:1"
                    it1 = self._roll_weapon_item(weps[1], ctx1) if not weps[1].get('_rolled') else weps[1]
                except Exception:
                    it1 = weps[1]
                self.player.inventory.append(it1)

        # Apply class base + level growth to player
        try:
            self._apply_class_and_level_to_player(initial=True)
        except Exception:
            pass

    # ---------- Save/Load ----------
    def _save_meta(self) -> Dict[str, Any]:
        def _ser_char(obj) -> Dict[str, Any]:
            return {
                'id': getattr(obj, 'id', ''),
                'name': obj.name,
                'race': obj.race,
                'role': getattr(obj, 'role', ''),
                'level': int(getattr(obj, 'level', 1)),
                'hp': int(getattr(obj, 'hp', 0)),
                'max_hp': int(getattr(obj, 'max_hp', 0)),
                'atk': list(getattr(obj, 'atk', (2,4))),
                'phy': int(getattr(obj, 'phy', 5)),
                'dex': int(getattr(obj, 'dex', 5)),
                'vit': int(getattr(obj, 'vit', 5)),
                'arc': int(getattr(obj, 'arc', 5)),
                'kno': int(getattr(obj, 'kno', 5)),
                'ins': int(getattr(obj, 'ins', 5)),
                'soc': int(getattr(obj, 'soc', 5)),
                'fth': int(getattr(obj, 'fth', 5)),
                'equipped_weapon': getattr(obj, 'equipped_weapon', None),
                # focus removed from serialization; kept for backward loads only
                'equipped_gear': dict(getattr(obj, 'equipped_gear', {}) or {}),
                'portrait': getattr(obj, 'portrait', None),
                'home_map': getattr(obj, 'home_map', None),
                'home_pos': list(getattr(obj, 'home_pos', []) or []) if getattr(obj, 'home_pos', None) is not None else None,
                'home_payload': copy.deepcopy(getattr(obj, 'home_payload', None)),
            }
        return {
            'schema': 'rpgen.save@1',
            'version': 1,
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'map_id': self.current_map_id,
            'map_name': self.current_map_name,
            'pos': [int(self.player.x), int(self.player.y)],
            'player': {
                'name': self.player.name,
                'race': self.player.race,
                'role': self.player.role,
                'level': int(getattr(self.player, 'level', 1)),
                'xp': int(getattr(self.player, 'xp', 0)),
                'hp': self.player.hp,
                'max_hp': self.player.max_hp,
                'atk': list(self.player.atk),
                # Core attributes
                'phy': self.player.phy,
                'dex': self.player.dex,
                'vit': self.player.vit,
                'arc': self.player.arc,
                'kno': self.player.kno,
                'ins': self.player.ins,
                'soc': self.player.soc,
                'fth': self.player.fth,
                'affinity': dict(self.player.affinity),
                'romance_flags': dict(self.player.romance_flags),
                'inventory': list(self.player.inventory),
                'equipped_weapon': self.player.equipped_weapon,
                # focus removed from serialization
                'equipped_gear': dict(self.player.equipped_gear),
            },
            'party': [ _ser_char(a) for a in getattr(self, 'party', []) ],
            'playtime_s': int(getattr(self, 'playtime_ms', 0) // 1000),
            'world_seed': int(getattr(self, 'world_seed', 0)),
            'returning_allies': {
                str(map_id): [
                    {
                        'npc': copy.deepcopy(entry.get('npc')),
                        'pos': list(entry.get('pos') or []),
                    }
                    for entry in entries if isinstance(entry, dict)
                ]
                for map_id, entries in (getattr(self, 'returning_allies', {}) or {}).items()
            },
        }

    def save_to_slot(self, slot: int) -> bool:
        try:
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            path = SAVE_DIR / f"slot{int(slot)}.json"
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._save_meta(), f, ensure_ascii=False, indent=2)
            self.say(f"Game saved to slot {slot}.")
            return True
        except Exception as e:
            self.say(f"Failed to save: {e}")
            return False

    def _apply_loaded_state(self, data: Dict[str, Any]):
        # Restore map
        map_id = data.get('map_id') or data.get('map_name')
        if not map_id:
            return False
        scene = load_scene_by_name('map', map_id)
        runtime = scene_to_runtime(scene)
        self.W, self.H = int(runtime.get('width', 12)), int(runtime.get('height', 8))
        self.tile_px = int(runtime.get('tile_size', 32))
        self.grid    = grid_from_runtime(runtime, self.items, self.npcs)
        self.current_map_name = runtime.get('name', map_id)
        self.current_map_id = map_id if isinstance(map_id, str) else self.current_map_id

        # Restore player
        p = data.get('player') or {}
        self.player.name = p.get('name', self.player.name)
        self.player.race = p.get('race', self.player.race)
        self.player.role = p.get('role', self.player.role)
        try:
            self.player.level = int(p.get('level', getattr(self.player, 'level', 1)))
        except Exception:
            pass
        try:
            self.player.xp = int(p.get('xp', getattr(self.player, 'xp', 0)))
        except Exception:
            pass
        try:
            self.player.hp = int(p.get('hp', self.player.hp))
            self.player.max_hp = int(p.get('max_hp', self.player.max_hp))
        except Exception:
            pass
        try:
            atk = p.get('atk') or self.player.atk
            self.player.atk = (int(atk[0]), int(atk[1]))
        except Exception:
            pass
        # Core attributes (with backward-compatibility mapping)
        self.player.dex = int(p.get('dex', getattr(self.player, 'dex', 5)))
        self.player.phy = int(p.get('phy', getattr(self.player, 'phy', 5)))
        self.player.vit = int(p.get('vit', getattr(self.player, 'vit', 5)))
        self.player.arc = int(p.get('arc', getattr(self.player, 'arc', 5)))
        self.player.kno = int(p.get('kno', getattr(self.player, 'kno', 5)))
        self.player.ins = int(p.get('ins', getattr(self.player, 'ins', 5)))
        self.player.soc = int(p.get('soc', getattr(self.player, 'soc', 5)))
        self.player.fth = int(p.get('fth', getattr(self.player, 'fth', 5)))
        # Legacy: map saved 'stealth' into Insight if present
        try:
            if 'stealth' in p and 'ins' not in p:
                self.player.ins = int(p.get('stealth', self.player.ins))
        except Exception:
            pass
        self.player.affinity = dict(p.get('affinity', self.player.affinity))
        self.player.romance_flags = dict(p.get('romance_flags', self.player.romance_flags))
        self.player.inventory = list(p.get('inventory', self.player.inventory))
        # Normalize weapon stats for any unrolled weapons in inventory
        try:
            for it in self.player.inventory:
                _ensure_weapon_combat_stats_inplace(it)
        except Exception:
            pass
        self.player.equipped_weapon = p.get('equipped_weapon')
        try:
            _ensure_weapon_combat_stats_inplace(self.player.equipped_weapon)
        except Exception:
            pass
        self.player.equipped_gear   = migrate_gear_keys(p.get('equipped_gear', self.player.equipped_gear))
        # Migration: hydrate equipped_weapon from equipped_gear['weapon_main'] if missing
        try:
            if not self.player.equipped_weapon and isinstance(self.player.equipped_gear, dict):
                w_main = self.player.equipped_gear.get('weapon_main')
                if w_main:
                    self.player.equipped_weapon = w_main
        except Exception:
            pass

        # Restore party
        self.party = []
        try:
            for a in (data.get('party') or []):
                try:
                    ally = Ally(
                        id=str(a.get('id') or a.get('name') or f"AL{len(self.party)+1:03d}"),
                        name=str(a.get('name') or 'Ally'),
                        race=str(a.get('race') or 'Human'),
                        role=str(a.get('role') or 'Ally'),
                        level=int(a.get('level', 1) or 1),
                        hp=int(a.get('hp', 10) or 10),
                        max_hp=int(a.get('max_hp', a.get('hp', 10)) or a.get('hp', 10)),
                        atk=tuple(a.get('atk') or (2,4)),
                        phy=int(a.get('phy', 5) or 5),
                        dex=int(a.get('dex', 5) or 5),
                        vit=int(a.get('vit', 5) or 5),
                        arc=int(a.get('arc', 5) or 5),
                        kno=int(a.get('kno', 5) or 5),
                        ins=int(a.get('ins', 5) or 5),
                        soc=int(a.get('soc', 5) or 5),
                        fth=int(a.get('fth', 5) or 5),
                        equipped_weapon=(a.get('equipped_weapon') or (a.get('equipped_gear') or {}).get('weapon_main')),
                        equipped_gear=migrate_gear_keys(a.get('equipped_gear', {})),
                        portrait=a.get('portrait'),
                        home_map=a.get('home_map'),
                        home_pos=tuple(a.get('home_pos')) if isinstance(a.get('home_pos'), (list, tuple)) else None,
                        home_payload=copy.deepcopy(a.get('home_payload'))
                    )
                    # Post-fix ally equipped weapon from gear map if still missing
                    try:
                        if not getattr(ally, 'equipped_weapon', None) and isinstance(ally.equipped_gear, dict):
                            w_main = ally.equipped_gear.get('weapon_main')
                            if w_main:
                                ally.equipped_weapon = w_main
                        _ensure_weapon_combat_stats_inplace(ally.equipped_weapon)
                    except Exception:
                        pass
                    self.party.append(ally)
                except Exception:
                    pass
        except Exception:
            self.party = []

        self.returning_allies = defaultdict(list)
        for map_id, entries in (data.get('returning_allies') or {}).items():
            if not isinstance(entries, list):
                continue
            bucket = self.returning_allies[str(map_id)]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                npc_payload = entry.get('npc')
                pos = entry.get('pos')
                if npc_payload is None or pos is None:
                    continue
                try:
                    pos_tuple = (int(pos[0]), int(pos[1]))
                except Exception:
                    continue
                bucket.append({'npc': npc_payload, 'pos': pos_tuple})

        # Position
        pos = data.get('pos') or [0,0]
        self.player.x = max(0, min(self.W-1, int(pos[0] if len(pos)>0 else 0)))
        self.player.y = max(0, min(self.H-1, int(pos[1] if len(pos)>1 else 0)))
        try:
            self.grid[self.player.y][self.player.x].discovered = True
        except Exception:
            pass
        # Reapply class effects to ensure atk/hp reflect class+level
        try:
            self._apply_class_and_level_to_player(initial=False, preserve_hp=True)
        except Exception:
            pass
        self._restore_returning_allies_for_map(self.current_map_id)
        self.mode = 'explore'
        try:
            self.playtime_ms = int((data.get('playtime_s') or 0) * 1000)
        except Exception:
            self.playtime_ms = getattr(self, 'playtime_ms', 0)
        try:
            ws = int(data.get('world_seed', getattr(self, 'world_seed', 0)))
            self.world_seed = ws
        except Exception:
            pass
        return True

    def load_from_slot(self, slot: int) -> bool:
        try:
            path = SAVE_DIR / f"slot{int(slot)}.json"
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ok = self._apply_loaded_state(data)
            if ok:
                self.say(f"Loaded game from slot {slot}.")
            else:
                self.say("Save file missing required data.")
            return ok
        except FileNotFoundError:
            self.say("No save in that slot.")
            return False
        except Exception as e:
            self.say(f"Failed to load: {e}")
            return False

    def tile(self, x=None, y=None) -> Tile:
        if x is None: x = self.player.x
        if y is None: y = self.player.y
        return self.grid[y][x]

    def say(self, msg: str, tag: Optional[str]=None):
        # Filter low-signal tags from the Recent log
        if tag and str(tag).lower() in LOG_HIDE_TAGS:
            return
        # Encode tag in-line for UI coloring as "[tag] message"
        if tag:
            msg = f"[{tag}] {msg}"
        self.log.append(msg)
        if len(self.log) > 8:
            self.log = self.log[-8:]

    # ---------- Overlay navigation helpers ----------
    def open_overlay(self, mode_name: str) -> None:
        try:
            self.ui_return_mode = getattr(self, 'mode', 'explore')
        except Exception:
            self.ui_return_mode = 'explore'
        self.mode = mode_name

    def close_overlay(self) -> None:
        prev = getattr(self, 'ui_return_mode', None)
        # Only return to a safe known mode; default to explore
        self.mode = prev if prev in ('explore', 'combat', 'dialogue', 'event') else 'explore'
        try:
            self.ui_return_mode = None
        except Exception:
            pass

    # ---------- Equipment actions ----------
    def _equip_target(self):
        try:
            idx = int(getattr(self, 'equip_target_idx', 0))
        except Exception:
            idx = 0
        if idx <= 0:
            return self.player
        party = getattr(self, 'party', []) or []
        return party[idx-1] if 0 <= (idx-1) < len(party) else self.player

    def _equipped_slot_of(self, actor, it: Dict) -> Optional[str]:
        try:
            if getattr(actor, 'equipped_weapon', None) is it:
                return 'weapon_main'
            # legacy focus slot removed
            gear = getattr(actor, 'equipped_gear', {}) or {}
            for k, v in gear.items():
                if v is it:
                    return str(k)
        except Exception:
            pass
        return None

    def equip_weapon(self, it: Dict):
        target = self._equip_target()
        if item_type(it).lower() == "weapon" and item_subtype(it).lower() not in ("wand","staff"):
            # Block if already equipped elsewhere
            where = self._equipped_slot_of(target, it)
            if where and where != 'weapon_main':
                self.say(f"Already equipped in {SLOT_LABELS.get(where, where)}. Unequip first.")
                return
            # Ensure combat stats exist on this weapon
            try:
                _ensure_weapon_combat_stats_inplace(it)
            except Exception:
                pass
            target.equipped_weapon = it
            # Keep equipped_gear in sync for equipment UI
            try:
                if not hasattr(target, 'equipped_gear') or not isinstance(getattr(target, 'equipped_gear'), dict):
                    target.equipped_gear = {}
                target.equipped_gear['weapon_main'] = it
            except Exception:
                pass
            self.say(f"Equipped weapon on {getattr(target,'name','ally')}: {item_name(it)}")
        else:
            self.say("That cannot be equipped as a weapon.")
    def drop_item(self, idx: int):
        if 0 <= idx < len(self.player.inventory):
            it = self.player.inventory[idx]
            if item_is_quest(it):
                self.say("You cannot drop quest items."); return
            self.player.inventory.pop(idx)
            self.say(f"Dropped: {item_name(it)}")
            self.inv_sel = None
    def equip_item(self, it: Dict):
        m = item_major_type(it)
        if m in ('armour','armor','clothing','accessory','accessories'):
            slots = it.get('equip_slots') or []
            if slots:
                raw = str(slots[0]).lower()
            else:
                raw = str(it.get('slot') or item_subtype(it) or '').lower()
            if raw in ('', '-', 'none', 'null'):
                raw = 'body'
            slot = normalize_slot(raw)
            if slot in ('weapon','weapon_main','weapon_off'):
                # Redirect weapons to equip_weapon/focus
                self.equip_item_to_slot('weapon_main', it)
            else:
                self.equip_item_to_slot(slot, it)
        elif m == 'weapon':
            # Treat all weapons uniformly; wands/staves equip as weapons
            self.equip_weapon(it)
        else:
            self.say("That item cannot be equipped.")
    
    def equip_item_to_slot(self, slot: str, it: Dict):
        slot = normalize_slot(slot)
        target = self._equip_target()
        # Prevent equipping the same item in multiple slots for the same target
        try:
            where = self._equipped_slot_of(target, it)
            if where and where != slot:
                self.say(f"Already equipped in {SLOT_LABELS.get(where, where)}. Unequip first.")
                return
        except Exception:
            pass
        if not slot_accepts(slot, it) and slot not in ('weapon_main','weapon_off'):
            self.say(f"{item_name(it)} cannot be equipped to {SLOT_LABELS.get(slot, slot)}.")
            return
        if not hasattr(target, 'equipped_gear') or not isinstance(getattr(target, 'equipped_gear'), dict):
            target.equipped_gear = {}
        # Replace mapping on the target
        target.equipped_gear[slot] = it
        # Also sync legacy fields for combat
        if slot == 'weapon_main':
            try:
                _ensure_weapon_combat_stats_inplace(it)
            except Exception:
                pass
            target.equipped_weapon = it
        self.say(f"Equipped {item_name(it)} -> {SLOT_LABELS.get(slot, slot)} on {getattr(target,'name','ally')}")

    def unequip_slot(self, slot: str):
        slot = normalize_slot(slot)
        target = self._equip_target()
        it = getattr(target, 'equipped_gear', {}).pop(slot, None)
        if it:
            # Clear legacy fields if they pointed to this item
            if slot == 'weapon_main' and getattr(target, 'equipped_weapon', None) is it:
                target.equipped_weapon = None
            # focus slot removed
            self.say(f"Unequipped {item_name(it)} from {SLOT_LABELS.get(slot, slot)} on {getattr(target,'name','ally')}")
    def consume_item(self, idx: int):
        if 0 <= idx < len(self.player.inventory):
            it = self.player.inventory[idx]
            if not item_is_consumable(it):
                self.say("That item cannot be consumed."); return
            # Simple effect: restore small HP if a hint exists, else just consume
            healed = 0
            for key in ('heal','hp','health','restore_hp','hp_restore'):
                try:
                    val = int(it.get(key) or 0)
                    if val > 0: healed = max(healed, val)
                except Exception:
                    pass
            if healed <= 0:
                # Heuristic: light consumables restore 3-8
                healed = random.randint(3, 8)
            self.player.hp = min(self.player.max_hp, self.player.hp + healed)
            self.say(f"You consume {item_name(it)} (+{healed} HP).")
            self.player.inventory.pop(idx)
            self.inv_sel = None

    def travel_link(self):
        t = self.tile()
        dest_map = getattr(t, 'link_to_map', None)
        if not dest_map:
            self.say("No link here."); return
        dest_entry = getattr(t, 'link_to_entry', None)
        # Load destination scene
        scene = load_scene_by_name('map', dest_map)
        runtime = scene_to_runtime(scene)
        # Determine destination coordinates
        px, py = 0, 0
        if dest_entry:
            try:
                px, py = find_entry_coords(scene, dest_entry)
            except Exception:
                px, py = 0, 0
        else:
            # Find reciprocal link back to this map
            back = None
            for link in (runtime.get('links') or []):
                try:
                    (lx, ly), to, _kind, _entry = link
                except Exception:
                    continue
                # Compare against a stable map ID rather than display name
                if str(to) == str(getattr(self, 'current_map_id', '')):
                    back = (int(lx), int(ly)); break
            if back:
                px, py = back
        # Ensure destination spawn is on a walkable tile
        px, py = find_nearest_walkable(runtime, px, py)
        # Rebuild grid, move player
        self.W, self.H = int(runtime.get('width', 12)), int(runtime.get('height', 8))
        self.tile_px = int(runtime.get('tile_size', 32))
        self.grid    = grid_from_runtime(runtime, self.items, self.npcs)
        self.current_map_name = runtime.get('name', dest_map)
        # Update stable map ID to the destination base name
        self.current_map_id = dest_map
        self._restore_returning_allies_for_map(self.current_map_id)
        self.player.x = max(0, min(self.W-1, int(px)))
        self.player.y = max(0, min(self.H-1, int(py)))
        try:
            self.grid[self.player.y][self.player.x].discovered = True
        except Exception:
            pass
        self.mode = "explore"
        self.say(f"You travel to {self.current_map_name}.")

    def can_leave_tile(self) -> bool:
        # Legacy helper retained; movement rules are enforced in move()
        if self.mode in ("dialogue","combat","event"):
            return False
        return True

    def move(self, dx, dy):
        # Block movement while in interactive modes
        if not self.can_leave_tile():
            return
        px, py = self.player.x, self.player.y
        nx, ny = px + dx, py + dy
        if 0 <= nx < getattr(self, 'W', 12) and 0 <= ny < getattr(self, 'H', 8):
            # Block movement onto impassable tiles
            try:
                target = self.grid[ny][nx]
                if not target.walkable:
                    return
            except Exception:
                pass
            # If current tile has a blocking enemy encounter, restrict exit
            cur_tile = self.tile()
            enc = cur_tile.encounter
            if enc and enc.enemy and enc.must_resolve:
                back = getattr(enc, 'allowed_back', None)
                if enc.spotted:
                    self.say("You're engaged! You cannot retreat. Try Flee.")
                    return
                if back is None or (nx, ny) != tuple(back):
                    self.say("You can't pass until you resolve this encounter, but you can go back.")
                    return
            self.player.x, self.player.y = nx, ny
            t = self.tile(); t.discovered = True; t.visited += 1
            if t.encounter:
                if t.encounter.enemy:
                    # Mark that this tile must be resolved before passing through
                    t.encounter.must_resolve = True
                    t.encounter.allowed_back = (px, py)
                    self.mode = "combat" if t.encounter.spotted else "explore"
                    # Determine enemy type for coloring
                    sub = str((t.encounter.enemy or {}).get('subcategory') or '').lower()
                    tag = 'monster' if sub in ('monsters','aberrations','calamities') else 'enemy'
                    if t.encounter.spotted:
                        self.start_combat(t.encounter.enemy); self.say(f"{t.encounter.enemy.get('name','A foe')} spots you!", tag)
                    else:
                        self.say("An enemy lurks here... maybe you could sneak by.", tag)
                elif t.encounter.npc:
                    # Friendly presence does not block or force dialogue; allow passing by
                    # If multiple friendlies, list them
                    try:
                        def _is_enemy_e(e: Dict) -> bool:
                            sub = (e.get('subcategory') or '').lower()
                            return sub in ('enemies','monsters','aberrations','calamities','villains','vilains') or bool(e.get('hostile'))
                        friendlies = [e for e in (t.encounter.npcs or []) if isinstance(e, dict) and not _is_enemy_e(e)]
                    except Exception:
                        friendlies = []
                    names = [str(e.get('name') or 'someone') for e in friendlies] if friendlies else [str(t.encounter.npc.get('name') or 'someone')]
                    # Build a concise list string
                    if len(names) == 1:
                        msg = f"You see {names[0]} here."
                    elif len(names) == 2:
                        msg = f"You see {names[0]} and {names[1]} here."
                    else:
                        msg = f"You see {', '.join(names[:-1])}, and {names[-1]} here."
                    # Tag based on first friendly type
                    try:
                        first = friendlies[0] if friendlies else t.encounter.npc
                        sub = str((first or {}).get('subcategory') or '').lower()
                        tag = 'ally' if sub == 'allies' else ('citizen' if sub == 'citizens' else ('animal' if sub == 'animals' else None))
                    except Exception:
                        tag = None
                    self.say(msg, tag)
                elif t.encounter.event:
                    self.mode = "event"; self.say(f"You encounter {t.encounter.event}.", 'event')
                else:
                    self.mode = "explore"
            else:
                self.mode = "explore"

    def start_dialogue(self, npc):
        self.current_npc = npc
        self.mode = "dialogue"

    def handle_dialogue_choice(self, choice: str):
        npc = self.current_npc;  nid = npc.get("id","?") if npc else "?"
        if not npc: return
        if choice == "Talk":
            self.player.affinity[nid] = self.player.affinity.get(nid,0) + 1
            # Log a simple, neutral interaction message
            self.say(f"You spoke to {npc.get('name','them')}.")
        elif choice == "Recruit":
            # Allow recruiting allies from allies.json (subcategory == 'allies')
            sub = str((npc or {}).get('subcategory') or '').lower()
            if sub == 'allies':
                self._recruit_npc_as_ally(npc)
            else:
                self.say("They are not interested in joining right now.")
        elif choice == "Insult":
            # Decrease affinity; risk souring relations
            cur = int(self.player.affinity.get(nid, 0))
            self.player.affinity[nid] = cur - 1
            self.say(f"You insult {npc.get('name','them')}.")
            # Small chance to flip to hostile in future; here we just log a warning
            self.say("They glare at you.")
        elif choice == "Flirt":
            if npc.get("romanceable"):
                chance = 0.5 + 0.05 * self.player.affinity.get(nid,0)
                if chance > 0.9: chance = 0.9
                if random.random() < chance:
                    self.player.romance_flags[nid] = True
                    self.say(f"{npc.get('name','They')} returns your smile. (Romance)")
                else:
                    self.say("Not quite the moment. Maybe build more rapport.")
            else:
                self.say("They seem unreceptive to flirtation.")
        elif choice == "Leave":
            t = self.tile(); t.encounter.npc = None; t.encounter.must_resolve = False
            self.current_npc = None; self.mode = "explore"
        else:
            self.say("You share a few words.")

    def _recruit_npc_as_ally(self, npc: Dict):
        try:
            aid = str(npc.get('id') or npc.get('name') or f"AL{len(self.party)+1:03d}")
            if any(getattr(a, 'id', None) == aid for a in self.party):
                self.say(f"{npc.get('name','They')} is already in your party.")
                return
            hp = int(npc.get('hp', 12))
            tile = None
            try:
                tile = self.tile()
            except Exception:
                tile = None
            ally = Ally(
                id=aid,
                name=str(npc.get('name') or 'Ally'),
                race=str(npc.get('race') or 'Human'),
                role=str(npc.get('role') or 'Ally'),
                level=int(npc.get('level', 1) or 1),
                hp=hp,
                max_hp=int(npc.get('max_hp', hp)),
                atk=(2,4),
                dex=int(npc.get('dex', 5) or 5),
                phy=int(npc.get('phy', 5) or 5),
                vit=int(npc.get('vit', 5) or 5),
                arc=int(npc.get('arc', 5) or 5),
                kno=int(npc.get('kno', 5) or 5),
                ins=int(npc.get('ins', 5) or 5),
                soc=int(npc.get('soc', 5) or 5),
                fth=int(npc.get('fth', 5) or 5),
                portrait=(npc.get('portrait') or npc.get('image') or npc.get('img') or npc.get('sprite') or None)
            )
            ally.home_map = str(getattr(self, 'current_map_id', None) or '') or None
            try:
                ally.home_pos = (int(getattr(tile, 'x', 0)), int(getattr(tile, 'y', 0))) if tile else None
            except Exception:
                ally.home_pos = None
            ally.home_payload = copy.deepcopy(npc)
            self.party.append(ally)
            self.say(f"{ally.name} joins your party!", 'ally')
            # Remove NPC from the tile
            try:
                self._remove_npc_from_tile(tile, npc)
                if tile and tile.encounter:
                    tile.encounter.must_resolve = False
            except Exception:
                pass
            self.current_npc = None
            self.mode = 'explore'
        except Exception:
            self.say("Recruitment failed.")

    def start_combat(self, enemy):
        # Backward-compatible single-target combat
        self.current_enemies = [enemy]
        self.current_enemies_hp = [int(enemy.get("hp", 12))]
        self.current_enemies_max_hp = [int(enemy.get("hp", 12))]
        self.current_enemy = enemy; self.current_enemy_hp = int(enemy.get("hp", 12))
        self.current_enemy.setdefault('status', [])
        self.current_enemy.setdefault('dex', 4)
        self.current_enemy.setdefault('will', 4)
        self.current_enemy.setdefault('greed', 4)
        self.can_bribe = False
        self.mode = "combat"
        # Build initiative turn order
        self._setup_initiative_order()
        # If it's not the player's turn, auto-resolve until it is (or combat ends)
        self._advance_turn(auto_only=True)

    def start_combat_group(self, enemies: List[Dict]):
        # Initialize group combat with multiple enemies
        self.current_enemies = []
        self.current_enemies_hp = []
        self.current_enemies_max_hp = []
        for e in (enemies or []):
            if not isinstance(e, dict):
                continue
            e.setdefault('status', [])
            e.setdefault('dex', 4)
            e.setdefault('will', 4)
            e.setdefault('greed', 4)
            self.current_enemies.append(e)
            try:
                hp_val = int(e.get('hp', 12))
            except Exception:
                hp_val = 12
            self.current_enemies_hp.append(hp_val)
            self.current_enemies_max_hp.append(hp_val)
        if not self.current_enemies:
            return
        self.current_enemy = self.current_enemies[0]
        self.current_enemy_hp = self.current_enemies_hp[0]
        self.can_bribe = False
        self.mode = "combat"
        # Build initiative turn order
        self._setup_initiative_order()
        self._advance_turn(auto_only=True)

    # ---------- Initiative / Turn System ----------
    def _actor_name(self, actor):
        try:
            if isinstance(actor, dict):
                return str(actor.get('name') or actor.get('id') or 'Enemy')
            return str(getattr(actor, 'name', '')) or 'Ally'
        except Exception:
            return 'Actor'

    def _actor_stat(self, actor, key: str, default: int = 5) -> int:
        try:
            if isinstance(actor, dict):
                return int(actor.get(key, default) or default)
            return int(getattr(actor, key, default))
        except Exception:
            return default

    def _setup_initiative_order(self):
        import random as _r
        order = []
        # Player
        ini = self._actor_stat(self.player, 'dex', 5) + self._actor_stat(self.player, 'ins', 5) + _r.randint(0, 2)
        order.append({'type': 'player', 'ref': self.player, 'name': self._actor_name(self.player), 'ini': int(ini)})
        # Allies
        for ally in (getattr(self, 'party', []) or []):
            if getattr(ally, 'hp', 1) <= 0:
                continue
            ini = self._actor_stat(ally, 'dex', 5) + self._actor_stat(ally, 'ins', 5) + _r.randint(0, 2)
            order.append({'type': 'ally', 'ref': ally, 'name': self._actor_name(ally), 'ini': int(ini)})
        # Enemies
        for enemy in (self.current_enemies or []):
            ini = self._actor_stat(enemy, 'dex', 4) + self._actor_stat(enemy, 'ins', 4) + _r.randint(0, 2)
            order.append({'type': 'enemy', 'ref': enemy, 'name': self._actor_name(enemy), 'ini': int(ini)})
        # Sort high to low initiative
        try:
            order.sort(key=lambda x: x.get('ini', 0), reverse=True)
        except Exception:
            pass
        self.turn_order = order
        self.turn_index = 0

    def _prune_turn_order(self):
        # Remove dead or missing actors; keep index within bounds
        alive = []
        for ent in getattr(self, 'turn_order', []) or []:
            t = ent.get('type')
            ref = ent.get('ref')
            ok = True
            if t == 'ally':
                ok = bool(ref) and getattr(ref, 'hp', 0) > 0
            elif t == 'player':
                ok = getattr(self.player, 'hp', 0) > 0
            elif t == 'enemy':
                # Enemy remains alive if it's in current_enemies list and hp>0
                idx = self._enemy_index_by_ref(ref)
                ok = (idx != -1 and int(self.current_enemies_hp[idx]) > 0)
            if ok:
                alive.append(ent)
        if not alive:
            self.turn_order = []
            self.turn_index = 0
        else:
            # Adjust index to same actor if possible
            cur = self._current_actor()
            self.turn_order = alive
            if cur in alive:
                self.turn_index = alive.index(cur)
            else:
                self.turn_index = min(self.turn_index, len(alive)-1)

    def _current_actor(self):
        try:
            if getattr(self, 'turn_order', None) and 0 <= self.turn_index < len(self.turn_order):
                return self.turn_order[self.turn_index]
        except Exception:
            pass
        return None

    @staticmethod
    def _npc_matches(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
        if a is b:
            return True
        try:
            ida = str((a or {}).get('id') or '').strip()
            idb = str((b or {}).get('id') or '').strip()
            if ida and idb:
                return ida == idb
        except Exception:
            pass
        return False

    def _remove_npc_from_tile(self, tile: Optional[Tile], npc: Optional[Dict[str, Any]]) -> None:
        if tile is None or npc is None:
            return
        enc = getattr(tile, 'encounter', None)
        if not enc:
            return
        try:
            enc.npcs = [e for e in (enc.npcs or []) if not self._npc_matches(e, npc)]
        except Exception:
            enc.npcs = list(enc.npcs or [])
        if enc.npc and self._npc_matches(enc.npc, npc):
            enc.npc = enc.npcs[0] if enc.npcs else None
        if enc.enemy and self._npc_matches(enc.enemy, npc):
            enc.enemy = None
        if not (enc.npcs or enc.items or enc.enemy or enc.event):
            tile.encounter = None

    def _place_npc_on_current_map(self, npc_payload: Optional[Dict[str, Any]], position: Optional[Tuple[int, int]]) -> bool:
        if npc_payload is None or position is None:
            return False
        try:
            x, y = int(position[0]), int(position[1])
        except Exception:
            return False
        if not (0 <= y < getattr(self, 'H', 0) and 0 <= x < getattr(self, 'W', 0)):
            return False
        try:
            tile = self.grid[y][x]
        except Exception:
            return False
        if tile.encounter is None:
            tile.encounter = Encounter()
        enc = tile.encounter
        if enc.npcs is None:
            enc.npcs = []
        else:
            enc.npcs = [e for e in enc.npcs if not self._npc_matches(e, npc_payload)]
        enc.npcs.append(copy.deepcopy(npc_payload))
        if not enc.npc:
            enc.npc = enc.npcs[0]
        return True

    def _restore_returning_allies_for_map(self, map_id: Optional[str]) -> None:
        if not map_id:
            return
        if not hasattr(self, 'returning_allies') or not isinstance(self.returning_allies, dict):
            self.returning_allies = defaultdict(list)
        key = str(map_id)
        pending = list(self.returning_allies.get(key, []))
        if not pending:
            return
        remaining: List[Dict[str, Any]] = []
        for entry in pending:
            npc_payload = entry.get('npc')
            pos = entry.get('pos')
            if npc_payload is None or pos is None:
                continue
            placed = self._place_npc_on_current_map(copy.deepcopy(npc_payload), pos)
            if not placed:
                remaining.append(entry)
        if remaining:
            self.returning_allies[key] = remaining
        else:
            self.returning_allies.pop(key, None)

    def _clone_item_by_id(self, item_id: str, hint: Optional[str] = None) -> Optional[Dict]:
        if not item_id:
            return None
        entries = []
        catalog = getattr(self, 'item_catalog', {}) or {}
        records = catalog.get(str(item_id))
        if records:
            entries.extend(records)
        if not entries and getattr(self, 'items', None):
            for base in self.items:
                if isinstance(base, dict) and str(base.get('id') or '').strip() == str(item_id):
                    entries.append(base)
        if not entries:
            return None
        if hint:
            hint_l = str(hint).lower()
            def _score(entry: Dict[str, Any]) -> int:
                score = 0
                major = item_major_type(entry).lower()
                subtype = str(item_subtype(entry)).lower()
                slot = str(entry.get('slot') or '').lower()
                eq = [str(s).lower() for s in entry.get('equip_slots') or []]
                category = str(entry.get('category') or '').lower()
                if hint_l == major:
                    score += 4
                if hint_l == category:
                    score += 3
                if hint_l == subtype:
                    score += 3
                if hint_l == slot:
                    score += 2
                if hint_l in eq:
                    score += 2
                return score
            entries.sort(key=_score, reverse=True)
            best = entries[0]
            if _score(best) <= 0 and len(entries) > 1:
                return copy.deepcopy(entries[0])
            return copy.deepcopy(entries[0])
        return copy.deepcopy(entries[0])

    def _random_base_item(self, rng: random.Random, rarity: Optional[str] = None, category: Optional[str] = None) -> Optional[Dict]:
        rarity_key = str(rarity or '').lower().strip() or None
        category_key = str(category or '').lower().strip() or None
        pool: List[Dict] = []
        for base in getattr(self, 'items', []) or []:
            if not isinstance(base, dict):
                continue
            if rarity_key and str(base.get('rarity') or '').lower() != rarity_key:
                continue
            if category_key:
                major = item_major_type(base).lower()
                btype = str(base.get('type') or '').lower()
                if category_key not in (major, btype):
                    continue
            pool.append(base)
        if rarity_key and not pool:
            pool = [base for base in (getattr(self, 'items', []) or [])
                    if isinstance(base, dict) and str(base.get('rarity') or '').lower() == rarity_key]
        if not pool:
            return None
        return copy.deepcopy(rng.choice(pool))

    def _roll_weapon_from_table(self, table_name: str, ctx_seed: str, rng: random.Random) -> Optional[Dict]:
        loot_cfg = _load_loot_config()
        table = (loot_cfg.get('drop_tables') or {}).get(table_name)
        if not table:
            return None
        weapons = table.get('weapons') or {}
        if not weapons:
            return None
        wtype = _weighted_choice([(k, v) for k, v in weapons.items()], rng)
        base_cfg = (loot_cfg.get('weapon_bases') or {}).get(wtype)
        if base_cfg:
            base = copy.deepcopy(base_cfg)
        else:
            base = self._random_base_item(rng, category='weapon') or {'category': 'weapon', 'type': wtype}
        base.setdefault('category', 'weapon')
        base.setdefault('type', wtype)
        base.setdefault('tags', base.get('tags', []))
        base['loot_table'] = table_name
        base.setdefault('name', wtype.replace('_', ' ').title())
        return self._roll_weapon_item(base, f"{ctx_seed}|table:{table_name}")

    def _generate_alias_item(self, alias_entry: Dict[str, Any], ctx_seed: str, rng: random.Random) -> Optional[Dict]:
        if not isinstance(alias_entry, dict):
            return None
        table_name = str(alias_entry.get('table') or '').strip()
        if table_name:
            rolled = self._roll_weapon_from_table(table_name, ctx_seed, rng)
            if rolled:
                return rolled
        rarity = alias_entry.get('rarity')
        category = alias_entry.get('category') or alias_entry.get('type')
        base = self._random_base_item(rng, rarity=rarity, category=category)
        if base is None and alias_entry.get('id'):
            hint = alias_entry.get('category') or alias_entry.get('type')
            base = self._clone_item_by_id(alias_entry.get('id'), hint)
        if base is None:
            return None
        for k, v in alias_entry.items():
            if k in ('rarity', 'category', 'type', 'table', 'id'):
                continue
            base[k] = copy.deepcopy(v)
        return base

    def _roll_from_mech_table(self, table_name: str, ctx_seed: str, rng: random.Random) -> Optional[Dict]:
        data = _load_mechanics_loot()
        entries = (data.get('tables') or {}).get(table_name)
        if not entries:
            return None
        picks: List[Any] = []
        weights: List[int] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pick = entry.get('pick')
            if pick is None:
                continue
            picks.append(pick)
            weights.append(int(entry.get('weight', 1) or 1))
        if not picks:
            return None
        choice = _weighted_choice(list(zip(picks, weights)), rng)
        return self._resolve_loot_reference(choice, f"{ctx_seed}|pick:{table_name}")

    def _resolve_loot_reference(self, ref: Any, ctx_seed: str) -> Optional[Dict]:
        rng = random.Random(_stable_int_hash(f"{ctx_seed}|base"))
        if isinstance(ref, dict):
            if ref.get('_rolled'):
                return copy.deepcopy(ref)
            table_name = str(ref.get('table') or '').strip()
            if table_name:
                rolled = self._roll_from_mech_table(table_name, ctx_seed, rng)
                if rolled:
                    return rolled
            alias_name = str(ref.get('alias') or '').strip()
            if alias_name:
                alias_entry = (_load_mechanics_loot().get('aliases') or {}).get(alias_name)
                base = self._generate_alias_item(alias_entry or {}, ctx_seed, rng)
                if base:
                    for k, v in ref.items():
                        if k not in ('alias', 'table'):
                            base[k] = copy.deepcopy(v)
                    return base
            base = None
            ref_id = ref.get('id')
            if ref_id:
                hint = ref.get('subcategory') or ref.get('category') or ref.get('type') or ref.get('slot')
                base = self._clone_item_by_id(ref_id, hint)
            if base is None:
                base = copy.deepcopy(ref)
            else:
                for k, v in ref.items():
                    if k == 'id':
                        continue
                    base[k] = copy.deepcopy(v)
            return base
        if isinstance(ref, str):
            catalog = getattr(self, 'item_catalog', {}) or {}
            if ref in catalog:
                entries = catalog[ref]
                if isinstance(entries, list) and entries:
                    return copy.deepcopy(entries[0])
                if isinstance(entries, dict):
                    return copy.deepcopy(entries)
            loot_cfg = _load_loot_config()
            if ref in (loot_cfg.get('drop_tables') or {}):
                return self._roll_weapon_from_table(ref, ctx_seed, rng)
            mech_loot = _load_mechanics_loot()
            alias_entry = (mech_loot.get('aliases') or {}).get(ref)
            if alias_entry:
                return self._generate_alias_item(alias_entry, ctx_seed, rng)
            if ref in (mech_loot.get('tables') or {}):
                return self._roll_from_mech_table(ref, ctx_seed, rng)
            return None
        return None

    def _finalize_loot_item(self, item: Optional[Dict], ctx_seed: str) -> Optional[Dict]:
        if not isinstance(item, dict):
            return None
        if item.get('_rolled'):
            return copy.deepcopy(item)
        try:
            major = str(item_major_type(item)).lower()
        except Exception:
            major = ''
        if major == 'weapon':
            return self._roll_weapon_item(copy.deepcopy(item), ctx_seed)
        if major in ('armour', 'armor', 'clothing', 'accessory', 'accessories'):
            return self._roll_gear_item(copy.deepcopy(item), ctx_seed)
        return copy.deepcopy(item)

    def _prepare_loot_item(self, ref: Any, tile, inv_index: int) -> Optional[Dict]:
        if isinstance(ref, dict):
            ref_sig = str(ref.get('id') or ref.get('name') or ref.get('alias') or ref.get('table') or 'dict')
        else:
            ref_sig = str(ref)
        ctx_seed = f"{getattr(self,'world_seed',0)}:{getattr(self,'current_map_id','')}:{int(getattr(tile,'x',0))},{int(getattr(tile,'y',0))}:{inv_index}:{ref_sig}"
        base = self._resolve_loot_reference(ref, ctx_seed)
        if base is None:
            return None
        return self._finalize_loot_item(base, ctx_seed)

    def _dismiss_ally_object(self, ally: Ally) -> bool:
        party = getattr(self, 'party', []) or []
        if ally not in party:
            self.say("That ally is not in your party.")
            return False
        try:
            self.party.remove(ally)
        except ValueError:
            return False
        home_map = getattr(ally, 'home_map', None)
        home_pos = getattr(ally, 'home_pos', None)
        home_payload = copy.deepcopy(getattr(ally, 'home_payload', None))
        placed = False
        if home_map and home_pos and home_payload:
            key = str(home_map)
            if key == str(getattr(self, 'current_map_id', None)):
                placed = self._place_npc_on_current_map(copy.deepcopy(home_payload), home_pos)
            if not placed:
                entry = {'npc': copy.deepcopy(home_payload), 'pos': tuple(home_pos)}
                if not hasattr(self, 'returning_allies') or not isinstance(self.returning_allies, dict):
                    self.returning_allies = defaultdict(list)
                bucket = [e for e in self.returning_allies[key]
                          if not self._npc_matches(e.get('npc'), home_payload) or tuple(e.get('pos') or ()) != tuple(home_pos)]
                bucket.append(entry)
                self.returning_allies[key] = bucket
        self.say(f"{getattr(ally,'name','An ally')} returns to their post.", 'ally')
        return True

    def dismiss_ally_by_index(self, idx: int) -> None:
        try:
            index = int(idx)
        except Exception:
            self.say("Invalid follower index.")
            return
        party = getattr(self, 'party', []) or []
        if index < 0 or index >= len(party):
            self.say("No follower at that slot.")
            return
        ally = party[index]
        if self._dismiss_ally_object(ally):
            if getattr(self, 'equip_target_idx', 0) > len(self.party):
                self.equip_target_idx = max(0, len(self.party))
            self.equip_sel_slot = None

    def dismiss_selected_ally(self) -> None:
        idx = int(getattr(self, 'equip_target_idx', 0) or 0)
        if idx <= 0:
            self.say("Select a follower first.")
            return
        self.dismiss_ally_by_index(idx - 1)

    def _enemy_index_by_ref(self, enemy_ref) -> int:
        try:
            for i, e in enumerate(self.current_enemies or []):
                if e is enemy_ref:
                    return i
        except Exception:
            return -1
        return -1

    def _sync_enemy_hp_tracking(self, idx: Optional[int] = None) -> int:
        """Ensure current_enemies_hp reflects the tracked enemy's HP."""
        if idx is None:
            idx = self._enemy_index_by_ref(self.current_enemy)
        try:
            if idx is not None and idx >= 0:
                if not hasattr(self, 'current_enemies_hp'):
                    self.current_enemies_hp = []
                while len(self.current_enemies_hp) <= idx:
                    self.current_enemies_hp.append(int(max(0, self.current_enemy_hp)))
                self.current_enemies_hp[idx] = int(max(0, self.current_enemy_hp))
        except Exception:
            pass
        return idx if idx is not None else -1

    def _enemy_max_hp_value(self, idx: Optional[int], enemy: Optional[Dict] = None) -> int:
        enemy = enemy or self.current_enemy
        if enemy is None:
            return 0
        try:
            if idx is not None and idx >= 0 and hasattr(self, 'current_enemies_max_hp'):
                if idx < len(self.current_enemies_max_hp):
                    return int(self.current_enemies_max_hp[idx])
            return int(enemy.get('hp', self.current_enemy_hp or 0) or max(1, int(self.current_enemy_hp or 0)))
        except Exception:
            try:
                return int(self.current_enemy_hp or 0)
            except Exception:
                return 0

    def _log_enemy_hp_status(self, enemy: Optional[Dict], idx: Optional[int] = None):
        if enemy is None:
            return
        idx = self._sync_enemy_hp_tracking(idx)
        try:
            if enemy is self.current_enemy:
                cur = int(max(0, self.current_enemy_hp))
            elif hasattr(self, 'current_enemies_hp') and idx is not None and 0 <= idx < len(self.current_enemies_hp):
                cur = int(max(0, self.current_enemies_hp[idx]))
            else:
                cur = int(max(0, enemy.get('hp', 0)))
        except Exception:
            cur = int(max(0, getattr(self, 'current_enemy_hp', 0)))
        max_hp = max(cur, self._enemy_max_hp_value(idx, enemy))
        try:
            name = self._actor_name(enemy)
        except Exception:
            name = 'Enemy'
        self.say(f"{name} HP: {cur}/{max_hp}")

    def select_enemy_target(self, index: int):
        """Manually choose which enemy to focus attacks on."""
        try:
            idx = int(index)
        except Exception:
            return
        if not getattr(self, 'current_enemies', None):
            return
        if idx < 0 or idx >= len(self.current_enemies):
            return
        target = self.current_enemies[idx]
        if target is self.current_enemy:
            return
        self.current_enemy = target
        try:
            if hasattr(self, 'current_enemies_hp') and idx < len(self.current_enemies_hp):
                self.current_enemy_hp = int(self.current_enemies_hp[idx])
            else:
                self.current_enemy_hp = int(target.get('hp', 0))
        except Exception:
            self.current_enemy_hp = int(target.get('hp', 0) or 0)
        self.say(f"Targeting {self._actor_name(target)}.")
        self._log_enemy_hp_status(target, idx)

    def _advance_turn(self, auto_only: bool=False):
        """Advance to next turn, auto-playing non-player turns.

        If auto_only=True, runs until it's the player's turn or combat ends without consuming a player's turn.
        """
        # End if no enemies remain
        if not getattr(self, 'current_enemies', None):
            return
        # Ensure order is clean
        self._prune_turn_order()
        if not self.turn_order:
            return
        # If called after a player's action, move to next actor
        if not auto_only:
            self.turn_index = (self.turn_index + 1) % len(self.turn_order)
        # Auto-play loop
        guard = 0
        while guard < 64:
            guard += 1
            self._prune_turn_order()
            if not self.turn_order:
                break
            actor = self._current_actor()
            if actor is None:
                break
            if actor.get('type') == 'player':
                # Wait for user input
                break
            # Perform AI action
            self._perform_actor_action(actor)
            # Check if combat ended
            if not getattr(self, 'current_enemies', None) or self.mode != 'combat' or self.current_enemy is None:
                break
            # Next actor
            self.turn_index = (self.turn_index + 1) % len(self.turn_order)

    def _perform_actor_action(self, actor):
        t = actor.get('type')
        ref = actor.get('ref')
        try:
            if t == 'ally':
                # Ally AI: attack current enemy
                if not self.current_enemy and getattr(self, 'current_enemies', None):
                    self.current_enemy = self.current_enemies[0]
                    self.current_enemy_hp = int(self.current_enemies_hp[0]) if self.current_enemies_hp else 0
                if not self.current_enemy:
                    return
                base_min, base_max = getattr(ref, 'atk', (2,4))
                wep = getattr(ref, 'equipped_weapon', None) or {}
                wmin, wmax, _, _ = _weapon_stats(wep)
                dmg = random.randint(int(base_min) + int(wmin), int(base_max) + max(int(wmax),0))
                dmg = max(1, int(dmg))
                self.current_enemy_hp -= dmg
                if self.current_enemy_hp < 0:
                    self.current_enemy_hp = 0
                idx = self._sync_enemy_hp_tracking()
                enemy_ref = self.current_enemy
                self.say(f"{self._actor_name(ref)} hits for {dmg}!")
                if enemy_ref:
                    self._log_enemy_hp_status(enemy_ref, idx)
                if self.current_enemy_hp <= 0:
                    # Remove defeated enemy
                    try: self._on_enemy_defeated(self.current_enemy)
                    except Exception: pass
                    try:
                        idx = self.current_enemies.index(self.current_enemy) if hasattr(self, 'current_enemies') else 0
                    except Exception:
                        idx = 0
                    try:
                        if hasattr(self, 'current_enemies'):
                            self.current_enemies.pop(idx)
                        if hasattr(self, 'current_enemies_hp') and len(self.current_enemies_hp) > idx:
                            self.current_enemies_hp.pop(idx)
                        if hasattr(self, 'current_enemies_max_hp') and len(self.current_enemies_max_hp) > idx:
                            self.current_enemies_max_hp.pop(idx)
                    except Exception:
                        pass
                    if getattr(self, 'current_enemies', []) and len(self.current_enemies) > 0:
                        self.current_enemy = self.current_enemies[0]
                        self.current_enemy_hp = int(self.current_enemies_hp[0] if self.current_enemies_hp else int(self.current_enemy.get('hp',12)))
                    else:
                        t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
                        self.current_enemy = None; self.mode = "explore"
            elif t == 'enemy':
                # Enemy AI: pick a random living target among player + allies
                targets = [('player', self.player)] + [(f"ally_{i}", a) for i, a in enumerate(getattr(self, 'party', [])) if getattr(a,'hp',0) > 0]
                tag, tgt = random.choice(targets)
                dmg = random.randint(2,5)
                if tag == 'player':
                    dmg = self._mitigate_incoming_damage(self.player, dmg, 'physical')
                    self.player.hp -= dmg; self.say(f"The enemy hits you for {dmg}.")
                    if self.player.hp <= 0:
                        # Enter death screen: let the player choose what to do next
                        try:
                            self.say("You fall...")
                        except Exception:
                            pass
                        # Clear immediate combat focus; show death overlay
                        try:
                            self.current_enemy = None
                        except Exception:
                            pass
                        self.mode = "death"
                else:
                    dmg = self._mitigate_incoming_damage(tgt, dmg, 'physical')
                    tgt.hp = max(0, int(getattr(tgt,'hp',0)) - dmg)
                    self.say(f"The enemy hits {getattr(tgt,'name','an ally')} for {dmg}.")
                    if tgt.hp <= 0:
                        self.say(f"{getattr(tgt,'name','An ally')} falls.")
            else:
                pass
        except Exception:
            pass

    def _maybe_apply_status(self, source: str, target: Dict, weapon_or_spell: Optional[Dict]=None):
        chance = 0.15
        pool = ["bleed","burn","shock","freeze","poison"]
        if weapon_or_spell:
            wmin, wmax, st_ch, statuses = _weapon_stats(weapon_or_spell)
            chance = st_ch or chance
            if statuses: pool = statuses
            else:
                st = item_subtype(weapon_or_spell).lower()
                if st in ('sword','dagger','axe','halberd','spear','shortsword'): pool = ["bleed"]
                if st in ('mace','club','hammer','greatclub'): pool = ["stagger"]
                if st in ('wand','staff'): pool = ["burn","shock","freeze"]
        if random.random() < chance:
            aff = random.choice(pool)
            if 'status' in target and aff not in target['status']:
                target['status'].append(aff)
                self.say(f"Status applied: {aff}.")

    # ---------- Defense (gear) helpers ----------
    def _item_defense(self, it: Optional[Dict]) -> Dict[str,int]:
        out: Dict[str,int] = {}
        if not isinstance(it, dict):
            return out
        try:
            for k, v in (it.get('defense_type') or {}).items():
                try:
                    out[str(k)] = out.get(str(k), 0) + int(v)
                except Exception:
                    pass
            # Generic defense bonus maps to physical
            b = it.get('bonus') or {}
            try:
                if 'defense' in b:
                    out['physical'] = out.get('physical', 0) + int(b.get('defense') or 0)
            except Exception:
                pass
            # Penalties (negative)
            p = it.get('penalties') or {}
            try:
                if 'defense' in p:
                    out['physical'] = out.get('physical', 0) + int(p.get('defense') or 0)
            except Exception:
                pass
        except Exception:
            pass
        return out

    def _total_defense_map(self, actor) -> Dict[str,int]:
        total: Dict[str,int] = {}
        try:
            gear = dict(getattr(actor, 'equipped_gear', {}) or {})
            # Include legacy weapon in case it carries defense
            if getattr(actor, 'equipped_weapon', None):
                gear.setdefault('weapon_main', getattr(actor, 'equipped_weapon'))
            for it in gear.values():
                d = self._item_defense(it)
                for k, v in d.items():
                    total[k] = total.get(k, 0) + int(v)
        except Exception:
            pass
        return total

    def _mitigate_incoming_damage(self, actor, raw: int, dmg_type: str = 'physical') -> int:
        """Reduce incoming damage by actor's gear defenses.

        Simple model: reduce by floor(defense/8) for matching type + half that for generic physical.
        Always leave at least 1 damage.
        """
        try:
            dm = self._total_defense_map(actor)
            d_main = int(dm.get(str(dmg_type), 0))
            if dmg_type != 'physical':
                d_phys = int(dm.get('physical', 0))
            else:
                d_phys = 0
            red = (d_main // 8) + max(0, d_phys // 16)
            return max(1, int(raw) - int(red))
        except Exception:
            return max(1, int(raw))

    # ---------- Class + Level system ----------
    def _apply_class_and_level_to_player(self, initial: bool=False, preserve_hp: bool=False):
        """Set player's base stats and growth from classes.json and current level.

        classes.json entries support keys:
        - name: class name matching player.role
        - base_stats: dict of core attributes
        - base_hp: int
        - base_atk: [min,max]
        - per_level: { hp:int, atk_min:int, atk_max:int, phy:int, dex:int, ... }
        """
        c = _class_by_name(getattr(self, 'classes', []), getattr(self.player, 'role', 'Wanderer'))
        if not c:
            return
        lvl = max(1, int(getattr(self.player, 'level', 1)))
        delta = max(0, lvl - 1)
        per = c.get('per_level') or {}
        base_stats = c.get('base_stats') or {}
        # Preserve hp ratio if requested
        hp_ratio = 1.0
        try:
            if preserve_hp and int(getattr(self.player, 'max_hp', 0)) > 0:
                hp_ratio = float(getattr(self.player, 'hp', 0)) / float(max(1, getattr(self.player, 'max_hp', 1)))
        except Exception:
            hp_ratio = 1.0
        # Core attributes
        for key in ('phy','dex','vit','arc','kno','ins','soc','fth'):
            try:
                base = int(base_stats.get(key, getattr(self.player, key, 5)))
                inc = int(per.get(key, 0)) * delta
                setattr(self.player, key, max(1, base + inc))
            except Exception:
                pass
        # HP from Vitality: max_hp = VIT * 5
        new_max_hp = max(1, int(getattr(self.player, 'vit', 5)) * 5)
        self.player.max_hp = new_max_hp
        if preserve_hp:
            self.player.hp = max(1, int(round(new_max_hp * hp_ratio)))
        else:
            self.player.hp = new_max_hp
        # Attack
        try:
            bmin, bmax = c.get('base_atk') or (self.player.atk[0], self.player.atk[1])
        except Exception:
            bmin, bmax = self.player.atk
        bmin = int(bmin) + int(per.get('atk_min', 0)) * delta
        bmax = int(bmax) + int(per.get('atk_max', 0)) * delta
        self.player.atk = (max(1, bmin), max(max(1, bmin)+1, bmax))

    def _xp_needed(self, level: int) -> int:
        return max(50, 100 * int(level))

    def gain_xp(self, amount: int):
        try:
            self.player.xp = int(getattr(self.player, 'xp', 0)) + int(amount)
            # Level-up loop
            leveled = False
            while self.player.xp >= self._xp_needed(self.player.level):
                self.player.xp -= self._xp_needed(self.player.level)
                self.player.level += 1
                leveled = True
            if leveled:
                lvl = int(self.player.level)
                self.say(f"You reached level {lvl}!")
                self._apply_class_and_level_to_player(initial=False, preserve_hp=False)
        except Exception:
            pass

    def _on_enemy_defeated(self, enemy: Optional[Dict]):
        try:
            xp = int((enemy or {}).get('xp', 25))
        except Exception:
            xp = 25
        # Award XP
        self.gain_xp(xp)
        # Remove defeated enemy from the current tile so it disappears from the map
        try:
            t = self.tile()
            enc = getattr(t, 'encounter', None)
            if enc is not None:
                # Clear direct single-enemy field when it matches
                try:
                    if getattr(enc, 'enemy', None) is enemy:
                        enc.enemy = None
                except Exception:
                    pass
                # Remove from NPC list (group encounters) by identity or ID match
                try:
                    npcs = list(getattr(enc, 'npcs', []) or [])
                    def _same_enemy(a, b) -> bool:
                        if a is b: return True
                        try:
                            return (a.get('id') and a.get('id') == (b or {}).get('id'))
                        except Exception:
                            return False
                    npcs = [n for n in npcs if not _same_enemy(n, enemy)]
                    enc.npcs = npcs
                except Exception:
                    pass
                # If no hostiles remain, allow passage
                try:
                    def _is_hostile(e):
                        try:
                            sub = str((e or {}).get('subcategory') or '').lower()
                            return sub in ('enemies','monsters','aberrations','calamities','villains','vilains') or bool((e or {}).get('hostile'))
                        except Exception:
                            return False
                    any_hostiles_left = bool(getattr(enc, 'enemy', None)) or any(_is_hostile(e) for e in (getattr(enc, 'npcs', []) or []))
                    if not any_hostiles_left:
                        enc.must_resolve = False
                        enc.spotted = False
                except Exception:
                    pass
                # If encounter has no content at all, drop it
                try:
                    if not (getattr(enc, 'enemy', None) or getattr(enc, 'npcs', None) or getattr(enc, 'npc', None) or getattr(enc, 'items', None) or getattr(enc, 'event', None)):
                        t.encounter = None
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- Weapon randomizer ----------
    def _rarity_rank(self, r: str) -> int:
        order = ["common","uncommon","rare","exotic","legendary","mythic"]
        r = str(r).lower()
        return order.index(r) if r in order else 0

    def _roll_weapon_item(self, base: Dict[str, Any], drop_context: str) -> Dict[str, Any]:
        """Return a randomized weapon derived from base, deterministically seeded by drop_context.

        Keeps schema compatibility with item helpers and combat damage via min/max fields.
        """
        try:
            seed_s = f"{int(getattr(self,'world_seed',0))}:{str(drop_context)}"
        except Exception:
            seed_s = str(drop_context)
        rng = random.Random(_stable_int_hash(seed_s))

        lvl = int(getattr(self.player, 'level', 1))
        loot_cfg = _load_loot_config()

        rarity = str(base.get('rarity') or 'common').lower()
        rarity_rules = loot_cfg.get('rarity') if loot_cfg.get('enabled') else {}
        rarity_entry = rarity_rules.get(rarity, {}) if isinstance(rarity_rules, dict) else {}
        r_mult = float(rarity_entry.get('budget', RARITY_DMG_MULT.get(rarity, 1.0)))
        base_scale = 1.0 + 0.06 * max(0, lvl)
        style = _style_for_weapon(base)
        base_type = str(base.get('type') or item_subtype(base) or 'weapon')

        base_dmg: Dict[str, int] = {}
        # Template-driven damage definitions (e.g., {"physical": [4,8]})
        template_dmg = base.get('damage_template') or base.get('damage_ranges')
        if template_dmg:
            templated = _template_map(template_dmg, rng)
            for k, v in templated.items():
                base_dmg[k] = int(base_dmg.get(k, 0)) + int(v)

        weapon_bases = loot_cfg.get('weapon_bases') or {}
        if not base_dmg and base_type in weapon_bases:
            wb = weapon_bases[base_type]
            for dmg_type, env in (wb.get('base_damage') or {}).items():
                try:
                    lo = int(env.get('min', 0))
                    hi = int(env.get('max', lo))
                except Exception:
                    lo = hi = 0
                if hi < lo:
                    lo, hi = hi, lo
                base_dmg[dmg_type] = rng.randint(lo, hi) if hi > lo else int(lo)

        if not base_dmg:
            try:
                mn, mx, *_ = _weapon_stats(base)
                avg = max(1, int((int(mn) + int(mx)) // 2))
            except Exception:
                avg = 10
            base_dmg = {"physical": int(avg)}

        dmg = _scale_damage_map(base_dmg, base_scale * r_mult)
        bonus: Dict[str,int] = dict(base.get('bonus') or {})
        template_bonus = base.get('bonus_template')
        if template_bonus:
            templated_bonus = _template_map(template_bonus, rng)
            for k, v in templated_bonus.items():
                bonus[k] = int(bonus.get(k, 0)) + int(v)
        traits: List[str] = []

        # Affixes removed per request; only base stats + enchant effects apply
        prefixes: List[Dict[str, Any]] = []
        suffixes: List[Dict[str, Any]] = []

        # Optional enchants from mechanics/enchants.json
        enchants_src = list(getattr(self, 'enchants', []) or [])
        # Filter to those that apply to weapons
        ench_pool = [e for e in enchants_src if str(e.get('applies_to','')).lower() in ('weapon','weapons')]
        rng.shuffle(ench_pool)
        # Rarity-based count
        e_counts = {
            'common': 0, 'uncommon': rng.choice([0,1]), 'rare': 1,
            'exotic': rng.choice([1,2]), 'legendary': 2, 'mythic': 2
        }
        n_en = int(e_counts.get(rarity, 0))
        sel_en = ench_pool[:max(0, n_en)] if ench_pool else []
        for en in sel_en:
            _apply_weapon_enchant_effects(dmg, bonus, traits, en.get('effect'))
        # Build combat min/max from total dmg budget
        total = max(1, int(sum(int(v) for v in dmg.values())))
        wmin = max(1, int(round(total * 0.55)))
        wmax = max(wmin+1, int(round(total * 0.95)))
        # Status hint
        statuses = []
        if 'fire' in dmg: statuses.append('burn')
        if 'ice' in dmg: statuses.append('freeze')
        if 'lightning' in dmg: statuses.append('shock')
        if 'bleed' in dmg: statuses.append('bleed')
        if 'poison' in dmg: statuses.append('poison')

        # Value/weight/trait
        val_base = int(sum(dmg.values()) * 10 + int(bonus.get('attack', 0)) * 25)
        val_mult = {"common":1.00, "uncommon":1.10, "rare":1.25, "exotic":1.50, "legendary":1.90, "mythic":2.40}.get(rarity, 1.0)
        value = int(round(val_base * float(val_mult)))
        weight = _jitter(int(item_weight(base) or base.get('base_weight') or 1000), 0.10, rng)
        trait = 'none'
        for t in traits:
            if t in ('echo_strike','lifedrink','knockback'):
                trait = t; break

        name = str(base.get('name') or _build_name(base_type, [], []))
        desc_r = rarity.title()
        rolled = {
            'category': 'weapon',
            'name': name,
            'style': style,
            'type': base_type,
            'rarity': rarity,
            'value': value,
            'weight': int(weight),
            'description': f"A {rarity} {base_type} forged to our current spec.",
            'components': [],
            'damage_type': dmg,
            'bonus': bonus,
            'weapon_trait': trait,
            'id': f"IT{rng.randrange(0, 10**8):08d}",
            'desc': f"A {rarity} {base_type} forged to our current spec.",
            # Combat fields used by _weapon_stats
            'min': int(wmin),
            'max': int(wmax),
            'status_chance': 0.15 if statuses else 0.0,
            'status': statuses,
            'enchants': [ {'id': e.get('id'), 'name': e.get('name')} for e in sel_en ] if sel_en else [],
            # Debug/marker
            '_rolled': True,
            '_base_id': base.get('id'),
            '_ctx': drop_context,
        }
        return rolled

    def _roll_gear_item(self, base: Dict[str, Any], drop_context: str) -> Dict[str, Any]:
        """Randomize non-weapon equipables (armour/clothing/accessories).

        Scales defense and adds small bonuses via affixes. Deterministic per context.
        """
        try:
            seed_s = f"{int(getattr(self,'world_seed',0))}:{str(drop_context)}"
        except Exception:
            seed_s = str(drop_context)
        rng = random.Random(_stable_int_hash(seed_s))

        lvl = int(getattr(self.player, 'level', 1))
        loot_cfg = _load_loot_config()
        rarity = str(base.get('rarity') or 'common').lower()
        rarity_rules = loot_cfg.get('rarity') if loot_cfg.get('enabled') else {}
        rarity_entry = rarity_rules.get(rarity, {}) if isinstance(rarity_rules, dict) else {}
        base_scale = 1.0 + 0.05 * max(0, lvl)
        r_mult = float(rarity_entry.get('budget', RARITY_DMG_MULT.get(rarity, 1.0)))

        style = _style_for_weapon(base)
        base_type = str(item_subtype(base) or base.get('type') or base.get('slot') or 'gear')
        base_name = item_name(base) or base_type.title()
        # Defense map fallback
        base_def = dict(base.get('defense_type') or {})
        if not base_def:
            base_def = {}
        template_def = base.get('defense_template') or base.get('defense_ranges')
        if template_def:
            templated = _template_map(template_def, rng)
            for k, v in templated.items():
                base_def[k] = int(base_def.get(k, 0)) + int(v)
        if not base_def:
            # Default tiny physical defense so items have some scale
            base_def = {"physical": 2}
        defense = _scale_damage_map(base_def, base_scale * r_mult)
        bonus: Dict[str,int] = dict(base.get('bonus') or {})
        template_bonus = base.get('bonus_template')
        if template_bonus:
            templated_bonus = _template_map(template_bonus, rng)
            for k, v in templated_bonus.items():
                bonus[k] = int(bonus.get(k, 0)) + int(v)

        # Affixes removed per request

        # Optional enchants for gear (armour/clothing/accessories)
        enchants_src = list(getattr(self, 'enchants', []) or [])
        applies = 'armour' if any(w in base_type.lower() for w in ('armour','armor','helm','head','chest','torso','legs','boots','feet','gloves','hands')) else (
                  'accessory' if any(w in base_type.lower() for w in ('ring','amulet','neck','bracelet','charm')) else (
                  'clothing'))
        ench_pool = [e for e in enchants_src if str(e.get('applies_to','')).lower() in (applies, 'gear')]
        rng.shuffle(ench_pool)
        e_counts = {
            'common': 0, 'uncommon': rng.choice([0,1]), 'rare': 1,
            'exotic': rng.choice([1,2]), 'legendary': 2, 'mythic': 2
        }
        n_en = int(e_counts.get(rarity, 0))
        sel_en = ench_pool[:max(0, n_en)] if ench_pool else []
        for en in sel_en:
            _apply_gear_enchant_effects(defense, bonus, en.get('effect'))

        # Value/weight
        val_base = int(sum(defense.values()) * 8 + sum(max(0, int(v)) for v in bonus.values()) * 20)
        val_mult = {"common":1.00, "uncommon":1.10, "rare":1.25, "exotic":1.50, "legendary":1.90, "mythic":2.40}.get(rarity, 1.0)
        value = int(round(val_base * float(val_mult)))
        weight = _jitter(int(item_weight(base) or base.get('base_weight') or 400), 0.10, rng)

        name = str(base.get('name') or base_name)

        rolled = dict(base)
        rolled.update({
            'name': name,
            'rarity': rarity,
            'value': value,
            'weight': int(weight),
            'defense_type': defense,
            'bonus': bonus,
            'enchants': [ {'id': e.get('id'), 'name': e.get('name')} for e in sel_en ] if sel_en else [],
            'id': f"IT{rng.randrange(0, 10**8):08d}",
            '_rolled': True,
            '_base_id': base.get('id'),
            '_ctx': drop_context,
        })
        return rolled

    def attack(self):
        if not self.current_enemy: return
        base_min, base_max = self.player.atk
        wep = self.player.equipped_weapon
        if not wep:
            try:
                gm = getattr(self, 'player').equipped_gear or {}
                if isinstance(gm, dict):
                    wep = gm.get('weapon_main')
            except Exception:
                wep = None
        wep = wep or {}
        wmin, wmax, _, _ = _weapon_stats(wep)
        dmg = random.randint(base_min + wmin, base_max + max(wmax,0))
        dmg = max(1, dmg)
        self.current_enemy_hp -= dmg
        if self.current_enemy_hp < 0:
            self.current_enemy_hp = 0
        idx = self._sync_enemy_hp_tracking()
        enemy_ref = self.current_enemy
        # Hide placeholder starter gear names in combat log
        label = 'your weapon' if _is_placeholder_item(wep) or not wep else item_name(wep)
        self.say(f"You strike with {label} for {dmg}.")
        if enemy_ref:
            self._log_enemy_hp_status(enemy_ref, idx)
        self._maybe_apply_status('melee', self.current_enemy, wep)
        if self.current_enemy_hp <= 0:
            self.say("Enemy defeated!")
            try: self._on_enemy_defeated(self.current_enemy)
            except Exception: pass
            try:
                idx = self.current_enemies.index(self.current_enemy) if hasattr(self, 'current_enemies') else 0
            except Exception:
                idx = 0
            # Remove defeated enemy from group
            try:
                if hasattr(self, 'current_enemies'):
                    self.current_enemies.pop(idx)
                if hasattr(self, 'current_enemies_hp') and len(self.current_enemies_hp) > idx:
                    self.current_enemies_hp.pop(idx)
                if hasattr(self, 'current_enemies_max_hp') and len(self.current_enemies_max_hp) > idx:
                    self.current_enemies_max_hp.pop(idx)
            except Exception:
                pass
            if getattr(self, 'current_enemies', []) and len(self.current_enemies) > 0:
                # Next enemy becomes current
                self.current_enemy = self.current_enemies[0]
                self.current_enemy_hp = int(self.current_enemies_hp[0] if self.current_enemies_hp else int(self.current_enemy.get('hp',12)))
            else:
                # No more enemies: clear any lingering encounter safely and return to explore
                try:
                    t = self.tile()
                    enc = getattr(t, 'encounter', None)
                    if enc is not None:
                        enc.enemy = None
                        enc.must_resolve = False
                except Exception:
                    pass
                self.current_enemy = None
                self.mode = "explore"
        # After player's action, advance initiative order (auto-play non-player turns)
        if self.mode == 'combat' and getattr(self, 'current_enemies', None):
            self._advance_turn(auto_only=False)

    def cast_spell(self):
        if not self.current_enemy:
            self.say("No target."); return
        if not self.magic:
            self.say("You don't recall any spells."); return
        spell = random.choice(self.magic)
        dmg = random.randint(4,8)
        self.current_enemy_hp -= dmg
        if self.current_enemy_hp < 0:
            self.current_enemy_hp = 0
        idx = self._sync_enemy_hp_tracking()
        enemy_ref = self.current_enemy
        # Spell cast message without focus reference
        self.say(f"You cast {spell.get('name','a spell')} for {dmg}!")
        if enemy_ref:
            self._log_enemy_hp_status(enemy_ref, idx)
        # Apply status based on current weapon if any
        self._maybe_apply_status('spell', self.current_enemy, self.player.equipped_weapon)
        if self.current_enemy_hp <= 0:
            self.say("Enemy crumples.")
            try: self._on_enemy_defeated(self.current_enemy)
            except Exception: pass
            try:
                idx = self.current_enemies.index(self.current_enemy) if hasattr(self, 'current_enemies') else 0
            except Exception:
                idx = 0
            try:
                if hasattr(self, 'current_enemies'):
                    self.current_enemies.pop(idx)
                if hasattr(self, 'current_enemies_hp') and len(self.current_enemies_hp) > idx:
                    self.current_enemies_hp.pop(idx)
                if hasattr(self, 'current_enemies_max_hp') and len(self.current_enemies_max_hp) > idx:
                    self.current_enemies_max_hp.pop(idx)
            except Exception:
                pass
            if getattr(self, 'current_enemies', []) and len(self.current_enemies) > 0:
                self.current_enemy = self.current_enemies[0]
                self.current_enemy_hp = int(self.current_enemies_hp[0] if self.current_enemies_hp else int(self.current_enemy.get('hp',12)))
            else:
                t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
                self.current_enemy = None; self.mode = "explore"
        # After player's action, advance initiative order (auto-play non-player turns)
        if self.mode == 'combat' and getattr(self, 'current_enemies', None):
            self._advance_turn(auto_only=False)

    def party_attack_round(self):
        """Each ally attacks the current enemy once, in order."""
        if not getattr(self, 'party', None):
            return
        if not self.current_enemy:
            return
        for ally in list(self.party):
            try:
                if getattr(ally, 'hp', 0) <= 0:
                    continue
                base_min, base_max = getattr(ally, 'atk', (2,4))
                wep = getattr(ally, 'equipped_weapon', None) or {}
                wmin, wmax, _, _ = _weapon_stats(wep)
                dmg = random.randint(int(base_min) + int(wmin), int(base_max) + max(int(wmax),0))
                dmg = max(1, int(dmg))
                self.current_enemy_hp -= dmg
                if self.current_enemy_hp < 0:
                    self.current_enemy_hp = 0
                idx = self._sync_enemy_hp_tracking()
                enemy_ref = self.current_enemy
                self.say(f"{getattr(ally,'name','Ally')} hits for {dmg}!")
                if enemy_ref:
                    self._log_enemy_hp_status(enemy_ref, idx)
                if self.current_enemy_hp <= 0:
                    # Reuse player defeat handling path
                    try: self._on_enemy_defeated(self.current_enemy)
                    except Exception: pass
                    try:
                        idx = self.current_enemies.index(self.current_enemy) if hasattr(self, 'current_enemies') else 0
                    except Exception:
                        idx = 0
                    try:
                        if hasattr(self, 'current_enemies'):
                            self.current_enemies.pop(idx)
                        if hasattr(self, 'current_enemies_hp') and len(self.current_enemies_hp) > idx:
                            self.current_enemies_hp.pop(idx)
                        if hasattr(self, 'current_enemies_max_hp') and len(self.current_enemies_max_hp) > idx:
                            self.current_enemies_max_hp.pop(idx)
                    except Exception:
                        pass
                    if getattr(self, 'current_enemies', []) and len(self.current_enemies) > 0:
                        self.current_enemy = self.current_enemies[0]
                        self.current_enemy_hp = int(self.current_enemies_hp[0] if self.current_enemies_hp else int(self.current_enemy.get('hp',12)))
                    else:
                        t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
                        self.current_enemy = None; self.mode = "explore"
                    break
            except Exception:
                pass

    def try_sneak(self):
        t = self.tile()
        if not (t.encounter and t.encounter.enemy and not t.encounter.spotted):
            self.say("No unnoticed enemy to sneak by."); return
        dc = 8 + random.randint(0,4); roll = 4 + random.randint(1,10)
        if roll >= dc:
            self.say("You slip past unnoticed.")
            t.encounter.enemy = None
            t.encounter.must_resolve = False
            self.mode = "explore"
        else:
            self.say("You stumble-you're spotted!"); t.encounter.spotted = True; self.start_combat(t.encounter.enemy)

    def bypass_enemy(self):
        t = self.tile()
        if t.encounter and t.encounter.enemy and not t.encounter.spotted:
            self.say("You give the area a wide berth. (You can leave now.)")
            t.encounter.must_resolve = False
            self.mode = "explore"
        else:
            self.say("Too risky to bypass.")

    def avoid_enemy(self):
        """Combined action for avoiding an enemy: choose sneak or bypass.

        If the enemy is unaware, prefer a sneak attempt when the player's
        stealth is decent; otherwise skirt around safely.
        """
        t = self.tile()
        if not (t.encounter and t.encounter.enemy and not t.encounter.spotted):
            self.say("Too risky to avoid."); return
        try:
            tech = int(getattr(self.player, 'dex', 0))
        except Exception:
            tech = 0
        # Heuristic: try to sneak if Technique (DEX) >= 5, else bypass safely
        if tech >= 5:
            self.try_sneak()
        else:
            self.bypass_enemy()

    def talk_enemy(self):
        if not self.current_enemy: return
        will = int(self.current_enemy.get('will', 4))
        chance = max(0.1, min(0.8, 0.5 - 0.05*(will-4) + 0.05*len(self.player.romance_flags)))
        if random.random() < chance:
            self.say("You talk them down. The hostility fades (for now).")
            # Keep encounter on tile, but clear forced blocking and awareness
            t = self.tile()
            try:
                if t.encounter:
                    t.encounter.must_resolve = False
                    t.encounter.spotted = False
            except Exception:
                pass
            # Exit combat to exploration; do not delete the enemy
            self.current_enemy = None
            self.mode = "explore"
            self.can_bribe = False
        else:
            self.say("They waver... maybe a bribe would help.")
            self.can_bribe = True
            # Advance turn if still in combat
            if self.mode == 'combat' and getattr(self, 'current_enemies', None):
                self._advance_turn(auto_only=False)

    def offer_bribe(self):
        if not self.current_enemy:
            self.say("No one to bribe."); return
        greed = int(self.current_enemy.get('greed', 4))
        chance = max(0.2, min(0.9, 0.6 + 0.05*(greed-4)))
        item = None
        for it in self.player.inventory:
            if item_type(it).lower() in ('trinket','material','accessory','materials'):
                item = it; break
        if item:
            self.player.inventory.remove(item)
            self.say(f"You offer {item_name(item)}...")
        else:
            self.say("You offer future favors...")
        if random.random() < chance:
            self.say("The bribe works. They let you pass.")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
            self.current_enemy = None; self.mode = "explore"; self.can_bribe = False
        else:
            self.say("No deal. They remain hostile.")
            self.can_bribe = False
            # Advance turn if still in combat
            if self.mode == 'combat' and getattr(self, 'current_enemies', None):
                self._advance_turn(auto_only=False)

    def flee(self):
        if not self.current_enemy: return
        pDex = int(self.player.dex); eDex = int(self.current_enemy.get('dex',4))
        chance = max(0.1, min(0.95, 0.35 + 0.08*(pDex - eDex)))
        if random.random() < chance:
            self.say("You slip away into the brush.")
            # Leave encounter intact but no longer blocking or alerted
            try:
                t = self.tile()
                if t.encounter:
                    t.encounter.must_resolve = False
                    t.encounter.spotted = False
            except Exception:
                pass
            self.current_enemy = None
            self.mode = "explore"
            # Small move away to adjacent tile if possible
            if self.player.y+1 < getattr(self, 'H', 8): self.player.y += 1
        else:
            self.say("You fail to escape!")
            # Failed flee consumes the player's turn
            if self.mode == 'combat' and getattr(self, 'current_enemies', None):
                self._advance_turn(auto_only=False)

    def enemy_turn(self):
        if not self.current_enemy: return
        # Pick a random target among player + alive allies
        targets = [('player', self.player)] + [(f"ally_{i}", a) for i, a in enumerate(getattr(self, 'party', [])) if getattr(a,'hp',0) > 0]
        tag, tgt = random.choice(targets)
        dmg = random.randint(2,5)
        if tag == 'player':
            dmg = self._mitigate_incoming_damage(self.player, dmg, 'physical')
            self.player.hp -= dmg; self.say(f"The enemy hits you for {dmg}.")
            if self.player.hp <= 0:
                # Enter death screen: let the player choose what to do next
                try:
                    self.say("You fall...")
                except Exception:
                    pass
                try:
                    self.current_enemy = None
                except Exception:
                    pass
                self.mode = "death"
        else:
            dmg = self._mitigate_incoming_damage(tgt, dmg, 'physical')
            tgt.hp = max(0, int(getattr(tgt,'hp',0)) - dmg)
            self.say(f"The enemy hits {getattr(tgt,'name','an ally')} for {dmg}.")
            if tgt.hp <= 0:
                self.say(f"{getattr(tgt,'name','An ally')} falls.")

    def search_tile(self):
        t = self.tile()
        if not t.encounter:
            self.say("You find little of note."); return
        items = list(getattr(t.encounter, 'items', []) or [])
        if not items:
            t.encounter.item_searched = True
            self.say("You search thoroughly, but find nothing."); return
        # Loot one item per search
        raw_item = items.pop(0)
        item = self._prepare_loot_item(raw_item, t, len(self.player.inventory))
        if item is None:
            self.say("The loot crumbles to dust.")
            t.encounter.items = items
            if not t.encounter.items:
                t.encounter.item_searched = True
            return
        t.encounter.items = items
        self.player.inventory.append(item)
        # Tag quests for orange recent text
        tag = 'quest_item' if item_is_quest(item) else 'item'
        self.say(f"You found: {item_name(item)}!", tag)
        if not t.encounter.items:
            t.encounter.item_searched = True

# ======================== Start game (UI) ========================
def start_game(start_map: Optional[str]=None, start_entry: Optional[str]=None, start_pos: Optional[Tuple[int,int]]=None, load_slot: Optional[int]=None, char_config: Optional[Dict[str, Any]] = None):
    global pg
    if pg is None:
        try:
            import pygame as _pg  # late import to show friendly error
            pg = _pg
        except ImportError:
            print("[ERR] pygame not installed. Run: pip install pygame")
            sys.exit(1)

    version = get_version()
    pg.init()
    pg.display.set_caption(f"RPGenesis {version} - Text RPG")
    # Reuse existing window if present to preserve size/flags
    screen = pg.display.get_surface()
    if screen is None:
        # First launch: create a window and maximize
        screen = pg.display.set_mode((1120, 700), pg.RESIZABLE)
        try:
            import ctypes
            hwnd = pg.display.get_wm_info().get('window')
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        except Exception:
            pass
    clock = pg.time.Clock()

    game = Game(start_map=start_map, start_entry=start_entry, start_pos=start_pos, char_config=char_config)
    if load_slot is not None:
        try:
            game.load_from_slot(int(load_slot))
        except Exception:
            pass
    running = True
    _next_action = None  # None | 'menu'
    while running:
        dt = clock.tick(60)
        # accumulate playtime
        try:
            game.playtime_ms = int(getattr(game, 'playtime_ms', 0)) + int(dt)
        except Exception:
            pass
        # Check for programmatic requests (e.g., death screen -> main menu)
        if getattr(game, '_req_main_menu', False):
            try:
                game._req_main_menu = False
            except Exception:
                pass
            _next_action = 'menu'
            running = False
            break
        for event in pg.event.get():
            if event.type == pg.QUIT:
                running = False
            elif event.type == pg.VIDEORESIZE:
                # Preserve current flags (fullscreen vs resizable)
                try:
                    f = screen.get_flags() if screen else 0
                except Exception:
                    f = 0
                if f & pg.FULLSCREEN:
                    screen = pg.display.set_mode((event.w, event.h), pg.FULLSCREEN)
                else:
                    screen = pg.display.set_mode((event.w, event.h), pg.RESIZABLE)
            elif event.type == pg.MOUSEWHEEL:
                # Scroll right panel content when hovered
                win_w, win_h = screen.get_size()
                panel_w = int(PANEL_W_FIXED)
                x0 = max(0, win_w - panel_w)
                content_top = 44
                # Use dynamic top boundary if available so scroll area matches visible content
                buttons_top = int(getattr(game, '_buttons_top', win_h - 210))
                view_h = max(0, buttons_top - content_top)
                mx, my = pg.mouse.get_pos()
                if x0 <= mx <= win_w and content_top <= my < buttons_top:
                    if not hasattr(game, 'ui_scroll'):
                        game.ui_scroll = 0
                    game.ui_scroll -= event.y * 24
                    # Clamp using last known bounds
                    mxs = max(0, int(getattr(game, 'ui_scroll_max', 0)))
                    if game.ui_scroll < 0: game.ui_scroll = 0
                    if game.ui_scroll > mxs: game.ui_scroll = mxs
                # Database list uses paging; no wheel scroll needed here
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE: 
                    if game.mode in ("inventory", "equip", "database", "save", "load"):
                        game.mode = "explore"
                    else:
                        running = False
                elif game.mode == 'database' and bool(getattr(game,'db_filter_focus', False)):
                    # Text input for database filter
                    if event.key == pg.K_RETURN:
                        game.db_filter_focus = False
                    elif event.key == pg.K_BACKSPACE:
                        try:
                            game.db_query = (game.db_query[:-1]) if game.db_query else ''
                        except Exception:
                            game.db_query = ''
                    else:
                        ch = getattr(event, 'unicode', '')
                        try:
                            if ch and ch.isprintable():
                                if len(game.db_query) < 128:
                                    game.db_query += ch
                        except Exception:
                            pass
                elif event.key in (pg.K_w, pg.K_UP):    game.move(0,-1)
                elif event.key in (pg.K_s, pg.K_DOWN):  game.move(0,1)
                elif event.key in (pg.K_a, pg.K_LEFT):  game.move(-1,0)
                elif event.key in (pg.K_d, pg.K_RIGHT): game.move(1,0)
                elif event.key == pg.K_i:
                    if game.mode != "inventory":
                        game.open_overlay('inventory')
                    else:
                        game.close_overlay()
            elif event.type == pg.MOUSEBUTTONDOWN:
                for b in draw_panel(screen, game):
                    b.handle(event)
        screen.fill((16,16,22))
        draw_grid(screen, game)
        draw_panel(screen, game)
        pg.display.flip()
    pg.quit()
    # Handle post-loop action (e.g., return to main menu)
    if _next_action == 'menu':
        sel, data = start_menu()
        if sel == 'new':
            if isinstance(data, dict):
                start_game(start_map=start_map, start_entry=start_entry, start_pos=start_pos, char_config=data)
            else:
                start_game(start_map=start_map, start_entry=start_entry, start_pos=start_pos)
        elif sel == 'load' and data is not None:
            start_game(load_slot=int(data))
        return


def _list_all_save_slots_sorted() -> List[Tuple[int, Optional[Dict[str, Any]]]]:
    """Return all slot*.json under SAVE_DIR sorted by timestamp desc.

    If timestamp missing, sort by slot number descending as fallback.
    """
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    out: List[Tuple[int, Optional[Dict[str, Any]]]] = []
    try:
        for fn in os.listdir(SAVE_DIR):
            if not fn.lower().startswith('slot') or not fn.lower().endswith('.json'):
                continue
            try:
                num = int(re.sub(r"\D", "", fn))
            except Exception:
                continue
            path = SAVE_DIR / fn
            data = None
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = None
            out.append((num, data))
    except Exception:
        pass
    def key(v):
        num, data = v
        ts = ''
        try:
            ts = str((data or {}).get('timestamp') or '')
        except Exception:
            ts = ''
        # Sort by timestamp desc primarily, then by slot number desc
        return (ts or ''), f"{num:08d}"
    out.sort(key=key, reverse=True)
    return out


def _latest_save_slot() -> Optional[int]:
    lst = _list_all_save_slots_sorted()
    return int(lst[0][0]) if lst else None


def start_menu():
    """Main menu loop: returns ('new', None) or ('load', slot) or ('quit', None)."""
    global pg
    if pg is None:
        try:
            import pygame as _pg
            pg = _pg
        except ImportError:
            print("[ERR] pygame not installed. Run: pip install pygame"); sys.exit(1)
    version = get_version()
    pg.init()
    pg.display.set_caption(f"RPGenesis {version} - Main Menu")
    screen = pg.display.set_mode((1120, 700), pg.RESIZABLE)
    try:
        import ctypes; hwnd = pg.display.get_wm_info().get('window');
        if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 3)
    except Exception: pass
    clock = pg.time.Clock()

    # Preload logo
    logo = None
    try:
        lp = os.path.join(ROOT, 'assets', 'images', 'icons', 'main_logo.png')
        if os.path.exists(lp):
            logo = pg.image.load(lp).convert_alpha()
    except Exception:
        logo = None

    mm_mode = 'menu'  # menu | load | options | info | credits | database | char_create
    # Load options
    def _opts_path():
        return UI_DIR / 'options.json'
    def _load_opts():
        try:
            if (_opts_path()).exists():
                with open(_opts_path(), 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {'fullscreen': False, 'music_vol': 100, 'sfx_vol': 100}
    def _save_opts(o):
        try:
            UI_DIR.mkdir(parents=True, exist_ok=True)
            with open(_opts_path(), 'w', encoding='utf-8') as f:
                json.dump(o, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    opts = _load_opts()
    # Lightweight state holder for Database when launched from main menu
    class _DBState:
        pass
    db_state: Optional[_DBState] = None
    load_page = 0
    running = True
    while running:
        dt = clock.tick(60)
        screen.fill((16,16,22))

        win_w, win_h = screen.get_size()
        panel = pg.Rect(0, 0, win_w, win_h)

        # Draw logo centered top
        top_y = 40
        if logo is not None:
            lw, lh = logo.get_size()
            max_w = int(win_w * 0.6)
            scale = min(1.0, max_w / max(1, lw))
            if scale != 1.0:
                lg = pg.transform.smoothscale(logo, (int(lw*scale), int(lh*scale)))
            else:
                lg = logo
            screen.blit(lg, lg.get_rect(midtop=(win_w//2, top_y)))
            top_y += lg.get_height() + 20
        else:
            top_y += 20

        buttons: List[Button] = []
        def add_btn(label, cb):
            nonlocal top_y
            r = pg.Rect(win_w//2 - 180, top_y, 360, 40)
            buttons.append(Button(r, label, cb))
            top_y += 48

        if mm_mode == 'menu':
            add_btn("New Game", lambda: (_start.set('new')))
            latest = _latest_save_slot()
            if latest is not None:
                add_btn("Continue Game", lambda slot=latest: (_start.set(('load', slot))))
            else:
                add_btn("Continue Game (no saves)", lambda: None)
            add_btn("Load Game", lambda: (_mode.set('load')))
            add_btn("Database", lambda: (_mode.set('database')))
            add_btn("Options", lambda: (_mode.set('options')))
            add_btn("Info",    lambda: (_mode.set('info')))
            add_btn("Credits", lambda: (_mode.set('credits')))
        elif mm_mode in ('info','credits'):
            title = {'info':'Info','credits':'Credits'}[mm_mode]
            f = pg.font.Font(None, 28)
            screen.blit(f.render(title, True, (230,230,240)), (win_w//2 - 40, top_y))
            top_y += 40
            f2 = pg.font.Font(None, 20)
            msg = (
                "RPGenesis-Fantasy: WASD/Arrows move, I inventory. Press ESC to return." if mm_mode=='info' else
                "Created by You. Press ESC to return."
            )
            draw_text(screen, msg, (win_w//2 - 240, top_y), max_w=480, font=f2)
        elif mm_mode == 'options':
            f = pg.font.Font(None, 28)
            screen.blit(f.render('Options', True, (230,230,240)), (win_w//2 - 40, top_y))
            top_y += 40
            # Fullscreen toggle
            fs_label = f"Fullscreen: {'On' if opts.get('fullscreen') else 'Off'}"
            buttons.append(Button(pg.Rect(win_w//2 - 180, top_y, 360, 36), fs_label, lambda: (_mode.set('toggle_fs')))); top_y += 44
            # Music/SFX volumes
            volf = pg.font.Font(None, 22)
            mv = int(opts.get('music_vol', 100)); sv = int(opts.get('sfx_vol', 100))
            draw_text(screen, f"Music Volume: {mv}", (win_w//2 - 120, top_y), font=volf); 
            buttons.append(Button(pg.Rect(win_w//2 - 180, top_y-4, 40, 32), "-", lambda: (_mode.set('mv-'))))
            buttons.append(Button(pg.Rect(win_w//2 + 120, top_y-4, 40, 32), "+", lambda: (_mode.set('mv+')))); top_y += 40
            draw_text(screen, f"SFX Volume: {sv}", (win_w//2 - 120, top_y), font=volf);
            buttons.append(Button(pg.Rect(win_w//2 - 180, top_y-4, 40, 32), "-", lambda: (_mode.set('sv-'))))
            buttons.append(Button(pg.Rect(win_w//2 + 120, top_y-4, 40, 32), "+", lambda: (_mode.set('sv+')))); top_y += 40
        elif mm_mode == 'load':
            # Paginated list of saves, most recent first
            saves = _list_all_save_slots_sorted()
            per_page = 6
            total_pages = max(1, (len(saves) + per_page - 1)//per_page)
            load_page = max(0, min(load_page, total_pages-1))
            start = load_page * per_page
            page_saves = saves[start:start+per_page]
            # Grid 2x3
            pad = 16
            grid_w = min(880, int(win_w*0.8))
            cell_w = (grid_w - pad*3)//2
            cell_h = 120
            left_x = (win_w - grid_w)//2
            y0 = top_y
            for i, (slot, data) in enumerate(page_saves):
                c = i % 2; r = i // 2
                x = left_x + pad + c*(cell_w + pad)
                y = y0 + pad + r*(cell_h + pad)
                rect = pg.Rect(x, y, cell_w, cell_h)
                _render_slot_card(screen, rect, slot, data)
                buttons.append(Button(rect, "", lambda s=slot: (_start.set(('load', s))), draw_bg=False))
            # Pager
            by = y0 + pad + 3*(cell_h + pad)
            prev_r = pg.Rect(win_w//2 - 170, by, 140, 32)
            next_r = pg.Rect(win_w//2 + 30,  by, 140, 32)
            buttons.append(Button(prev_r, "Prev Page", lambda: (_page.set(load_page-1))))
            buttons.append(Button(next_r, "Next Page", lambda: (_page.set(load_page+1))))
        elif mm_mode == 'char_create':
            # Character creation simple form
            if not hasattr(start_menu, '_cc_state'):
                races_doc = load_races_list() or []
                classes = load_classes_list() or []
                # Keep race objects and group them by main race (race_group)
                race_objs: List[Dict] = [r for r in races_doc if isinstance(r, dict)]
                group_map: Dict[str, List[Dict]] = {}
                for r in race_objs:
                    grp = str(r.get('race_group') or r.get('group') or '').strip()
                    if not grp:
                        grp = str(r.get('name') or r.get('id') or 'Other')
                    group_map.setdefault(grp, []).append(r)
                race_groups: List[str] = list(group_map.keys()) or ['Race']
                # Build initial subrace names for the first group
                init_group = race_groups[0]
                init_subs = group_map.get(init_group, [])
                init_sub_names: List[str] = [ (s.get('name') or s.get('id') or init_group) for s in init_subs ]
                start_menu._cc_state = {
                    'first_name': '',
                    'last_name': '',
                    'backstory': '',
                    'race_groups': race_groups,
                    'race_group_idx': 0,
                    'race_group_map': group_map,
                    'subrace_names': init_sub_names,
                    'subrace_idx': 0,
                    'race_objs': race_objs,
                    'classes':[ (c.get('name') or c.get('id') or 'Wanderer') for c in classes ] or ['Wanderer'],
                    'race_idx': 0, 'class_idx': 0,
                    # Appearance option lists and selections
                    'hair_colors': [], 'skin_tones': [], 'eye_colors': [],
                    'hair_idx': 0, 'skin_idx': 0, 'eye_idx': 0,
                    # New: hair style and length options
                    'hair_lengths': [
                        'Bald', 'Very Short', 'Short', 'Medium', 'Long', 'Very Long', 'Knee Length'
                    ],
                    'hair_style_map': {
                        'Bald': ['None'],
                        'Very Short': [
                            'Buzz Cut', 'Crew Cut', 'Caesar', 'Crop', 'Very Short Curls', 'Faux Hawk',
                            'Ivy League', 'High and Tight'
                        ],
                        'Short': [
                            'Pixie', 'Short Bob', 'Side Part', 'Undercut', 'Quiff', 'Short Curls',
                            'Pompadour', 'Finger Waves'
                        ],
                        'Medium': [
                            'Loose', 'Wavy', 'Curly', 'Ponytail', 'Half-Up', 'Low Bun', 'Braided Crown',
                            'Mohawk', 'Undercut', 'Bob', 'Layered', 'French Twist', 'Space Buns', 'Shag'
                        ],
                        'Long': [
                            'Loose', 'Wavy', 'Curly', 'Ponytail', 'Braided', 'French Braid', 'Fishtail Braid',
                            'Low Bun', 'High Bun', 'Top Knot', 'Half-Up', 'Dreadlocks',
                            'Side Braid', 'Dutch Braid', 'Braided Ponytail', 'Braided Bun'
                        ],
                        'Very Long': [
                            'Loose', 'Wavy', 'Curly', 'Ponytail', 'Braided', 'French Braid', 'Fishtail Braid',
                            'Twin Braids', 'Low Bun', 'High Bun', 'Top Knot', 'Half-Up', 'Dreadlocks',
                            'Waterfall Braid', 'Rope Braid', 'Gibson Tuck', 'Side Ponytail'
                        ],
                        'Knee Length': [
                            'Loose', 'Braided', 'Fishtail Braid', 'Twin Braids', 'Low Bun', 'Half-Up', 'Dreadlocks',
                            'Giant Braid', 'Coiled Bun', 'Rope Braid'
                        ]
                    },
                    'hair_style_idx': 0,
                    # Fallback style list if mapping not found (should rarely be used)
                    'hair_styles': [
                        'Loose', 'Braided', 'Ponytail', 'Bun', 'Curly', 'Wavy', 'Straight', 'Top Knot',
                        'Side Braid', 'Dutch Braid', 'Space Buns', 'French Twist', 'Layered', 'Shag'
                    ],
                    'hair_length_idx': 0,
                    'open_dd': None,
                    'focus': 'first_name',
                }
            st = start_menu._cc_state
            # Reset per-frame dropdown helpers
            st['_dd_buttons'] = []
            st['_dd_mask'] = None
            st['_dd_geom'] = None
            # Ensure classes list stays in sync with data/mechanics/classes.json
            def _refresh_classes_if_needed():
                try:
                    docs = load_classes_list() or []
                    new_names = [ (c.get('name') or c.get('id') or 'Wanderer') for c in docs if isinstance(c, dict) ]
                    cur = list(st.get('classes') or [])
                    # Always keep class_objs in sync
                    st['class_objs'] = [c for c in docs if isinstance(c, dict)]
                    if not cur and new_names:
                        st['classes'] = new_names
                    elif new_names and new_names != cur:
                        st['classes'] = new_names
                    if new_names:
                        st['class_idx'] = 0 if not isinstance(st.get('class_idx'), int) else max(0, min(st['class_idx'], len(new_names)-1))
                except Exception:
                    pass
            _refresh_classes_if_needed()
            # Modal
            # Larger, responsive modal: ~94% x 92% of window, clamped inside with margins
            modal_w = min(int(win_w * 0.94), max(200, win_w - 40)); modal_h = min(int(win_h * 0.92), max(200, win_h - 40))
            modal = pg.Rect((win_w-modal_w)//2, (win_h-modal_h)//2, modal_w, modal_h)
            dim = pg.Surface((win_w, win_h), pg.SRCALPHA); dim.fill((10,10,14,160)); screen.blit(dim, (0,0))
            pg.draw.rect(screen, (24,26,34), modal, border_radius=10)
            pg.draw.rect(screen, (96,102,124), modal, 2, border_radius=10)
            title = pg.font.Font(None, 30).render('Character Creation', True, (235,235,245))
            screen.blit(title, (modal.x + 16, modal.y + 12))
            content = modal.inflate(-40, -60)
            x0, y0 = content.x + 12, content.y + 12
            labf = pg.font.Font(None, 22); valf = pg.font.Font(None, 24)
            # Helpers to parse appearance options from race objects
            def _to_str_list(v) -> List[str]:
                try:
                    if isinstance(v, list):
                        out = []
                        for it in v:
                            if isinstance(it, str):
                                out.append(it)
                            elif isinstance(it, dict):
                                nm = it.get('name') or it.get('id') or it.get('label')
                                if isinstance(nm, str): out.append(nm)
                        return [s for s in out if isinstance(s, str) and s.strip()]
                    if isinstance(v, dict):
                        for k in ('colors','options','list','values'):
                            if k in v:
                                return _to_str_list(v.get(k))
                except Exception:
                    pass
                return []
            def _find_list(obj: Dict, keys: List[str]) -> List[str]:
                if not isinstance(obj, dict):
                    return []
                # direct
                for k in keys:
                    v = obj.get(k)
                    lst = _to_str_list(v)
                    if lst: return lst
                # nested 'appearance'
                ap = obj.get('appearance')
                if isinstance(ap, dict):
                    for k in keys:
                        lst = _to_str_list(ap.get(k))
                        if lst: return lst
                return []
            def _rebuild_opts():
                # Update subrace list for current group and appearance options from selected subrace
                grp_names = list(st.get('race_groups') or [])
                grp_idx = max(0, min(int(st.get('race_group_idx',0)), max(0, len(grp_names)-1)))
                grp = grp_names[grp_idx] if grp_names else ''
                gmap: Dict[str, List[Dict]] = st.get('race_group_map') or {}
                subs: List[Dict] = gmap.get(grp, [])
                sub_names: List[str] = [ (s.get('name') or s.get('id') or grp) for s in subs ]
                st['subrace_names'] = sub_names
                st['subrace_idx'] = max(0, min(int(st.get('subrace_idx',0)), max(0, len(sub_names)-1)))
                # Selected subrace object
                race_obj = subs[st['subrace_idx']] if subs else None
                hair = _find_list(race_obj or {}, ['hair_colour','hair_color','hair_colors','hair_colours','hairColor','hair-colors','hair','hair_options'])
                skin = _find_list(race_obj or {}, ['skin_tone','skin_tones','skin_color','skin_colors','skin_colours','skin','complexion','skinOptions','skinTone'])
                eyes = _find_list(race_obj or {}, ['eye_color','eye_colors','eye_colour','eye_colours','eyes','eye','eye_options','eyeColors','eyeColor'])
                st['hair_colors'] = hair
                st['skin_tones'] = skin
                st['eye_colors'] = eyes
                st['hair_idx'] = 0 if not isinstance(st.get('hair_idx'), int) else max(0, min(st['hair_idx'], max(0, len(hair)-1)))
                st['skin_idx'] = 0 if not isinstance(st.get('skin_idx'), int) else max(0, min(st['skin_idx'], max(0, len(skin)-1)))
                st['eye_idx']  = 0 if not isinstance(st.get('eye_idx'),  int) else max(0, min(st['eye_idx'],  max(0, len(eyes)-1)))
            # Ensure appearance options reflect the current race
            if not getattr(start_menu, '_cc_opts_built', False):
                _rebuild_opts(); start_menu._cc_opts_built = True
            def field(label, key, w=360):
                nonlocal y0
                screen.blit(labf.render(label, True, (220,220,230)), (x0, y0))
                box = pg.Rect(x0+180, y0-2, w, 28)
                pg.draw.rect(screen, (36,38,48), box, border_radius=6)
                pg.draw.rect(screen, (96,102,124) if st['focus']==key else (70,74,92), box, 1, border_radius=6)
                txt = valf.render(str(st.get(key,'')[:64]), True, (230,230,240))
                screen.blit(txt, (box.x+8, box.y+4))
                buttons.append(Button(box, '', lambda k=key: (st.__setitem__('focus', k)), draw_bg=False))
                y0 += 36
            # Helper: class color by highest default stat
            # Removed class colorization per user request

            # Simple dropdown widget for selection lists
            def dropdown(label, items: List[str], idx_key: str, close_key: Optional[str]=None, w=280):
                nonlocal y0
                screen.blit(labf.render(label, True, (220,220,230)), (x0, y0))
                box = pg.Rect(x0+180, y0-2, w, 28)
                pg.draw.rect(screen, (36,38,48), box, border_radius=6)
                # Dim other dropdowns if some dropdown is open (disabled state)
                disabled = bool(st.get('open_dd')) and st.get('open_dd') != idx_key
                pg.draw.rect(screen, (60,62,72) if disabled else (70,74,92), box, 1, border_radius=6)
                cur_idx = max(0, min(int(st.get(idx_key,0)), max(0, len(items)-1))) if items else 0
                cur = items[cur_idx] if items else ''
                label_surf = valf.render(str(cur), True, (230,230,240))
                screen.blit(label_surf, (box.x+8, box.y+4))
                # Dropdown indicator
                tri = valf.render('v', True, (200,200,210))
                screen.blit(tri, (box.right - 22, box.y + 2))
                def _toggle():
                    # Only open if there are items to show
                    if st.get('open_dd') == idx_key:
                        st['open_dd'] = None
                    else:
                        # Block opening another dropdown while one is open
                        if not bool(st.get('open_dd')) and items:
                            st['open_dd'] = idx_key
                            st['dd_scroll'] = 0
                buttons.append(Button(box, '', _toggle, draw_bg=False))
                open_now = (st.get('open_dd') == idx_key)
                # Defer drawing and event binding for the open dropdown to the end,
                # so it appears on top and captures clicks exclusively.
                if open_now and items:
                    max_show = 8
                    item_h = 24
                    vis = min(max_show, len(items))
                    total_h = vis*item_h + 8
                    dd_w = w
                    top = box.bottom + 4
                    if top + total_h > content.bottom - 6:
                        top = box.top - 4 - total_h
                    dd_rect = pg.Rect(box.x, top, dd_w, total_h)
                    # Save geom to be drawn after all other widgets
                    st['_dd_geom'] = {'dd_rect': dd_rect, 'items': list(items), 'cur_idx': int(cur_idx), 'idx_key': str(idx_key), 'item_h': int(item_h), 'vis': int(vis)}
                    # Build choice buttons and a mask to close when clicking outside
                    dd_buttons: List[Button] = []
                    start = max(0, min(int(st.get('dd_scroll', 0)), max(0, len(items) - vis)))
                    yy = dd_rect.y + 4
                    for i_rel in range(vis):
                        i = start + i_rel
                        if i >= len(items): break
                        it = items[i]
                        r = pg.Rect(dd_rect.x + 4, yy, dd_w - 8, item_h)
                        def _set(i=i):
                            st[idx_key] = i
                            if isinstance(close_key, str):
                                st[close_key] = items[i]
                            # If main race changed, refresh subrace + appearance
                            if idx_key in ('race_group_idx', 'subrace_idx'):
                                _rebuild_opts()
                            st['open_dd'] = None
                        dd_buttons.append(Button(r, '', _set, draw_bg=False))
                        yy += item_h
                    # Full-screen invisible mask to block clicks behind dropdown
                    def _mask_close():
                        try:
                            mx, my = pg.mouse.get_pos()
                        except Exception:
                            mx, my = 0, 0
                        if not dd_rect.collidepoint(mx, my) and not box.collidepoint(mx, my):
                            st['open_dd'] = None
                    st['_dd_buttons'] = dd_buttons
                    st['_dd_mask'] = Button(pg.Rect(0, 0, win_w, win_h), '', _mask_close, draw_bg=False)
                    # Provide an anchor button to allow closing by clicking the box itself
                    st['_dd_anchor'] = Button(box, '', _toggle, draw_bg=False)
                y0 += 36
            # Race first, as requested
            def chooser(label, items, idx_key):
                nonlocal y0
                screen.blit(labf.render(label, True, (220,220,230)), (x0, y0))
                box = pg.Rect(x0+180, y0-2, 280, 28)
                pg.draw.rect(screen, (36,38,48), box, border_radius=6)
                pg.draw.rect(screen, (70,74,92), box, 1, border_radius=6)
                cur = items[max(0, min(st[idx_key], len(items)-1))] if items else ''
                screen.blit(valf.render(str(cur), True, (230,230,240)), (box.x+8, box.y+4))
                prev_r = pg.Rect(box.right + 8, box.y, 28, 28)
                next_r = pg.Rect(box.right + 44, box.y, 28, 28)
                def prev():
                    st[idx_key] = max(0, st[idx_key]-1)
                    if idx_key == 'race_idx':
                        _rebuild_opts()
                def next():
                    st[idx_key] = min(len(items)-1, st[idx_key]+1)
                    if idx_key == 'race_idx':
                        _rebuild_opts()
                buttons.append(Button(prev_r, '<', prev))
                buttons.append(Button(next_r, '>', next))
                y0 += 36
            # Main Race + Subrace dropdowns
            dropdown('Main Race', st.get('race_groups', []), 'race_group_idx')
            dropdown('Subrace',   st.get('subrace_names', []), 'subrace_idx')
            # Appearance dropdowns (values depend on race)
            def _cap_list(v):
                try:
                    return [str(x).strip().title() for x in (v or [])]
                except Exception:
                    return v or []
            dropdown('Hair Colour', _cap_list(st.get('hair_colors', [])), 'hair_idx', close_key='hair_color')
            dropdown('Skin Colour', _cap_list(st.get('skin_tones', [])), 'skin_idx', close_key='skin_tone')
            dropdown('Eye Colour',  _cap_list(st.get('eye_colors',  [])), 'eye_idx',  close_key='eye_color')
            # Choose hair length first
            dropdown('Hair Length',  st.get('hair_lengths',  []), 'hair_length_idx',  close_key='hair_length')
            # Hair style options depend on selected length
            try:
                lens = st.get('hair_lengths') or []
                li = max(0, min(int(st.get('hair_length_idx',0)), max(0, len(lens)-1))) if lens else 0
                lname = lens[li] if lens else ''
                style_map = st.get('hair_style_map') or {}
                cur_styles = style_map.get(lname, st.get('hair_styles') or [])
                # Clamp idx if it exceeds available styles for this length
                if cur_styles:
                    st['hair_style_idx'] = max(0, min(int(st.get('hair_style_idx',0)), len(cur_styles)-1))
                else:
                    st['hair_style_idx'] = 0
            except Exception:
                cur_styles = st.get('hair_styles') or []
            dropdown('Hair Style',   cur_styles, 'hair_style_idx',   close_key='hair_style')
            # Then names and class
            field('First Name', 'first_name')
            field('Last Name',  'last_name')
            dropdown('Class', st.get('classes', []), 'class_idx')
            # Selected class default stats panel (right side)
            try:
                objs = st.get('class_objs') or []
                cidx = max(0, min(int(st.get('class_idx',0)), max(0, len(objs)-1)))
                co = objs[cidx] if objs else None
                if isinstance(co, dict):
                    # Normalize stats
                    def norm(sd: Dict[str, Any]) -> Dict[str,int]:
                        out: Dict[str,int] = {}
                        for k,v in (sd or {}).items():
                            try:
                                kk = str(k).strip().lower()
                                if kk in ('tec','tech','technique'): kk = 'dex'
                                if kk.startswith('str'): kk = 'phy'
                                if kk.startswith('int'): kk = 'kno'
                                if kk.startswith('wis'): kk = 'ins'
                                out[kk] = int(v)
                            except Exception:
                                continue
                        return out
                    base = co.get('base_stats') if isinstance(co.get('base_stats'), dict) else co.get('stat_block') if isinstance(co.get('stat_block'), dict) else {}
                    ns = norm(base or {})
                    # Compute max to outline top stat(s)
                    max_val = max((int(v) for v in ns.values()), default=None) if ns else None
                    # Stat color mapping
                    COLS = {
                        'phy': (220,90,90),   # red
                        'dex': (90,200,140),  # green
                        'vit': (210,160,90),  # ochre
                        'arc': (160,110,230), # violet
                        'kno': (90,160,240),  # blue
                        'ins': (240,180,90),  # amber
                        'soc': (220,140,200), # magenta
                        'fth': (230,190,120), # gold
                    }
                    # Layout
                    panel_w = 240
                    info_x = content.right - panel_w
                    info_y = content.y + 10
                    info_h = 220
                    info = pg.Rect(info_x, info_y, panel_w-8, info_h)
                    pg.draw.rect(screen, (28,30,40), info, border_radius=8)
                    pg.draw.rect(screen, (72,78,96), info, 1, border_radius=8)
                    titlef = pg.font.Font(None, 22)
                    labf_s = pg.font.Font(None, 20)
                    screen.blit(titlef.render('Class Stats', True, (230,230,240)), (info.x + 8, info.y + 6))
                    rows = [('PHY','phy'),('DEX','dex'),('VIT','vit'),('ARC','arc'),('KNO','kno'),('INS','ins'),('SOC','soc'),('FTH','fth')]
                    # Draw rows with color coding and outline for the highest stat(s)
                    yy2 = info.y + 32
                    for lab,key in rows:
                        val = ns.get(key)
                        col = COLS.get(key, (225,225,235))
                        is_top = (max_val is not None and isinstance(val, int) and int(val) == int(max_val))
                        row_rect = pg.Rect(info.x + 6, yy2 - 2, panel_w - 20, 20)
                        if is_top:
                            pg.draw.rect(screen, (96,102,124), row_rect, 1, border_radius=6)
                        # Left colored swatch
                        sw = pg.Rect(info.x + 10, yy2 + 2, 10, 10)
                        pg.draw.rect(screen, col, sw, border_radius=2)
                        # Stat text
                        shown = '-' if not isinstance(val, int) else str(int(val))
                        label_txt = f"{lab}: {shown}"
                        screen.blit(labf_s.render(label_txt, True, (225,225,235)), (sw.right + 8, yy2 - 2))
                        # Proportional bar (stays within panel bounds)
                        try:
                            if isinstance(val, int) and max_val not in (None, 0):
                                pct = max(0.0, min(1.0, float(val) / float(max_val)))
                                bar_left = info.x + 110
                                bar_right = info.right - 12
                                avail = max(0, bar_right - bar_left)
                                bw = int(avail * pct)
                                if bw > 0:
                                    br = pg.Rect(bar_left, yy2 + 2, bw, 8)
                                    pg.draw.rect(screen, col, br, border_radius=4)
                        except Exception:
                            pass
                        yy2 += 22
            except Exception:
                pass            # Backstory (brief)
            screen.blit(labf.render('Backstory', True, (220,220,230)), (x0, y0))
            box = pg.Rect(x0+180, y0-2, content.w - 220, 80)
            pg.draw.rect(screen, (36,38,48), box, border_radius=6)
            pg.draw.rect(screen, (96,102,124) if st['focus']=='backstory' else (70,74,92), box, 1, border_radius=6)
            bs_lines = []
            line=""
            for ch in str(st.get('backstory','')):
                if ch=='\n' or len(line)>=52:
                    bs_lines.append(line); line='';
                    if ch=='\n': continue
                line += ch
            if line: bs_lines.append(line)
            yy = box.y + 4
            for ln in bs_lines[:3]:
                screen.blit(valf.render(ln, True, (230,230,240)), (box.x+8, yy)); yy += 26
            buttons.append(Button(box, '', lambda: (st.__setitem__('focus','backstory')), draw_bg=False))
            # Descriptions for selected Race and Class at the bottom
            try:
                desc_pad = 8
                desc_h = max(80, min(160, int(content.h * 0.26)))
                by = content.bottom - 40 - (desc_h + desc_pad)
                # Panel rect
                drect = pg.Rect(content.x, by + 40 + desc_pad, content.w, desc_h)
                pg.draw.rect(screen, (28,30,40), drect, border_radius=8)
                pg.draw.rect(screen, (72,78,96), drect, 1, border_radius=8)
                # Columns
                col_gap = 12
                col_w = (drect.w - col_gap) // 2
                race_rect = pg.Rect(drect.x + 8, drect.y + 6, col_w - 16, drect.h - 12)
                class_rect= pg.Rect(race_rect.right + col_gap, drect.y + 6, col_w - 16, drect.h - 12)
                headf = pg.font.Font(None, 20)
                bodyf = pg.font.Font(None, 18)
                # Selected race object
                grp_names = list(st.get('race_groups') or [])
                grp_idx = max(0, min(int(st.get('race_group_idx',0)), max(0, len(grp_names)-1)))
                grp = grp_names[grp_idx] if grp_names else ''
                subs_objs = (st.get('race_group_map') or {}).get(grp, [])
                sub_idx = max(0, min(int(st.get('subrace_idx',0)), max(0, len(subs_objs)-1)))
                r_obj = subs_objs[sub_idx] if subs_objs else None
                # Build race text
                r_name = ''
                r_txts = []
                if isinstance(r_obj, dict):
                    try:
                        r_name = str(r_obj.get('name') or r_obj.get('id') or grp)
                    except Exception:
                        r_name = grp
                    for k in ('appearance','nature_and_culture','combat','spice','description','desc'):
                        v = r_obj.get(k)
                        if isinstance(v, str) and v.strip():
                            r_txts.append(v.strip())
                # Draw race column
                screen.blit(headf.render((r_name or 'Race'), True, (230,230,240)), (race_rect.x, race_rect.y))
                if r_txts:
                    draw_text(screen, "\n\n".join(r_txts), (race_rect.x, race_rect.y + 20), max_w=race_rect.w, font=bodyf, color=(220,220,230))
                # Selected class object
                c_objs = st.get('class_objs') or []
                cidx = max(0, min(int(st.get('class_idx',0)), max(0, len(c_objs)-1)))
                c_obj = c_objs[cidx] if c_objs else None
                c_name = ''
                c_txts = []
                if isinstance(c_obj, dict):
                    try:
                        c_name = str(c_obj.get('name') or c_obj.get('id') or 'Class')
                    except Exception:
                        c_name = 'Class'
                    for k in ('summary','description','desc','notes'):
                        v = c_obj.get(k)
                        if isinstance(v, str) and v.strip():
                            c_txts.append(v.strip())
                    # Append primary stats and proficiencies terse line if present
                    try:
                        prim = c_obj.get('primary_stats')
                        if isinstance(prim, list) and prim:
                            c_txts.append("Primary: " + ", ".join([str(x) for x in prim]))
                    except Exception:
                        pass
                    try:
                        prof = c_obj.get('proficiencies')
                        if isinstance(prof, list) and prof:
                            c_txts.append("Proficiencies: " + ", ".join([str(x) for x in prof][:6]))
                    except Exception:
                        pass
                screen.blit(headf.render((c_name or 'Class'), True, (230,230,240)), (class_rect.x, class_rect.y))
                if c_txts:
                    draw_text(screen, "\n\n".join(c_txts), (class_rect.x, class_rect.y + 20), max_w=class_rect.w, font=bodyf, color=(220,220,230))
            except Exception:
                # If anything goes wrong, fall back to original button position
                by = content.bottom - 40
                pass
            # Action buttons
            def _begin():
                classes = st['classes']
                # Resolve race string from subrace (or main race when no subraces)
                grp_names = list(st.get('race_groups') or [])
                grp_idx = max(0, min(int(st.get('race_group_idx',0)), max(0, len(grp_names)-1)))
                grp = grp_names[grp_idx] if grp_names else 'Human'
                subs = list(st.get('subrace_names') or [])
                race = (subs[max(0, min(int(st.get('subrace_idx',0)), max(0, len(subs)-1)))]) if subs else grp
                role = classes[st['class_idx']] if classes else 'Wanderer'
                # Resolve appearance values from selections
                hair = (st.get('hair_colors') or [''])[max(0, min(int(st.get('hair_idx',0)), max(0, len(st.get('hair_colors',[]))-1)))] if st.get('hair_colors') else ''
                skin = (st.get('skin_tones') or [''])[max(0, min(int(st.get('skin_idx',0)), max(0, len(st.get('skin_tones',[]))-1)))] if st.get('skin_tones') else ''
                eyes = (st.get('eye_colors')  or [''])[max(0, min(int(st.get('eye_idx',0)),  max(0, len(st.get('eye_colors',[]))-1)))] if st.get('eye_colors') else ''
                # Build full name from first/last
                first = str(st.get('first_name','')).strip()
                last  = str(st.get('last_name','')).strip()
                full_name = (f"{first} {last}".strip() if (first or last) else 'Adventurer')
                # Resolve hair length and style strings from selections (style depends on length)
                lens = st.get('hair_lengths') or []
                li = max(0, min(int(st.get('hair_length_idx',0)), max(0, len(lens)-1))) if lens else 0
                length = lens[li] if lens else ''
                style_options = (st.get('hair_style_map') or {}).get(length, st.get('hair_styles') or [])
                si = max(0, min(int(st.get('hair_style_idx',0)), max(0, len(style_options)-1))) if style_options else 0
                style = style_options[si] if style_options else ''
                cfg = {
                    'name': full_name,
                    'race': race,
                    'role': role,
                    'appearance': {
                        'hair_color': hair,
                        'skin_tone': skin,
                        'eye_color': eyes,
                        'hair_style': style,
                        'hair_length': length,
                    },
                    'backstory': st['backstory'],
                }
                _start.set(('new', cfg))
            buttons.append(Button((x0, by, 200, 32), 'Begin Adventure', _begin))
            buttons.append(Button((x0+210, by, 100, 32), 'Back', lambda: (_mode.set('menu'))))
            # NOTE: visual overlay drawing moved to post-draw stage for top layering
        elif mm_mode == 'database':
            # Ensure a minimal data context exists for the database browser
            if db_state is None:
                db_state = _DBState()
                try:
                    # Preload datasets similar to Game.__init__ for rich browsing
                    db_state.items   = gather_items()
                    db_state.npcs    = gather_npcs()
                    db_state.traits  = load_traits()
                    db_state.enchants= load_enchants()
                    db_state.magic   = load_magic()
                    db_state.status  = load_status()
                    db_state.curses  = load_curses()
                    db_state.races   = load_races_list()
                    db_state.classes = load_classes_list()
                except Exception:
                    # Fallbacks; draw_database_overlay tolerates empty lists
                    db_state.items   = []
                    db_state.npcs    = []
                    db_state.traits  = []
                    db_state.enchants= []
                    db_state.magic   = []
                    db_state.status  = []
                    db_state.races   = []
                    db_state.classes = []
            # Render database overlay and collect its buttons
            buttons += draw_database_overlay(screen, db_state)

        # Tiny signal variables updated by buttons via closures
        class _Sig:
            def __init__(self): self.v = None
            def set(self, v): self.v = v
        _start = _Sig(); _mode = _Sig(); _page = _Sig()

        # Keep stacked menu buttons within the window height (simple upward shift)
        try:
            if mm_mode in ('menu','options'):
                stack = [b for b in buttons if isinstance(getattr(b, 'rect', None), pg.Rect) and b.rect.w == 360 and abs((b.rect.x + b.rect.w//2) - (win_w//2)) <= 2]
                if stack:
                    max_bottom = max(b.rect.bottom for b in stack)
                    overflow = max(0, max_bottom + 16 - win_h)
                    if overflow > 0:
                        for b in stack:
                            b.rect.y -= overflow
        except Exception:
            pass

        # Draw buttons
        for b in buttons: b.draw(screen)
        # Draw dropdown overlay on top if character creation has an open dropdown
        if mm_mode == 'char_create' and hasattr(start_menu, '_cc_state'):
            st = start_menu._cc_state
            dd = st.get('_dd_geom') if bool(st.get('open_dd')) else None
            if isinstance(dd, dict):
                dd_rect = dd.get('dd_rect')
                items = dd.get('items') or []
                cur_idx = int(dd.get('cur_idx') or 0)
                item_h = int(dd.get('item_h') or 24)
                vis = int(dd.get('vis') or min(8, len(items)))
                start = max(0, min(int(st.get('dd_scroll', 0)), max(0, len(items) - vis)))
                if isinstance(dd_rect, pg.Rect) and items:
                    pg.draw.rect(screen, (32,34,44), dd_rect, border_radius=6)
                    pg.draw.rect(screen, (96,102,124), dd_rect, 1, border_radius=6)
                    # Draw scrollbar track + thumb if available
                    track_rect = dd.get('track_rect')
                    thumb_rect = dd.get('thumb_rect')
                    track_w = 0
                    if isinstance(track_rect, pg.Rect):
                        track_w = track_rect.w
                        pg.draw.rect(screen, (40,42,56), track_rect, border_radius=4)
                        pg.draw.rect(screen, (96,102,124), track_rect, 1, border_radius=4)
                        if isinstance(thumb_rect, pg.Rect):
                            pg.draw.rect(screen, (78,84,106), thumb_rect, border_radius=4)
                            pg.draw.rect(screen, (120,128,150), thumb_rect, 1, border_radius=4)
                    labf2 = pg.font.Font(None, 22)
                    # Hover highlight
                    try:
                        mx, my = pg.mouse.get_pos()
                    except Exception:
                        mx, my = 0, 0
                    hover_rel = -1
                    if dd_rect.collidepoint(mx, my):
                        try:
                            hover_rel = int((my - (dd_rect.y + 4)) // item_h)
                        except Exception:
                            hover_rel = -1
                    yy = dd_rect.y + 4
                    for i_rel in range(vis):
                        i = start + i_rel
                        if i >= len(items): break
                        it = items[i]
                        r = pg.Rect(dd_rect.x + 4, yy, dd_rect.w - 8 - track_w, item_h)
                        if i == cur_idx:
                            pg.draw.rect(screen, (56,60,76), r, border_radius=4)
                        elif i_rel == hover_rel:
                            pg.draw.rect(screen, (46,50,66), r, border_radius=4)
                        txt = labf2.render(str(it), True, (230,230,240))
                        screen.blit(txt, (r.x + 6, r.y + 3))
                        yy += item_h
        pg.display.flip()
        # Handle events (after buttons exist)
        for event in pg.event.get():
            if event.type == pg.QUIT:
                running = False
            elif event.type == pg.VIDEORESIZE:
                screen = pg.display.set_mode((event.w, event.h), pg.RESIZABLE)
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE:
                    if mm_mode == 'menu':
                        running = False
                    else:
                        mm_mode = 'menu'
                # Text input for char create
                if mm_mode == 'char_create' and hasattr(start_menu, '_cc_state'):
                    st = start_menu._cc_state
                    if event.key == pg.K_BACKSPACE:
                        k = st['focus']; st[k] = st.get(k,'')[:-1]
                    elif event.key == pg.K_RETURN:
                        order = ['first_name','last_name','backstory']
                        try:
                            i = order.index(st['focus']); st['focus'] = order[(i+1)%len(order)]
                        except Exception:
                            st['focus'] = 'first_name'
                    else:
                        ch = getattr(event, 'unicode', '')
                        if ch and ch.isprintable():
                            k = st['focus'];
                            lim = 200 if k=='backstory' else 48
                            if len(st.get(k,'')) < lim:
                                st[k] = st.get(k,'') + ch
                        # Clear database text focus when leaving
                        if db_state is not None:
                            try: db_state.db_filter_focus = False
                            except Exception: pass
                elif mm_mode == 'database' and db_state is not None and bool(getattr(db_state,'db_filter_focus', False)):
                    # Text input for database filter (main menu context)
                    if event.key == pg.K_RETURN:
                        db_state.db_filter_focus = False
                    elif event.key == pg.K_BACKSPACE:
                        try:
                            db_state.db_query = (db_state.db_query[:-1]) if getattr(db_state,'db_query','') else ''
                        except Exception:
                            db_state.db_query = ''
                    else:
                        ch = getattr(event, 'unicode', '')
                        try:
                            if ch and ch.isprintable():
                                if len(getattr(db_state,'db_query','')) < 128:
                                    db_state.db_query = (getattr(db_state,'db_query','') + ch)
                        except Exception:
                            pass
            elif event.type == pg.MOUSEWHEEL:
                # Scroll open dropdown lists in character creation
                if mm_mode == 'char_create' and hasattr(start_menu, '_cc_state'):
                    st = start_menu._cc_state
                    if bool(st.get('open_dd')) and isinstance(st.get('_dd_geom'), dict):
                        dd = st['_dd_geom']
                        dd_rect = dd.get('dd_rect')
                        items = dd.get('items') or []
                        vis = int(dd.get('vis') or min(8, len(items)))
                        try:
                            mx, my = pg.mouse.get_pos()
                        except Exception:
                            mx, my = 0, 0
                        if isinstance(dd_rect, pg.Rect) and dd_rect.collidepoint(mx, my):
                            ofs = int(st.get('dd_scroll', 0))
                            max_ofs = max(0, len(items) - vis)
                            ofs = max(0, min(max_ofs, ofs - int(getattr(event, 'y', 0))))
                            st['dd_scroll'] = ofs
            elif event.type == pg.MOUSEBUTTONDOWN:
                # If a dropdown is open in character creation, capture clicks exclusively
                if mm_mode == 'char_create' and hasattr(start_menu, '_cc_state'):
                    st = start_menu._cc_state
                    if bool(st.get('open_dd')):
                        dd_btns = list(st.get('_dd_buttons') or [])
                        mask_btn = st.get('_dd_mask')
                        anchor_btn = st.get('_dd_anchor')
                        active = ([mask_btn] if mask_btn is not None else []) + ([anchor_btn] if anchor_btn is not None else []) + dd_btns
                        if active:
                            for b in reversed(active):
                                b.handle(event)
                            # Swallow click to prevent interacting with elements behind dropdown
                            continue
                # Handle most recently added buttons first (overlays on top)
                for b in reversed(buttons): b.handle(event)

        # Apply requested state changes
        if _mode.v is not None:
            val = _mode.v; _mode.v = None
            if val == 'toggle_fs':
                opts['fullscreen'] = not opts.get('fullscreen', False)
                _save_opts(opts)
                # Apply immediately
                flags = pg.FULLSCREEN if opts['fullscreen'] else pg.RESIZABLE
                screen = pg.display.set_mode(screen.get_size(), flags)
            elif val in ('mv-','mv+','sv-','sv+'):
                delta = -10 if val.endswith('-') else 10
                key = 'music_vol' if val.startswith('mv') else 'sfx_vol'
                opts[key] = max(0, min(100, int(opts.get(key, 100)) + delta))
                _save_opts(opts)
            else:
                mm_mode = val
        # Handle Back button inside database overlay (sets mode='explore')
        if mm_mode == 'database' and db_state is not None and getattr(db_state, 'mode', None) == 'explore':
            mm_mode = 'menu'
            try:
                db_state.db_filter_focus = False
                db_state.mode = None
            except Exception:
                pass
        if _page.v is not None:
            load_page = max(0, int(_page.v)); _page.v = None
        if _start.v is not None:
            sel = _start.v
            if isinstance(sel, tuple) and sel[0] == 'new':
                return ('new', sel[1])
            if sel == 'new':
                mm_mode = 'char_create'; _start.v = None; continue
            if isinstance(sel, tuple) and sel[0] == 'load':
                slot = int(sel[1]); return ('load', slot)
            _start.v = None

    return ('quit', None)

# ======================== CLI entry ========================
def main(argv=None):
    ap = argparse.ArgumentParser(description="RPGenesis-Fantasy - validate then launch game UI")
    ap.add_argument("--root", default=".", help="Project root")
    ap.add_argument("--validate-only", action="store_true", help="Run validation only, do not start UI")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as fatal")
    # Start overrides
    ap.add_argument("--start-map", dest="start_map", help="Override starting map name")
    ap.add_argument("--start-entry", dest="start_entry", help="Override starting entry name (if provided, takes precedence over position)")
    ap.add_argument("--start-pos", dest="start_pos", nargs=2, type=int, metavar=("X","Y"), help="Override starting tile position X Y")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.root in (None, ".", "./"):
        root = script_dir

    errs, warns = validate_project(root, strict=args.strict)

    if args.validate_only:
        sys.exit(1 if errs or (args.strict and warns) else 0)

    if errs or (args.strict and warns):
        print("\n[ABORT] Fix the issues above to launch the game (use --strict to elevate warnings).")
        sys.exit(1)

    print("\n[OK] Validation passed. Launching main menu...")
    sel, data = start_menu()
    if sel == 'new':
        if isinstance(data, dict):
            start_game(start_map=args.start_map, start_entry=args.start_entry, start_pos=tuple(args.start_pos) if args.start_pos else None, char_config=data)
        else:
            start_game(start_map=args.start_map, start_entry=args.start_entry, start_pos=tuple(args.start_pos) if args.start_pos else None)
    elif sel == 'load' and data is not None:
        start_game(load_slot=int(data))
    else:
        print("Goodbye.")

if __name__ == "__main__":
    main()
