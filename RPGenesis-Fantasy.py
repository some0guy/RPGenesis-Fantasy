#!/usr/bin/env python3
from __future__ import annotations
import os, sys, json, re, argparse, random, math
from typing import Dict, Any, List, Tuple, Optional, Set
from datetime import datetime
from collections import deque
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
WORLD_MAP_PATH = DATA_DIR / "world_map.json"

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
        "data/npcs/monsters.json",
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
        for it in doc.get("items", []):
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
        for npc in doc.get("npcs", []):
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
        ("data/enchants.json", "enchants", "enchant"),
        ("data/traits.json",   "traits",   "trait"),
        ("data/magic.json",    "spells",   "magic"),
        ("data/status.json",   "status",   "status"),
    ]:
        try:
            doc = load_json(abspath(rel), {key: []})
            if isinstance(doc, dict):
                check_ids_in(doc, rel, key, kind)
        except Exception as e:
            errs.append(f"[ERR] Failed to load {rel}: {e}")

    try:
        loot = load_json(abspath("data/loot_tables.json"), {"tables": {}, "aliases": {}})
    except Exception as e:
        errs.append(f"[ERR] Failed to load data/loot_tables.json: {e}")
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
    doc = load_json(os.path.join(DATA_DIR, rel), {array_key: []})
    return [x for x in doc.get(array_key, []) if isinstance(x, dict)]

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
    'head': 'Helmet',
    'neck': 'Necklace',
    'chest': 'Chestplate',
    'legs': 'Legs',
    'boots': 'Boots',
    'gloves': 'Gloves',
    'ring': 'Ring',
    'bracelet': 'Bracelet',
    'charm': 'Charm',
    'back': 'Cape/Backpack',
    'weapon_main': 'Weapon 1',
    'weapon_off': 'Weapon 2',
}

def normalize_slot(name: str) -> str:
    n = (name or '').strip().lower()
    if n in ('head','helm','helmet','hat'): return 'head'
    if n in ('neck','amulet','necklace','torc'): return 'neck'
    if n in ('chest','torso','body','armor','armour','breastplate','chestplate'): return 'chest'
    if n in ('legs','pants','trousers'): return 'legs'
    if n in ('boots','shoes','feet','foot','greaves'): return 'boots'
    if n in ('hands','hand','gloves','gauntlets'): return 'gloves'
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
    if slot in ('weapon_main','weapon_off'):
        return typ == 'weapon'
    if slot == 'head':
        return m in ('armour','armor','clothing') and sub in ('head','helm','helmet','hat')
    if slot == 'chest':
        return m in ('armour','armor','clothing') and sub in ('chest','torso','body','armor','armour','breastplate','chestplate')
    if slot == 'legs':
        return m in ('armour','armor','clothing') and sub in ('legs','pants','trousers')
    if slot == 'boots':
        return m in ('armour','armor','clothing') and sub in ('boots','shoes','feet','foot','greaves')
    if slot == 'gloves':
        return m in ('armour','armor','clothing') and sub in ('hands','hand','gloves','gauntlets')
    if slot == 'ring':
        return m in ('accessory','accessories','trinket','trinkets') and sub in ('ring',)
    if slot == 'bracelet':
        return m in ('accessory','accessories','trinket','trinkets') and sub in ('bracelet','bracer','bracers','wrist')
    if slot == 'charm':
        return m in ('accessory','accessories','trinket','trinkets') and sub in ('charm','token','trinket')
    if slot == 'neck':
        return m in ('accessory','accessories','trinket','trinkets') and sub in ('neck','amulet','necklace','torc')
    if slot == 'back':
        return (m in ('armour','armor','clothing','accessory','accessories') and sub in ('back','cloak','cape','backpack'))
    return False

def _weapon_stats(it: Dict) -> Tuple[int,int,float,List[str]]:
    """Returns (min_bonus, max_bonus, status_chance, statuses) reading multiple possible keys safely."""
    min_b = int(_coalesce(it.get('min'), it.get('min_damage'), it.get('damage_min'), it.get('atk_min'), 0) or 0)
    max_b = int(_coalesce(it.get('max'), it.get('max_damage'), it.get('damage_max'), it.get('atk_max'), 0) or 0)
    st_ch = float(_coalesce(it.get('status_chance'), it.get('statusChance'), 0.0) or 0.0)
    statuses = it.get('status') or it.get('statuses') or []
    if isinstance(statuses, str): statuses = [statuses]
    st_ch = max(0.0, min(1.0, st_ch))
    return min_b, max_b, st_ch, list(statuses)

def gather_items() -> List[Dict]:
    items: List[Dict] = []
    items_dir = os.path.join(DATA_DIR, "items")
    if os.path.isdir(items_dir):
        for name in ["weapons.json","armour.json","accessories.json","clothing.json","consumables.json","materials.json","quest_items.json","trinkets.json"]:
            for it in safe_load_doc(os.path.join("items", name), "items"):
                items.append(it)
    return items

def gather_npcs() -> List[Dict]:
    npcs: List[Dict] = []
    npcs_dir = os.path.join(DATA_DIR, "npcs")
    if os.path.isdir(npcs_dir):
        for name in ["allies.json","animals.json","citizens.json","enemies.json","monsters.json","villains.json"]:
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

