#!/usr/bin/env python3
from __future__ import annotations
import os, sys, json, re, argparse, random, math
from typing import Dict, Any, List, Tuple, Optional
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
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback if fallback is not None else {}
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
    return (it.get('type') or it.get('Type') or it.get('category') or
            it.get('slot') or it.get('item_type') or '?')

def item_subtype(it: dict) -> str:
    return (it.get('subtype') or it.get('SubType') or it.get('weapon_type') or
            it.get('class') or it.get('category2') or '-')

def item_desc(it: dict) -> str:
    return (it.get('desc') or it.get('description') or it.get('flavor') or '')

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
        for name in ["weapons.json","armour.json","accessories.json","clothing.json","materials.json","quest_items.json","trinkets.json"]:
            for it in safe_load_doc(os.path.join("items", name), "items"):
                items.append(it)
    return items

def gather_npcs() -> List[Dict]:
    npcs: List[Dict] = []
    npcs_dir = os.path.join(DATA_DIR, "npcs")
    if os.path.isdir(npcs_dir):
        for name in ["allies.json","animals.json","citizens.json","enemies.json","monsters.json"]:
            for n in safe_load_doc(os.path.join("npcs", name), "npcs"):
                npcs.append(n)
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

# ======================== Core structures ========================
@dataclass
class Encounter:
    npc: Optional[Dict] = None
    enemy: Optional[Dict] = None
    event: Optional[str] = None
    must_resolve: bool = False
    spotted: bool = False
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
    - encounters: minimal mapping of editor payloads to Encounter(npc/item)
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
                enc = Encounter()
                if cell.get('npc'):
                    enc.npc = cell.get('npc'); enc.must_resolve = False
                if cell.get('item'):
                    enc.item_here = cell.get('item')
                t.encounter = enc if (enc.npc or enc.item_here) else None

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

# ======================== UI helpers (MODULE-LEVEL) ========================
try:
    import pygame as pg
except Exception:
    pg = None  # checked at runtime

def draw_text(surface, text, pos, color=(230,230,230), font=None, max_w=None):
    if font is None:
        if pg is None:
            raise RuntimeError("pygame not available")
        font = pg.font.Font(None, 18)
    if not max_w:
        surface.blit(font.render(text, True, color), pos); return
    words = text.split(" "); x,y = pos; line = ""
    for w in words:
        test = (line + " " + w).strip()
        if font.size(test)[0] <= max_w: line = test
        else:
            surface.blit(font.render(line, True, color), (x,y))
            y += font.get_linesize()
            line = w
    if line: surface.blit(font.render(line, True, color), (x,y))

class Button:
    def __init__(self, rect, label, cb):
        if pg is None:
            raise RuntimeError("pygame not available")
        self.rect = pg.Rect(rect); self.label = label; self.cb = cb
    def draw(self, surf):
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

    # Colors
    COL_ENEMY  = (190,70,70)
    COL_NPC    = (90,170,110)
    COL_EVENT  = (160,130,200)
    COL_LINK   = (255,105,180)  # match editor's link color (pink)
    COL_PLAYER = (122,162,247)  # accent

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
                if tile.encounter.enemy:
                    dot_colors.append(COL_ENEMY)
                if tile.encounter.npc:
                    dot_colors.append(COL_NPC)
                if tile.encounter.event:
                    dot_colors.append(COL_EVENT)
                if getattr(tile.encounter, 'item_here', None):
                    dot_colors.append((230,230,230))  # item present
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

    # Tile / Equipped summary
    t = game.tile(); y = 44
    draw_text(surf, f"Tile ({t.x},{t.y})", (x0+16, y)); y += 18
    draw_text(surf, t.description, (x0+16, y), max_w=panel_w-32); y += 40
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
        if not t.encounter.item_searched:
            draw_text(surf, "Area can be searched.", (x0+16, y), (200,200,240)); y += 18
        else:
            draw_text(surf, "Area already searched.", (x0+16, y), (160,160,180)); y += 18

    # Player + log
    y += 6
    draw_text(surf, f"HP: {game.player.hp}/{game.player.max_hp}", (x0+16, y)); y += 18
    draw_text(surf, f"Inventory: {len(game.player.inventory)}", (x0+16, y)); y += 24
    draw_text(surf, "Recent:", (x0+16, y)); y += 16
    for line in game.log[-6:]:
        draw_text(surf, f"• {line}", (x0+20, y), max_w=panel_w-36); y += 16

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
        add("Inventory / Equip", lambda: setattr(game, 'mode', 'inventory'))
    elif game.mode == "dialogue":
        add("Talk",  lambda: game.handle_dialogue_choice("Talk"))
        add("Flirt", lambda: game.handle_dialogue_choice("Flirt"))
        add("Leave", lambda: game.handle_dialogue_choice("Leave"))
        add("Inventory / Equip", lambda: setattr(game, 'mode', 'inventory'))
    elif game.mode == "inventory":
        buttons += draw_inventory_panel(surf, game, x0, panel_w)
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
        add("Inventory / Equip", lambda: setattr(game, 'mode', 'inventory'))

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
        # Load start map from world_map.json and build grid from editor/runtime
        wm_map, wm_entry, wm_pos = get_game_start()
        sel_map = start_map or wm_map or "Jungle of Hills"
        entry_name = start_entry if start_entry is not None else wm_entry
        pos = start_pos if start_pos is not None else wm_pos
        scene = load_scene_by_name('map', sel_map)
        runtime = scene_to_runtime(scene)
        self.W, self.H = int(runtime.get('width', 12)), int(runtime.get('height', 8))
        self.tile_px = int(runtime.get('tile_size', 32))
        self.grid    = grid_from_runtime(runtime, self.items, self.npcs)
        self.current_map_name = runtime.get('name', sel_map)
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
        self.player.x = max(0, min(self.W-1, px))
        self.player.y = max(0, min(self.H-1, py))
        # Mark starting tile discovered
        try:
            self.grid[self.player.y][self.player.x].discovered = True
        except Exception:
            pass
        self.log: List[str] = ["You arrive at the edge of the wilds."]
        self.mode = "explore"
        self.current_enemy_hp = 0
        self.current_enemy = None
        self.current_npc = None
        self.can_bribe = False
        self.inv_page = 0
        self.inv_sel = None

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

    def tile(self, x=None, y=None) -> Tile:
        if x is None: x = self.player.x
        if y is None: y = self.player.y
        return self.grid[y][x]

    def say(self, msg: str):
        self.log.append(msg)
        if len(self.log) > 8: self.log = self.log[-8:]

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
            it = self.player.inventory.pop(idx)
            self.say(f"Dropped: {item_name(it)}")
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
                if str(to) == str(getattr(self, 'current_map_name', '')):
                    back = (int(lx), int(ly)); break
            if back:
                px, py = back
        # Rebuild grid, move player
        self.W, self.H = int(runtime.get('width', 12)), int(runtime.get('height', 8))
        self.tile_px = int(runtime.get('tile_size', 32))
        self.grid    = grid_from_runtime(runtime, self.items, self.npcs)
        self.current_map_name = runtime.get('name', dest_map)
        self.player.x = max(0, min(self.W-1, int(px)))
        self.player.y = max(0, min(self.H-1, int(py)))
        try:
            self.grid[self.player.y][self.player.x].discovered = True
        except Exception:
            pass
        self.mode = "explore"
        self.say(f"You travel to {self.current_map_name}.")

    def can_leave_tile(self) -> bool:
        t = self.tile()
        if not t.encounter: return True
        if not t.encounter.must_resolve: return True
        if self.mode in ("dialogue","combat","event"): return False
        if t.encounter.npc or t.encounter.enemy or t.encounter.event: return False
        return True

    def move(self, dx, dy):
        if not self.can_leave_tile():
            self.say("Resolve the encounter before moving on."); return
        nx, ny = self.player.x + dx, self.player.y + dy
        if 0 <= nx < getattr(self, 'W', 12) and 0 <= ny < getattr(self, 'H', 8):
            # Block movement onto impassable tiles
            try:
                target = self.grid[ny][nx]
                if not target.walkable:
                    return
            except Exception:
                pass
            self.player.x, self.player.y = nx, ny
            t = self.tile(); t.discovered = True; t.visited += 1
            if t.encounter:
                if t.encounter.enemy:
                    self.mode = "combat" if t.encounter.spotted else "explore"
                    if t.encounter.spotted:
                        self.start_combat(t.encounter.enemy); self.say(f"{t.encounter.enemy.get('name','A foe')} spots you!")
                    else:
                        self.say("An enemy lurks here... maybe you could sneak by.")
                elif t.encounter.npc:
                    self.mode = "dialogue"; self.start_dialogue(t.encounter.npc); self.say(f"You meet {t.encounter.npc.get('name','someone')}.")
                elif t.encounter.event:
                    self.mode = "event"; self.say(f"You encounter {t.encounter.event}.")
            else:
                self.mode = "explore"

    def start_dialogue(self, npc): self.current_npc = npc

    def handle_dialogue_choice(self, choice: str):
        npc = self.current_npc;  nid = npc.get("id","?") if npc else "?"
        if not npc: return
        if choice == "Talk":
            self.player.affinity[nid] = self.player.affinity.get(nid,0) + 1
            self.say(f"You talk with {npc.get('name','them')} (+affinity).")
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
            self.say("You slip past unnoticed."); t.encounter.enemy = None; t.encounter.must_resolve = False; self.mode = "explore"
        else:
            self.say("You stumble—you're spotted!"); t.encounter.spotted = True; self.start_combat(t.encounter.enemy)

    def bypass_enemy(self):
        t = self.tile()
        if t.encounter and t.encounter.enemy and not t.encounter.spotted:
            self.say("You give the area a wide berth. (You can leave now.)")
            t.encounter.must_resolve = False; self.mode = "explore"
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
        if t.encounter.item_searched:
            self.say("You've already scoured this area."); return
        t.encounter.item_searched = True
        if t.encounter.item_here:
            item = t.encounter.item_here; self.player.inventory.append(item)
            self.say(f"You found: {item_name(item)}!"); t.encounter.item_here = None
        else:
            self.say("You search thoroughly, but find nothing this time.")

# ======================== Start game (UI) ========================
def start_game(start_map: Optional[str]=None, start_entry: Optional[str]=None, start_pos: Optional[Tuple[int,int]]=None):
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
    # Create normal window, then ask OS to maximize (Windows)
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
    running = True
    while running:
        dt = clock.tick(60)
        for event in pg.event.get():
            if event.type == pg.QUIT:
                running = False
            elif event.type == pg.VIDEORESIZE:
                screen = pg.display.set_mode((event.w, event.h), pg.RESIZABLE)
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE: 
                    if game.mode == "inventory":
                        game.mode = "explore"
                    else:
                        running = False
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

    print("\n[OK] Validation passed. Launching game...")
    start_game(start_map=args.start_map, start_entry=args.start_entry, start_pos=tuple(args.start_pos) if args.start_pos else None)

if __name__ == "__main__":
    main()