# Tolerant loaders for top-level array documents (e.g., races, classes)
def load_races_list() -> List[Dict]:
    path = DATA_DIR / "races.json"
    try:
        doc = load_json(str(path), [])
        if isinstance(doc, list):
            return list(doc)
        if isinstance(doc, dict) and isinstance(doc.get("races"), list):
            return list(doc.get("races"))
    except Exception:
        pass
    return []

def load_classes_list() -> List[Dict]:
    path = DATA_DIR / "classes.json"
    try:
        if not path.exists() or path.stat().st_size == 0:
            return []
        doc = load_json(str(path), [])
        if isinstance(doc, list):
            return list(doc)
        if isinstance(doc, dict) and isinstance(doc.get("classes"), list):
            return list(doc.get("classes"))
    except Exception:
        pass
    return []

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
    has_link: bool = False   # link marker for UI

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
    stealth: int = 4
    dex: int = 5
    affinity: Dict[str,int] = field(default_factory=dict)
    romance_flags: Dict[str,bool] = field(default_factory=dict)
    inventory: List[Dict] = field(default_factory=list)
    equipped_weapon: Optional[Dict] = None
    equipped_focus: Optional[Dict] = None
    # Generic equipment slots for armour/clothing/accessory
    equipped_gear: Dict[str, Dict] = field(default_factory=dict)

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
            elif text.startswith("• "):
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

class Button:
    def __init__(self, rect, label, cb, draw_bg: bool=True):
        if pg is None:
            raise RuntimeError("pygame not available")
        self.rect = pg.Rect(rect)
        self.label = label
        self.cb = cb
        self.draw_bg = draw_bg
    def draw(self, surf):
        if not self.draw_bg:
            return
        label_font = pg.font.Font(None, 18)
        pg.draw.rect(surf, (60,60,70), self.rect, border_radius=8)
        pg.draw.rect(surf, (110,110,130), self.rect, 2, border_radius=8)
        label = label_font.render(self.label, True, (240,240,255))
        surf.blit(label, (self.rect.x + 10, self.rect.y + (self.rect.h - label.get_height())//2))
    def handle(self, event):
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            self.cb()

PANEL_W_FIXED = 380  # Fixed width for left/right sidebars

def draw_grid(surf, game):
    # Dynamic view area and camera
    win_w, win_h = surf.get_size()
    panel_w = int(PANEL_W_FIXED)
    view_w = max(100, win_w - 2*panel_w)
    view_h = win_h
    view_rect = pg.Rect(panel_w, 0, view_w, view_h)
    # Background for map area
    pg.draw.rect(surf, (26,26,32), view_rect)

    W = getattr(game, 'W', 12); H = getattr(game, 'H', 8)
    # Target visible tiles for a slightly zoomed view
    vis_w_tiles = min(10, W)
    vis_h_tiles = min(6, H)
    margin = 12
    gap = 4
    # Compute tile size to fit target number of tiles
    tile_px = max(20, min(96,
        int(min(
            (view_w - 2*margin) / max(1, vis_w_tiles) - gap,
            (view_h - 2*margin) / max(1, vis_h_tiles) - gap
        ))
    ))
    stride = tile_px + gap
    # Save on game for other UI uses
    game.tile_px = tile_px

    # Camera center on player
    px_world = game.player.x * stride + margin + tile_px//2
    py_world = game.player.y * stride + margin + tile_px//2
    # Center camera on player at all times (allow background beyond edges)
    cam_x = px_world - view_w//2
    cam_y = py_world - view_h//2

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

    for y in range(H):
        for x in range(W):
            wx = x*stride + margin
            wy = y*stride + margin
            rx = wx - cam_x
            ry = wy - cam_y
            if rx > view_w or ry > view_h or rx + tile_px < 0 or ry + tile_px < 0:
                continue
            r = pg.Rect(int(view_rect.x + rx), int(view_rect.y + ry), tile_px, tile_px)
            tile = game.grid[y][x]
            # Invisible impassable tiles: skip base/border entirely
            if tile.walkable:
                # Constant base color (do not vary by discovered/visited)
                base = (42,44,56)
                pg.draw.rect(surf, base, r, border_radius=6)
                pg.draw.rect(surf, (70,74,92), r, 1, border_radius=6)
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
                order = ['enemy','villain','ally','citizen','monster','animal','quest_item','item','event']
                color_map = {
                    'enemy': COL_ENEMY,
                    'villain': COL_VILLAIN,
                    'ally': COL_ALLY,
                    'citizen': COL_CITIZEN,
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
            if dot_colors:
                # layout centered: 1 center; 2 side-by-side; 3 triangle; 4 2x2; >4 balanced rows
                pad = max(2, tile_px // 16)
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
                gap = max(2, tile_px // 16)
                avail_w = r.w - 2*pad
                avail_h = r.h - 2*pad
                r_w = (avail_w - (max_cols - 1) * gap) / (2 * max_cols) if max_cols else tile_px//8
                r_h = (avail_h - (rows_cnt - 1) * gap) / (2 * rows_cnt) if rows_cnt else tile_px//8
                rad = int(max(3, min(r_w, r_h, tile_px // 8)))
                gap_x = 2*rad + gap
                gap_y = 2*rad + gap
                total_h = rows_cnt * (2*rad) + (rows_cnt - 1) * gap
                start_y = r.y + (r.h - total_h)//2 + rad
                idx = 0
                for ri, cnt in enumerate(row_counts):
                    total_w = cnt * (2*rad) + (cnt - 1) * gap
                    start_x = r.x + (r.w - total_w)//2 + rad
                    cy = start_y + ri * gap_y
                    for cj in range(cnt):
                        if idx >= n: break
                        cx = start_x + cj * gap_x
                        pg.draw.circle(surf, (10,10,12), (int(cx), int(cy)), rad+1)
                        pg.draw.circle(surf, dot_colors[idx], (int(cx), int(cy)), rad)
                        idx += 1

    # Player marker: outline around the player's tile (no white square)
    px = px_world - cam_x
    py = py_world - cam_y
    if 0 <= px <= view_w and 0 <= py <= view_h:
        pr = pg.Rect(int(view_rect.x + px - tile_px//2), int(view_rect.y + py - tile_px//2), tile_px, tile_px)
        pg.draw.rect(surf, COL_PLAYER, pr, 3, border_radius=6)

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
    draw_text(surf, f"RPGenesis v{get_version()} – Field Log", (x0+16, 12), font=header_font)

    # Left panel content: Party header + player stats
    yL = 12
    draw_text(surf, "Party", (16, yL), font=header_font); yL += 26
    draw_text(surf, f"You: {game.player.name}", (16, yL)); yL += 18
    draw_text(surf, f"Race: {game.player.race}", (16, yL)); yL += 18
    draw_text(surf, f"Class: {game.player.role}", (16, yL)); yL += 18
    draw_text(surf, f"HP: {game.player.hp}/{game.player.max_hp}", (16, yL)); yL += 18
    mn,mx = game.player.atk
    draw_text(surf, f"ATK: {mn}-{mx}", (16, yL)); yL += 18
    draw_text(surf, f"DEX: {game.player.dex}", (16, yL)); yL += 18
    draw_text(surf, f"Stealth: {game.player.stealth}", (16, yL)); yL += 18

    # Scrollable right panel content (below header, above buttons)
    content_top = 44
    buttons_top = win_h - 210
    view_h = max(0, buttons_top - content_top)
    content_clip = pg.Rect(x0, content_top, panel_w, view_h)
    _prev_clip = surf.get_clip(); surf.set_clip(content_clip)
    if not hasattr(game, 'ui_scroll'):
        game.ui_scroll = 0
    y = content_top - max(0, int(getattr(game, 'ui_scroll', 0)))

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
    # Equipped
    wep = item_name(game.player.equipped_weapon) if game.player.equipped_weapon else "None"
    foc = item_name(game.player.equipped_focus) if game.player.equipped_focus else "None"
    draw_text(surf, f"Weapon: {wep}", (x0+16, y)); y += 18
    draw_text(surf, f"Focus : {foc}", (x0+16, y)); y += 24

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
        block_h = draw_text(surf, f"• {line}", (x0+20, y), max_w=panel_w-36)
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
        add("Attack (Weapon)", game.attack)
        add("Cast Spell", game.cast_spell)
        add("Talk", game.talk_enemy)
        if getattr(game, 'can_bribe', False):
            add("Offer Bribe", game.offer_bribe)
        add("Flee", game.flee)
        add("Inventory", lambda: setattr(game, 'mode', 'inventory'))
        add("Equipment", lambda: setattr(game, 'mode', 'equip'))
        add("Database", lambda: setattr(game, 'mode', 'database'))
    elif game.mode == "dialogue":
        add("Talk",  lambda: game.handle_dialogue_choice("Talk"))
        add("Leave", lambda: game.handle_dialogue_choice("Leave"))
        add("Inventory", lambda: setattr(game, 'mode', 'inventory'))
        add("Equipment", lambda: setattr(game, 'mode', 'equip'))
        add("Database", lambda: setattr(game, 'mode', 'database'))
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
    else:
        add("Search Area", game.search_tile)
        if t.encounter and t.encounter.enemy and not t.encounter.spotted:
            add("Sneak Past",            game.try_sneak)
            add("Bypass (Skirt Around)", game.bypass_enemy)
        if t.encounter and t.encounter.enemy and t.encounter.spotted:
            add("Fight", lambda: game.start_combat(t.encounter.enemy))
        if t.encounter and t.encounter.npc:
            add("Talk",      lambda: game.start_dialogue(t.encounter.npc))
        # Travel via link if present
        if getattr(t, 'link_to_map', None):
            dest = t.link_to_map
            add(f"Travel to {dest}", game.travel_link)
            add("Leave NPC", lambda: game.handle_dialogue_choice("Leave"))
        add("Inventory", lambda: setattr(game, 'mode', 'inventory'))
        add("Equipment", lambda: setattr(game, 'mode', 'equip'))
        add("Database", lambda: setattr(game, 'mode', 'database'))
        add("Save Game", lambda: setattr(game, 'mode', 'save'))
        add("Load Game", lambda: setattr(game, 'mode', 'load'))

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
            if subtype in ("wand","staff"):
                buttons.append(Button((x0+16, y, 160, 30), "Equip as Focus", lambda: game.equip_focus(it)))
                y += 34
            else:
                buttons.append(Button((x0+16, y, 160, 30), "Equip Weapon", lambda: game.equip_weapon(it)))
                y += 34
        # Drop button
        buttons.append(Button((x0+16, y, 160, 30), "Drop", lambda: game.drop_item(game.inv_sel)))
        # Close
        buttons.append(Button((x0+16+170, y, 160, 30), "Close", lambda: setattr(game,'mode','explore')))
    else:
        # Pager + Close when nothing selected
        buttons.append(Button((x0+16, y, 110, 28), "Prev Page", lambda: setattr(game,'inv_page', max(0, game.inv_page-1))))
        buttons.append(Button((x0+16+120, y, 110, 28), "Next Page", lambda: setattr(game,'inv_page', min(pages-1, game.inv_page+1))))
        buttons.append(Button((x0+16+240, y, 90, 28), "Close", lambda: setattr(game,'mode','explore')))

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
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: setattr(game,'mode','explore')))

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
        # Colored inner tag stripe
        tag = r.inflate(-10, -10)
        tag.h = max(8, icon // 6)
        pg.draw.rect(surf, type_color(it), (tag.x, tag.y, tag.w, tag.h), border_radius=4)
        # Icon glyph (first letter of type)
        glyph = (str(item_type(it)) or '?')[:1].upper()
        gfont = pg.font.Font(None, max(18, icon // 2))
        gs = gfont.render(glyph, True, (235,235,245))
        surf.blit(gs, (r.centerx - gs.get_width()//2, r.centery - gs.get_height()//2))
        # Label (name) under icon — multi-line (up to 2)
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
                    while len(t) > 1 and lab_font.size(t + '…')[0] > max_w:
                        t = t[:-1]
                    lines.append(t + '…')
                    cur = ""
                    break
                cur = w
                if len(lines) >= lab_lines - 1:
                    # finalize last line with ellipsis
                    t = cur
                    while len(t) > 1 and lab_font.size(t + '…')[0] > max_w:
                        t = t[:-1]
                    lines.append((t + '…') if t else '')
                    cur = ""
                    break
        if cur and len(lines) < lab_lines:
            lines.append(cur)
        # Render lines centered under icon
        for li, text in enumerate(lines[:lab_lines]):
            ts = lab_font.render(text, True, (220,220,230))
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
        draw_text(surf, item_name(it), (det_area.x + 12, det_area.y + 10), font=name_font)
        y2 = det_area.y + 48
        typ = item_type(it); sub = item_subtype(it)
        wt = item_weight(it); val = item_value(it)
        draw_text(surf, f"Type: {typ} / {sub}", (det_area.x + 12, y2)); y2 += 22
        draw_text(surf, f"Weight: {wt}", (det_area.x + 12, y2)); y2 += 22
        draw_text(surf, f"Value: {val}", (det_area.x + 12, y2)); y2 += 26
        desc = item_desc(it) or ""
        draw_text(surf, desc, (det_area.x + 12, y2), max_w=det_area.w - 24); y2 += 90

        # Action buttons along bottom of details
        bx = det_area.x + 12; by = det_area.bottom - 34
        mtyp = item_major_type(it)
        sub_l = str(sub).lower()
        if mtyp == 'weapon':
            if sub_l in ('wand','staff'):
                buttons.append(Button((bx, by, 160, 28), "Equip as Focus", lambda it=it: game.equip_focus(it))); bx += 170
            else:
                buttons.append(Button((bx, by, 160, 28), "Equip Weapon", lambda it=it: game.equip_weapon(it))); bx += 170
        elif mtyp in ('armour','armor','clothing','accessory','accessories'):
            buttons.append(Button((bx, by, 160, 28), "Equip", lambda it=it: game.equip_item(it))); bx += 170
        if item_is_consumable(it):
            buttons.append(Button((bx, by, 140, 28), "Consume", lambda idx=game.inv_sel: game.consume_item(idx))); bx += 150
        if not item_is_quest(it):
            buttons.append(Button((bx, by, 120, 28), "Drop", lambda idx=game.inv_sel: game.drop_item(idx))); bx += 130

    # Back button moved to header above

    # Tooltips removed per request

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

    # Header
    title_font = pg.font.Font(None, 30)
    surf.blit(title_font.render("Equipment", True, (235,235,245)), (modal.x + 16, modal.y + 12))
    buttons.append(Button((modal.right - 230, modal.y + 10, 110, 28), "Inventory", lambda: setattr(game,'mode','inventory')))
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: setattr(game,'mode','explore')))

    # Layout left silhouette, right list
    pad = 16
    content = modal.inflate(-2*pad, -2*pad)
    sil_area = pg.Rect(content.x, content.y + 36, int(content.w * 0.54), content.h - 52)
    list_area = pg.Rect(content.x + sil_area.w + 12, content.y + 36, content.w - sil_area.w - 12, content.h - 52)
    for r in (sil_area, list_area):
        pg.draw.rect(surf, (30,32,42), r, border_radius=8)
        pg.draw.rect(surf, (70,74,92), r, 1, border_radius=8)

    # Try to draw the actual player sprite; fall back to silhouette image/shapes
    sil_img = None
    try:
        candidates = [
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
    def at(nx: float, ny: float) -> pg.Rect:
        px = sil_area.x + int(nx * sil_area.w) - slot_sz//2
        py = sil_area.y + int(ny * sil_area.h) - slot_sz//2
        return pg.Rect(px, py, slot_sz, slot_sz)

    SLOT_POS = {
        'head':         (0.50, 0.12),
        # Necklace aligned to the gap between left and center columns
        'neck':         (0.34, 0.30),
        'back':         (0.60, 0.30),
        'chest':        (0.50, 0.42),
        # Move gloves down to ring row; move bracelet to former gloves position; add charm at former bracelet position
        'gloves':       (0.82, 0.54),
        'ring':         (0.18, 0.54),
        # Bracelet aligned to the gap between center and right columns
        'bracelet':     (0.66, 0.42),
        'charm':        (0.18, 0.42),
        # Legs moved up slightly; boots added below
        'legs':         (0.50, 0.60),
        'boots':        (0.50, 0.72),
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
        eq = game.player.equipped_gear.get(key)
        hov = r.collidepoint(mx, my)
        base = (44,48,62) if hov or key == sel_slot else (38,40,52)
        pg.draw.rect(surf, base, r, border_radius=8)
        pg.draw.rect(surf, (96,102,124) if hov or key == sel_slot else (70,74,92), r, 2, border_radius=8)
        # Slot label
        lab = SLOT_LABELS.get(key, key.title())
        f = pg.font.Font(None, 18)
        ls = f.render(lab, True, (210,210,220))
        surf.blit(ls, (r.centerx - ls.get_width()//2, r.bottom + 4))
        # If equipped, draw small icon glyph
        if eq:
            tag = r.inflate(-10, -10)
            tag.h = max(8, slot_sz // 6)
            pg.draw.rect(surf, type_color(eq), (tag.x, tag.y, tag.w, tag.h), border_radius=4)
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
    header = f"Select for: {SLOT_LABELS.get(sel_slot, '—')}" if sel_slot else "Select a slot"
    draw_text(surf, header, (list_area.x + 12, list_area.y - 26), font=fnt)

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
            draw_text(surf, label, (r.x+8, r.y+6))
            def make_equip(it=it, slot=sel_slot):
                return lambda it=it, slot=slot: game.equip_item_to_slot(slot, it)
            buttons.append(Button(r, "", make_equip(), draw_bg=False))

        # Pager and Unequip
        pager_y = list_area.bottom - 34
        buttons.append(Button((list_area.x + 8, pager_y, 110, 26), "Prev Page", lambda: setattr(game,'equip_page', max(0, game.equip_page-1))))
        buttons.append(Button((list_area.x + 8 + 120, pager_y, 110, 26), "Next Page", lambda: setattr(game,'equip_page', min(pages-1, game.equip_page+1))))
        # Unequip if there is an item in slot
        if game.player.equipped_gear.get(sel_slot):
            buttons.append(Button((list_area.right - 130, pager_y, 110, 26), "Unequip", lambda slot=sel_slot: game.unequip_slot(slot)))

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
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: setattr(game,'mode','explore')))

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
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: setattr(game,'mode','explore')))

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
    buttons.append(Button((modal.right - 112, modal.y + 10, 100, 28), "Back", lambda: setattr(game,'mode','explore')))

    # Initialize state on first open
    if not hasattr(game, 'db_cat'): game.db_cat = 'Items'
    if not hasattr(game, 'db_sub'): game.db_sub = 'All'
    if not hasattr(game, 'db_page'): game.db_page = 0
    if not hasattr(game, 'db_sel'): game.db_sel = None
    # Sorting state for database view
    if not hasattr(game, 'db_sort_key'): game.db_sort_key = 'Name'
    if not hasattr(game, 'db_sort_desc'): game.db_sort_desc = False  # False=A–Z, True=Z–A
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
            'All':      npcs_all,
            'Allies':   _safe(os.path.join('npcs','allies.json'), 'npcs'),
            'Animals':  _safe(os.path.join('npcs','animals.json'), 'npcs'),
            'Citizens': _safe(os.path.join('npcs','citizens.json'), 'npcs'),
            'Enemies':  _safe(os.path.join('npcs','enemies.json'), 'npcs'),
            'Monsters': _safe(os.path.join('npcs','monsters.json'), 'npcs'),
            'Villains': villains_list,
        }
        game.db_cache = {
            'Items': items,
            'NPCs': npcs,
            'Races': list(getattr(game, 'races', []) or []),
            'Traits': list(getattr(game, 'traits', []) or []),
            'Enchants': list(getattr(game, 'enchants', []) or []),
            'Magic': list(getattr(game, 'magic', []) or []),
            'Status': list(getattr(game, 'status', []) or []),
            'Classes': list(getattr(game, 'classes', []) or []),
        }

    # Tabs
    tab_font = game._db_font_22
    tab_y = modal.y + 50
    tab_x = modal.x + 16
    tab_h = 28
    tab_pad = 10
    tabs = ['Items','NPCs','Races','Traits','Enchants','Magic','Status','Classes']
    for name in tabs:
        tw = max(90, tab_font.size(name)[0] + 20)
        r = pg.Rect(tab_x, tab_y, tw, tab_h)
        sel = (game.db_cat == name)
        pg.draw.rect(surf, (50,54,68) if sel else (34,36,46), r, border_radius=8)
        pg.draw.rect(surf, (110,110,130), r, 2, border_radius=8)
        surf.blit(tab_font.render(name, True, (235,235,245)), (r.x + 10, r.y + 5))
        def make_tab(n=name):
            return lambda n=n: (setattr(game,'db_cat', n), setattr(game,'db_page', 0), setattr(game,'db_sel', None))
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
        chips = ['All','Allies','Animals','Citizens','Enemies','Monsters','Villains']
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
            return (_safe_str(item_type(obj)).lower(), _safe_str(item_name(obj)).lower())
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

    try:
        if cat == 'Items':
            entries = sorted(base, key=_sort_val_items, reverse=desc)
        elif cat == 'NPCs':
            entries = sorted(base, key=_sort_val_npcs, reverse=desc)
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
                if cat == 'Races':
                    return [
                        ('Name', ('name','id')),
                        ('Group', ('race_group',)),
                        ('Appearance', ('appearance',)),
                        ('Nature & Culture', ('nature_and_culture',)),
                        ('Combat', ('combat',)),
                        ('Flavor', ('spice',)),
                    ]
                return [
                    ('Name', ('name','id')),
                    ('Details', ('effect','effects','tags','applies_to','school','damage','mp')),
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
    dd_label = ('Fields ▾' if not is_open else 'Fields ▴')
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
            return ['Name','Type']
        if cat == 'NPCs':
            return ['Name','Race','Sex','Type']
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

    # Direction toggle (A–Z / Z–A)
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
            ('Details', ('effect','effects','tags','applies_to','school','damage','mp')),
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
            'monsters': COL_MONSTER,
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
        if 'monster' in t: return COL_MONSTER
        if 'animal' in t: return COL_ANIMAL
        if 'citizen' in t: return COL_CITIZEN
        try:
            if bool(n.get('hostile')): return COL_ENEMY
        except Exception:
            pass
        return COL_ALLY

    def _entry_dot_color(obj: Any) -> Optional[Tuple[int,int,int]]:
        if cat == 'Items' and isinstance(obj, dict):
            try:
                return COL_QITEM if item_is_quest(obj) else COL_ITEM
            except Exception:
                return COL_ITEM
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
            elif cat == 'NPCs':
                label = str(it.get('name') or it.get('id') or '?')
            elif cat == 'Races':
                label = str(it.get('name') or it.get('id') or '?')
            elif cat in ('Traits','Enchants','Magic','Status','Classes'):
                label = str(it.get('name') or it.get('id') or '?')
        except Exception:
            label = str(it)
        cache_key = (label, int(name_font.get_height()))
        lab_surf = game._db_label_cache.get(cache_key)
        if lab_surf is None:
            lab_surf = name_font.render(label, True, (230,230,240))
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
                                line(f"   • {k2}: {v2}")
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
    def __init__(self, start_map: Optional[str]=None, start_entry: Optional[str]=None, start_pos: Optional[Tuple[int,int]]=None):
        random.seed()
        self.items   = gather_items()
        self.npcs    = gather_npcs()
        self.traits  = load_traits()
        self.enchants= load_enchants()
        self.magic   = load_magic()
        self.status  = load_status()
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
        self.player  = Player()
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

        weps  = [it for it in self.items if str(item_type(it)).lower() == 'weapon']
        melee = [w for w in weps if str(item_subtype(w)).lower() not in ('wand','staff')]
        focus = [w for w in weps if str(item_subtype(w)).lower() in ('wand','staff')]
        self.player.equipped_weapon = melee[0] if melee else (weps[0] if weps else None)
        self.player.equipped_focus  = focus[0] if focus else None

        if self.player.equipped_weapon:
            self.say(f"Equipped weapon: {item_name(self.player.equipped_weapon)}")
        if self.player.equipped_focus:
            self.say(f"Equipped focus: {item_name(self.player.equipped_focus)}")

        if not self.player.inventory and weps:
            self.player.inventory.append(weps[0])
            if len(weps) > 1:
                self.player.inventory.append(weps[1])

    # ---------- Save/Load ----------
    def _save_meta(self) -> Dict[str, Any]:
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
                'hp': self.player.hp,
                'max_hp': self.player.max_hp,
                'atk': list(self.player.atk),
                'stealth': self.player.stealth,
                'dex': self.player.dex,
                'affinity': dict(self.player.affinity),
                'romance_flags': dict(self.player.romance_flags),
                'inventory': list(self.player.inventory),
                'equipped_weapon': self.player.equipped_weapon,
                'equipped_focus': self.player.equipped_focus,
                'equipped_gear': dict(self.player.equipped_gear),
            },
            'playtime_s': int(getattr(self, 'playtime_ms', 0) // 1000),
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
            self.player.hp = int(p.get('hp', self.player.hp))
            self.player.max_hp = int(p.get('max_hp', self.player.max_hp))
        except Exception:
            pass
        try:
            atk = p.get('atk') or self.player.atk
            self.player.atk = (int(atk[0]), int(atk[1]))
        except Exception:
            pass
        self.player.stealth = int(p.get('stealth', self.player.stealth))
        self.player.dex = int(p.get('dex', self.player.dex))
        self.player.affinity = dict(p.get('affinity', self.player.affinity))
        self.player.romance_flags = dict(p.get('romance_flags', self.player.romance_flags))
        self.player.inventory = list(p.get('inventory', self.player.inventory))
        self.player.equipped_weapon = p.get('equipped_weapon')
        self.player.equipped_focus  = p.get('equipped_focus')
        self.player.equipped_gear   = dict(p.get('equipped_gear', self.player.equipped_gear))

        # Position
        pos = data.get('pos') or [0,0]
        self.player.x = max(0, min(self.W-1, int(pos[0] if len(pos)>0 else 0)))
        self.player.y = max(0, min(self.H-1, int(pos[1] if len(pos)>1 else 0)))
        try:
            self.grid[self.player.y][self.player.x].discovered = True
        except Exception:
            pass
        self.mode = 'explore'
        try:
            self.playtime_ms = int((data.get('playtime_s') or 0) * 1000)
        except Exception:
            self.playtime_ms = getattr(self, 'playtime_ms', 0)
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

    # ---------- Equipment actions ----------
    def equip_weapon(self, it: Dict):
        if item_type(it).lower() == "weapon" and item_subtype(it).lower() not in ("wand","staff"):
            self.player.equipped_weapon = it
            self.say(f"Equipped weapon: {item_name(it)}")
        else:
            self.say("That cannot be equipped as a weapon.")
    def equip_focus(self, it: Dict):
        if item_type(it).lower() == "weapon" and item_subtype(it).lower() in ("wand","staff"):
            self.player.equipped_focus = it
            self.say(f"Equipped focus: {item_name(it)}")
        else:
            self.say("You need a wand or staff as a focus.")
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
            raw = str(slots[0]).lower() if slots else str(item_subtype(it)).lower() or 'body'
            slot = normalize_slot(raw)
            if slot in ('weapon','weapon_main','weapon_off'):
                # Redirect weapons to equip_weapon/focus
                self.equip_item_to_slot('weapon_main', it)
            else:
                self.equip_item_to_slot(slot, it)
        elif m == 'weapon':
            sub = item_subtype(it).lower()
            if sub in ('wand','staff'):
                self.equip_focus(it)
            else:
                self.equip_weapon(it)
        else:
            self.say("That item cannot be equipped.")
    
    def equip_item_to_slot(self, slot: str, it: Dict):
        slot = normalize_slot(slot)
        if not slot_accepts(slot, it) and slot not in ('weapon_main','weapon_off'):
            self.say(f"{item_name(it)} cannot be equipped to {SLOT_LABELS.get(slot, slot)}.")
            return
        # Move previously equipped item (if any) back to inventory
        # Do not mutate inventory; just replace mapping
        self.player.equipped_gear[slot] = it
        # Also sync legacy fields for combat
        if slot == 'weapon_main':
            if str(item_subtype(it)).lower() in ('wand','staff'):
                self.player.equipped_focus = it
            else:
                self.player.equipped_weapon = it
        elif slot == 'weapon_off':
            # Only set focus if it's a wand/staff and no main focus is set
            if str(item_subtype(it)).lower() in ('wand','staff') and not self.player.equipped_focus:
                self.player.equipped_focus = it
        self.say(f"Equipped {item_name(it)} -> {SLOT_LABELS.get(slot, slot)}")

    def unequip_slot(self, slot: str):
        slot = normalize_slot(slot)
        it = self.player.equipped_gear.pop(slot, None)
        if it:
            # Clear legacy fields if they pointed to this item
            if slot == 'weapon_main' and self.player.equipped_weapon is it:
                self.player.equipped_weapon = None
            if slot in ('weapon_main','weapon_off') and self.player.equipped_focus is it:
                self.player.equipped_focus = None
            self.say(f"Unequipped {item_name(it)} from {SLOT_LABELS.get(slot, slot)}")
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
                    tag = 'monster' if sub == 'monsters' else 'enemy'
                    if t.encounter.spotted:
                        self.start_combat(t.encounter.enemy); self.say(f"{t.encounter.enemy.get('name','A foe')} spots you!", tag)
                    else:
                        self.say("An enemy lurks here... maybe you could sneak by.", tag)
                elif t.encounter.npc:
                    # Friendly presence does not block or force dialogue; allow passing by
                    sub = str((t.encounter.npc or {}).get('subcategory') or '').lower()
                    tag = 'ally' if sub == 'allies' else ('citizen' if sub == 'citizens' else ('animal' if sub == 'animals' else None))
                    self.say(f"You see {t.encounter.npc.get('name','someone')} here.", tag)
                elif t.encounter.event:
                    self.mode = "event"; self.say(f"You encounter {t.encounter.event}.", 'event')
            else:
                self.mode = "explore"

    def start_dialogue(self, npc): self.current_npc = npc

    def handle_dialogue_choice(self, choice: str):
        npc = self.current_npc;  nid = npc.get("id","?") if npc else "?"
        if not npc: return
        if choice == "Talk":
            self.player.affinity[nid] = self.player.affinity.get(nid,0) + 1
            # Log a simple, neutral interaction message
            self.say(f"You spoke to {npc.get('name','them')}.")
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

    def start_combat(self, enemy):
        self.current_enemy = enemy; self.current_enemy_hp = enemy.get("hp", 12)
        self.current_enemy.setdefault('status', [])
        self.current_enemy.setdefault('dex', 4)
        self.current_enemy.setdefault('will', 4)
        self.current_enemy.setdefault('greed', 4)
        self.can_bribe = False

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

    def attack(self):
        if not self.current_enemy: return
        base_min, base_max = self.player.atk
        wep = self.player.equipped_weapon or {}
        wmin, wmax, _, _ = _weapon_stats(wep)
        dmg = random.randint(base_min + wmin, base_max + max(wmax,0))
        dmg = max(1, dmg)
        self.current_enemy_hp -= dmg
        self.say(f"You strike with {item_name(wep) if wep else 'your weapon'} for {dmg}.")
        self._maybe_apply_status('melee', self.current_enemy, wep)
        if self.current_enemy_hp <= 0:
            self.say("Enemy defeated!")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
            self.current_enemy = None; self.mode = "explore"
        else:
            self.enemy_turn()

    def cast_spell(self):
        if not self.current_enemy:
            self.say("No target."); return
        if not self.player.equipped_focus:
            self.say("You need a wand or staff to focus your magic."); return
        if not self.magic:
            self.say("You don't recall any spells."); return
        spell = random.choice(self.magic)
        dmg = random.randint(4,8)
        self.current_enemy_hp -= dmg; self.say(f"You cast {spell.get('name','a spell')} through {item_name(self.player.equipped_focus)} for {dmg}!")
        self._maybe_apply_status('spell', self.current_enemy, self.player.equipped_focus)
        if self.current_enemy_hp <= 0:
            self.say("Enemy crumples.")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
            self.current_enemy = None; self.mode = "explore"
        else:
            self.enemy_turn()

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

    def talk_enemy(self):
        if not self.current_enemy: return
        will = int(self.current_enemy.get('will', 4))
        chance = max(0.1, min(0.8, 0.5 - 0.05*(will-4) + 0.05*len(self.player.romance_flags)))
        if random.random() < chance:
            self.say("You talk them down. The hostility fades.")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
            self.current_enemy = None; self.mode = "explore"
        else:
            self.say("They waver... maybe a bribe would help.")
            self.can_bribe = True

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

    def flee(self):
        if not self.current_enemy: return
        pDex = int(self.player.dex); eDex = int(self.current_enemy.get('dex',4))
        chance = max(0.1, min(0.95, 0.35 + 0.08*(pDex - eDex)))
        if random.random() < chance:
            self.say("You slip away into the brush.")
            self.mode = "explore"
            if self.player.y+1 < getattr(self, 'H', 8): self.player.y += 1
        else:
            self.say("You fail to escape!")
            self.enemy_turn()

    def enemy_turn(self):
        if not self.current_enemy: return
        dmg = random.randint(2,5); self.player.hp -= dmg; self.say(f"The enemy hits you for {dmg}.")
        if self.player.hp <= 0:
            self.say("You fall... but awaken at the trailhead, aching.")
            self.player.hp = self.player.max_hp; self.player.x = 0; self.player.y = 0; self.mode = "explore"

    def search_tile(self):
        t = self.tile()
        if not t.encounter:
            self.say("You find little of note."); return
        items = list(getattr(t.encounter, 'items', []) or [])
        if not items:
            t.encounter.item_searched = True
            self.say("You search thoroughly, but find nothing."); return
        # Loot one item per search
        item = items.pop(0)
        t.encounter.items = items
        self.player.inventory.append(item)
        # Tag quests for orange recent text
        tag = 'quest_item' if item_is_quest(item) else 'item'
        self.say(f"You found: {item_name(item)}!", tag)
        if not t.encounter.items:
            t.encounter.item_searched = True

# ======================== Start game (UI) ========================
def start_game(start_map: Optional[str]=None, start_entry: Optional[str]=None, start_pos: Optional[Tuple[int,int]]=None, load_slot: Optional[int]=None):
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

    game = Game(start_map=start_map, start_entry=start_entry, start_pos=start_pos)
    if load_slot is not None:
        try:
            game.load_from_slot(int(load_slot))
        except Exception:
            pass
    running = True
    while running:
        dt = clock.tick(60)
        # accumulate playtime
        try:
            game.playtime_ms = int(getattr(game, 'playtime_ms', 0)) + int(dt)
        except Exception:
            pass
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
                buttons_top = win_h - 210
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
                elif event.key == pg.K_i: game.mode = "inventory" if game.mode != "inventory" else "explore"
            elif event.type == pg.MOUSEBUTTONDOWN:
                for b in draw_panel(screen, game):
                    b.handle(event)
        screen.fill((16,16,22))
        draw_grid(screen, game)
        draw_panel(screen, game)
        pg.display.flip()
    pg.quit()


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

    mm_mode = 'menu'  # menu | load | options | info | credits
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

        # Tiny signal variables updated by buttons via closures
        class _Sig:
            def __init__(self): self.v = None
            def set(self, v): self.v = v
        _start = _Sig(); _mode = _Sig(); _page = _Sig()

        # Draw buttons
        for b in buttons: b.draw(screen)
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
            elif event.type == pg.MOUSEBUTTONDOWN:
                for b in buttons: b.handle(event)

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
        if _page.v is not None:
            load_page = max(0, int(_page.v)); _page.v = None
        if _start.v is not None:
            sel = _start.v
            if sel == 'new':
                return ('new', None)
            if isinstance(sel, tuple) and sel[0] == 'load':
                slot = int(sel[1]); return ('load', slot)
            _start.v = None

    return ('quit', None)

# ======================== CLI entry ========================
def main(argv=None):
    ap = argparse.ArgumentParser(description="RPGenesis-Fantasy – validate then launch game UI")
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
        start_game(start_map=args.start_map, start_entry=args.start_entry, start_pos=tuple(args.start_pos) if args.start_pos else None)
    elif sel == 'load' and data is not None:
        start_game(load_slot=int(data))
    else:
        print("Goodbye.")

if __name__ == "__main__":
    main()
