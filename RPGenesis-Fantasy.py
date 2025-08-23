#!/usr/bin/env python3
from __future__ import annotations
import os, sys, json, re, argparse, random
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
print(f"[GAME]  Version     = 0.2.x")
print(f"[GAME]  CWD         = {os.getcwd()}")
print(f"[GAME]  SCRIPT      = {__file__}")
print(f"[GAME]  DATA_DIR    = {DATA_DIR}")
print(f"[GAME]  WORLD_MAP   = {DATA_DIR / 'world_map.txt'}")
print(f"[GAME]  OVERRIDES   = {DATA_DIR / 'world_overrides.json'}")


# -------------------- Project paths / version --------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
VERSION_FILE = os.path.join(os.path.dirname(__file__), "VERSION.txt")

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
<<<<<<< Updated upstream
        if v is None: 
=======
        if v is None:
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
    """Returns (min_bonus, max_bonus, status_chance, statuses) reading multiple possible keys safely."""
=======
>>>>>>> Stashed changes
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
        for name in ["weapons.json","armours.json","accessories.json","clothing.json","materials.json","quest_items.json","trinkets.json"]:
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

@dataclass
class Player:
    x: int = 0
    y: int = 0
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
<<<<<<< Updated upstream
=======

def generate_path(w, h) -> List[Tuple[int,int]]:
    # Simple random walk from (0,0) to (w-1,h-1), biased to the right
    x, y = 0, 0
    path = [(x,y)]
    while x < w-1 or y < h-1:
        moves = []
        if x < w-1: moves += [(1,0)]*2  # bias right
        if y < h-1: moves += [(0,1)]
        dx, dy = random.choice(moves)
        x, y = x+dx, y+dy
        if (x,y) not in path:
            path.append((x,y))
    # add occasional side spur
    for _ in range(max(2, (w+h)//6)):
        px, py = random.choice(path)
        for dx,dy in random.sample([(1,0),(-1,0),(0,1),(0,-1)], k=2):
            nx, ny = px+dx, py+dy
            if 0 <= nx < w and 0 <= ny < h:
                path.append((nx,ny))
    return list(dict.fromkeys(path))  # unique preserve order
>>>>>>> Stashed changes

def generate_world(items, npcs) -> List[List[Tile]]:
    W, H = 12, 8
    grid: List[List[Tile]] = [[Tile(x=x, y=y) for x in range(W)] for y in range(H)]
    path = set(generate_path(W, H))

    for y in range(H):
        for x in range(W):
            t = grid[y][x]
            t.walkable = (x,y) in path
            t.description = random.choice([
                "Wind-swept brush and bent reeds.",
                "Ancient stones half-swallowed by moss.",
                "A hush falls here, like a held breath.",
                "Dappled light flickers between tall birches.",
                "A trampled path suggests recent travelers."
            ])
<<<<<<< Updated upstream
            enc = Encounter()
            r = random.random()
            if r < 0.3:
                enc.enemy = pick_enemy(npcs); enc.must_resolve = True; enc.spotted = random.random() < 0.6
            elif r < 0.6:
                enc.npc = pick_npc(npcs); enc.must_resolve = True
            elif r < 0.7:
                enc.event = random.choice(["ancient shrine","abandoned camp","strange circle of mushrooms"]); enc.must_resolve = True
            enc.item_here = pick_item(items)
            t.encounter = enc
            row.append(t)
        grid.append(row)
    grid[0][0].description = "A lonely milestone marks the trailhead."
    grid[0][0].discovered = True
=======
            if t.walkable:
                enc = Encounter()
                r = random.random()
                if r < 0.3:
                    enc.enemy = pick_enemy(npcs); enc.must_resolve = True; enc.spotted = random.random() < 0.6
                elif r < 0.6:
                    enc.npc = pick_npc(npcs); enc.must_resolve = True
                elif r < 0.7:
                    enc.event = random.choice(["ancient shrine","abandoned camp","strange circle of mushrooms"]); enc.must_resolve = True
                enc.item_here = pick_item(items)
                t.encounter = enc

    start = grid[0][0]
    start.description = "A lonely milestone marks the trailhead."
    start.walkable = True
    start.discovered = True
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
        pg.draw.rect(surf, (60,60,70), self.rect, border_radius=8)
        pg.draw.rect(surf, (110,110,130), self.rect, 2, border_radius=8)
=======
        mx, my = pg.mouse.get_pos()
        hovered = self.rect.collidepoint(mx, my)
        bg = (70,70,88) if hovered else (60,60,70)
        border = (140,140,180) if hovered else (110,110,130)
        pg.draw.rect(surf, bg, self.rect, border_radius=8)
        pg.draw.rect(surf, border, self.rect, 2, border_radius=8)
>>>>>>> Stashed changes
        label = label_font.render(self.label, True, (240,240,255))
        surf.blit(label, (self.rect.x + 10, self.rect.y + (self.rect.h - label.get_height())//2))
    def handle(self, event):
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            self.cb()

def draw_grid(surf, game):
<<<<<<< Updated upstream
    pg.draw.rect(surf, (26,26,32), (0,0, 980 - 360, 640))
=======
    # Background
    pg.draw.rect(surf, (22,22,28), (0,0, 980 - 360, 640))
    # Draw path tiles only; non-walkable are faint hints
>>>>>>> Stashed changes
    for y in range(8):
        for x in range(12):
            rx, ry = x*44 + 12, y*44 + 12
            r = pg.Rect(rx, ry, 40, 40)
            tile = game.grid[y][x]
<<<<<<< Updated upstream
            base = (42,44,56) if tile.discovered else (28,30,38)
            pg.draw.rect(surf, base, r, border_radius=6)
            pg.draw.rect(surf, (70,74,92), r, 1, border_radius=6)
            if tile.encounter:
                if tile.encounter.enemy:  pg.draw.circle(surf, (190,70,70),   (r.centerx, r.centery), 4)
                elif tile.encounter.npc: pg.draw.circle(surf, (90,170,110),  (r.centerx, r.centery), 4)
                elif tile.encounter.event: pg.draw.circle(surf, (160,130,200),(r.centerx, r.centery), 4)
=======
            if tile.walkable:
                base = (52,56,72) if tile.discovered else (42,46,60)
                pg.draw.rect(surf, base, r, border_radius=10)
                pg.draw.rect(surf, (90,94,112), r, 1, border_radius=10)
                # NO encounter dots (requirement #2)
            else:
                # faint suggestion of blocked tiles to imply terrain
                pg.draw.rect(surf, (18,18,24), r, border_radius=8)
    # player marker
>>>>>>> Stashed changes
    px = game.player.x*44 + 12 + 20
    py = game.player.y*44 + 12 + 20
    pg.draw.circle(surf, (235,235,80), (px,py), 7)

def draw_panel(surf, game):
    x0 = 980 - 360
    pg.draw.rect(surf, (18,18,24), (x0,0, 360, 640))
    pg.draw.rect(surf, (70,74,92), (x0,0, 360, 640), 1)
    header_font = pg.font.Font(None, 22)
    draw_text(surf, f"RPGenesis v{get_version()} – Field Log", (x0+16, 12), font=header_font)

    # Tile / Equipped summary
    t = game.tile(); y = 44
    draw_text(surf, f"Tile ({t.x},{t.y})", (x0+16, y)); y += 18
    draw_text(surf, t.description, (x0+16, y), max_w=360-32); y += 40
    # Equipped
<<<<<<< Updated upstream
    wep = item_name(game.player.equipped_weapon) if game.player.equipped_weapon else "None"
    foc = item_name(game.player.equipped_focus) if game.player.equipped_focus else "None"
    draw_text(surf, f"Weapon: {wep}", (x0+16, y)); y += 18
    draw_text(surf, f"Focus : {foc}", (x0+16, y)); y += 24

    # Encounter info
=======
    wep = (game.player.equipped_weapon or {}).get('name') or (game.player.equipped_weapon or {}).get('Name') or "None"
    foc = (game.player.equipped_focus or {}).get('name') or (game.player.equipped_focus or {}).get('Name') or "None"
    draw_text(surf, f"Weapon: {wep}", (x0+16, y)); y += 18
    draw_text(surf, f"Focus : {foc}", (x0+16, y)); y += 24

    # Encounter info (still hidden on grid; shown here when present)
>>>>>>> Stashed changes
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
        draw_text(surf, f"• {line}", (x0+20, y), max_w=360-36); y += 16

<<<<<<< Updated upstream
    # Buttons
=======
    # Buttons (with hover glow handled inside Button.draw)
>>>>>>> Stashed changes
    y0 = 640 - 210
    buttons = []
    def add(label, cb):
        nonlocal y0
        buttons.append(Button((x0+16, y0, 360-32, 34), label, cb)); y0 += 38

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
        buttons += draw_inventory_panel(surf, game, x0)
    else:
        add("Search Area", game.search_tile)
<<<<<<< Updated upstream
=======
        t = game.tile()
>>>>>>> Stashed changes
        if t.encounter and t.encounter.enemy and not t.encounter.spotted:
            add("Sneak Past",            game.try_sneak)
            add("Bypass (Skirt Around)", game.bypass_enemy)
        if t.encounter and t.encounter.enemy and t.encounter.spotted:
            add("Fight", lambda: game.start_combat(t.encounter.enemy))
        if t.encounter and t.encounter.npc:
            add("Talk",      lambda: game.start_dialogue(t.encounter.npc))
            add("Leave NPC", lambda: game.handle_dialogue_choice("Leave"))
        add("Inventory / Equip", lambda: setattr(game, 'mode', 'inventory'))

    for b in buttons: b.draw(surf)
    return buttons

def draw_inventory_panel(surf, game, x0):
<<<<<<< Updated upstream
    """Returns list of Button objects for the inventory sub-panel."""
    buttons = []
    # panel header
=======
    buttons = []
>>>>>>> Stashed changes
    y = 320
    pg.draw.line(surf, (70,74,92), (x0+12, y-6), (x0+360-12, y-6), 1)
    draw_text(surf, "Inventory", (x0+16, y)); y += 20

<<<<<<< Updated upstream
    # pagination state
=======
>>>>>>> Stashed changes
    if not hasattr(game, "inv_page"): game.inv_page = 0
    if not hasattr(game, "inv_sel"): game.inv_sel = None

    per_page = 6
    total = len(game.player.inventory)
    pages = max(1, (total + per_page - 1)//per_page)
    page = max(0, min(game.inv_page, pages-1))
    start = page*per_page
    items = game.player.inventory[start:start+per_page]

<<<<<<< Updated upstream
    # list items as clickable rows
=======
>>>>>>> Stashed changes
    row_h = 26
    for i, it in enumerate(items):
        r = pg.Rect(x0+16, y+i*row_h, 360-32, row_h-4)
        sel = (game.inv_sel == start+i)
<<<<<<< Updated upstream
        pg.draw.rect(surf, (52,56,70) if sel else (34,36,46), r, border_radius=6)
        pg.draw.rect(surf, (90,94,112), r, 1, border_radius=6)
        label = f"{item_name(it)}  [{item_type(it)}/{item_subtype(it)}]"
=======
        mx, my = pg.mouse.get_pos()
        hovered = r.collidepoint(mx, my)
        base = (58,60,76) if hovered else (52,56,70)
        pg.draw.rect(surf, base if sel else (34,36,46), r, border_radius=6)
        pg.draw.rect(surf, (120,124,150) if hovered else (90,94,112), r, 1, border_radius=6)
        label = f"{(it.get('name') or it.get('Name') or '?')}  [{(it.get('type') or it.get('Type') or '?')}/{(it.get('subtype') or it.get('SubType') or '-')}]"
>>>>>>> Stashed changes
        draw_text(surf, label, (r.x+8, r.y+5))
        def make_sel(idx):
            return lambda idx=idx: setattr(game, 'inv_sel', idx)
        buttons.append(Button(r, "", make_sel(start+i)))

    y += per_page*row_h + 4

<<<<<<< Updated upstream
    # info & actions for selected item
    if game.inv_sel is not None and 0 <= game.inv_sel < total:
        it = game.player.inventory[game.inv_sel]
        draw_text(surf, (item_desc(it) or "-"), (x0+16, y), max_w=360-32); y += 36
        subtype = str(item_subtype(it)).lower()
        typ = str(item_type(it)).lower()
=======
    if game.inv_sel is not None and 0 <= game.inv_sel < total:
        it = game.player.inventory[game.inv_sel]
        draw_text(surf, (it.get('desc') or "-"), (x0+16, y), max_w=360-32); y += 36
        subtype = str((it.get('subtype') or it.get('SubType') or '')).lower()
        typ = str((it.get('type') or it.get('Type') or '')).lower()
>>>>>>> Stashed changes
        if typ == "weapon":
            if subtype in ("wand","staff"):
                buttons.append(Button((x0+16, y, 160, 30), "Equip as Focus", lambda: game.equip_focus(it)))
                y += 34
            else:
                buttons.append(Button((x0+16, y, 160, 30), "Equip Weapon", lambda: game.equip_weapon(it)))
                y += 34
<<<<<<< Updated upstream
        # Drop button
        buttons.append(Button((x0+16, y, 160, 30), "Drop", lambda: game.drop_item(game.inv_sel)))
        # Close
        buttons.append(Button((x0+16+170, y, 160, 30), "Close", lambda: setattr(game,'mode','explore')))
    else:
        # Pager + Close when nothing selected
=======
        buttons.append(Button((x0+16, y, 160, 30), "Drop", lambda: game.drop_item(game.inv_sel)))
        buttons.append(Button((x0+16+170, y, 160, 30), "Close", lambda: setattr(game,'mode','explore')))
    else:
>>>>>>> Stashed changes
        buttons.append(Button((x0+16, y, 110, 28), "Prev Page", lambda: setattr(game,'inv_page', max(0, game.inv_page-1))))
        buttons.append(Button((x0+16+120, y, 110, 28), "Next Page", lambda: setattr(game,'inv_page', min(pages-1, game.inv_page+1))))
        buttons.append(Button((x0+16+240, y, 90, 28), "Close", lambda: setattr(game,'mode','explore')))

    return buttons

# ======================== Game class + loop ========================
class Game:
    def __init__(self):
        random.seed()
        self.items   = gather_items()
        self.npcs    = gather_npcs()
        self.traits  = load_traits()
        self.enchants= load_enchants()
        self.magic   = load_magic()
        self.status  = load_status()
        self.grid    = generate_world(self.items, self.npcs)
        self.player  = Player()
        self.log: List[str] = ["You arrive at the edge of the wilds."]
        self.mode = "explore"
        self.current_enemy_hp = 0
        self.current_enemy = None
        self.current_npc = None
        self.can_bribe = False
        self.inv_page = 0
        self.inv_sel = None

<<<<<<< Updated upstream
        weps  = [it for it in self.items if str(item_type(it)).lower() == 'weapon']
        melee = [w for w in weps if str(item_subtype(w)).lower() not in ('wand','staff')]
        focus = [w for w in weps if str(item_subtype(w)).lower() in ('wand','staff')]
        self.player.equipped_weapon = melee[0] if melee else (weps[0] if weps else None)
        self.player.equipped_focus  = focus[0] if focus else None

        if self.player.equipped_weapon:
            self.say(f"Equipped weapon: {item_name(self.player.equipped_weapon)}")
        if self.player.equipped_focus:
            self.say(f"Equipped focus: {item_name(self.player.equipped_focus)}")

=======
        weps  = [it for it in self.items if str((it.get('type') or it.get('Type') or '')).lower() == 'weapon']
        melee = [w for w in weps if str((w.get('subtype') or w.get('SubType') or '')).lower() not in ('wand','staff')]
        focus = [w for w in weps if str((w.get('subtype') or w.get('SubType') or '')).lower() in ('wand','staff')]
        self.player.equipped_weapon = melee[0] if melee else (weps[0] if weps else None)
        self.player.equipped_focus  = focus[0] if focus else None

>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
        if item_type(it).lower() == "weapon" and item_subtype(it).lower() not in ("wand","staff"):
            self.player.equipped_weapon = it
            self.say(f"Equipped weapon: {item_name(it)}")
        else:
            self.say("That cannot be equipped as a weapon.")
    def equip_focus(self, it: Dict):
        if item_type(it).lower() == "weapon" and item_subtype(it).lower() in ("wand","staff"):
            self.player.equipped_focus = it
            self.say(f"Equipped focus: {item_name(it)}")
=======
        typ = str((it.get('type') or it.get('Type') or '')).lower()
        sub = str((it.get('subtype') or it.get('SubType') or '')).lower()
        if typ == "weapon" and sub not in ("wand","staff"):
            self.player.equipped_weapon = it
            self.say(f"Equipped weapon: {(it.get('name') or it.get('Name') or '?')}")
        else:
            self.say("That cannot be equipped as a weapon.")
    def equip_focus(self, it: Dict):
        typ = str((it.get('type') or it.get('Type') or '')).lower()
        sub = str((it.get('subtype') or it.get('SubType') or '')).lower()
        if typ == "weapon" and sub in ("wand","staff"):
            self.player.equipped_focus = it
            self.say(f"Equipped focus: {(it.get('name') or it.get('Name') or '?')}")
>>>>>>> Stashed changes
        else:
            self.say("You need a wand or staff as a focus.")
    def drop_item(self, idx: int):
        if 0 <= idx < len(self.player.inventory):
            it = self.player.inventory.pop(idx)
<<<<<<< Updated upstream
            self.say(f"Dropped: {item_name(it)}")
            self.inv_sel = None

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
        if 0 <= nx < 12 and 0 <= ny < 8:
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
=======
            self.say(f"Dropped: {(it.get('name') or it.get('Name') or '?')}")
            self.inv_sel = None

    # ---------- Movement rules ----------
    def can_leave_tile(self) -> bool:
        """You can always leave unless **there is an enemy here** (requirement #1)."""
        t = self.tile()
        return not (t.encounter and t.encounter.enemy)

    def move(self, dx, dy):
        if not self.can_leave_tile():
            self.say("An enemy blocks your way!"); return
        nx, ny = self.player.x + dx, self.player.y + dy
        if not (0 <= nx < 12 and 0 <= ny < 8):
            return
        nt = self.grid[ny][nx]
        if not nt.walkable:
            self.say("The undergrowth is too thick that way."); return
        self.player.x, self.player.y = nx, ny
        t = self.tile(); t.discovered = True; t.visited += 1
        if t.encounter:
            if t.encounter.enemy:
                # Do not auto-start combat if not spotted; let player decide (sneak/fight)
                if t.encounter.spotted:
                    self.start_combat(t.encounter.enemy)
                    self.say(f"{t.encounter.enemy.get('name','A foe')} spots you!")
                else:
                    self.mode = "explore"
                    self.say("You sense danger nearby...")
            elif t.encounter.npc:
                # Do not force dialogue; player may pass through
                self.mode = "explore"
                self.say("You pass a traveler on the path.")
            elif t.encounter.event:
                self.mode = "explore"
                self.say("Something curious lies just off the trail.")
        else:
            self.mode = "explore"

    def start_dialogue(self, npc): self.current_npc = npc; self.mode = "dialogue"
>>>>>>> Stashed changes

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
<<<<<<< Updated upstream
            t = self.tile(); t.encounter.npc = None; t.encounter.must_resolve = False
=======
            t = self.tile(); t.encounter.npc = None; 
>>>>>>> Stashed changes
            self.current_npc = None; self.mode = "explore"
        else:
            self.say("You share a few words.")

<<<<<<< Updated upstream
=======
    # ---- Combat / statuses / diplomacy ----
>>>>>>> Stashed changes
    def start_combat(self, enemy):
        self.current_enemy = enemy; self.current_enemy_hp = enemy.get("hp", 12)
        self.current_enemy.setdefault('status', [])
        self.current_enemy.setdefault('dex', 4)
        self.current_enemy.setdefault('will', 4)
        self.current_enemy.setdefault('greed', 4)
        self.can_bribe = False
<<<<<<< Updated upstream
=======
        self.mode = "combat"

    def _weapon_stats(self, it: Dict) -> Tuple[int,int,float,List[str]]:
        return _weapon_stats(it)
>>>>>>> Stashed changes

    def _maybe_apply_status(self, source: str, target: Dict, weapon_or_spell: Optional[Dict]=None):
        chance = 0.15
        pool = ["bleed","burn","shock","freeze","poison"]
        if weapon_or_spell:
<<<<<<< Updated upstream
            wmin, wmax, st_ch, statuses = _weapon_stats(weapon_or_spell)
            chance = st_ch or chance
            if statuses: pool = statuses
            else:
                st = item_subtype(weapon_or_spell).lower()
=======
            wmin, wmax, st_ch, statuses = self._weapon_stats(weapon_or_spell)
            chance = st_ch or chance
            if statuses: pool = statuses
            else:
                st = str((weapon_or_spell.get('subtype') or weapon_or_spell.get('SubType') or '')).lower()
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
        wmin, wmax, _, _ = _weapon_stats(wep)
        dmg = random.randint(base_min + wmin, base_max + max(wmax,0))
        dmg = max(1, dmg)
        self.current_enemy_hp -= dmg
        self.say(f"You strike with {item_name(wep) if wep else 'your weapon'} for {dmg}.")
        self._maybe_apply_status('melee', self.current_enemy, wep)
        if self.current_enemy_hp <= 0:
            self.say("Enemy defeated!")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
=======
        wmin, wmax, _, _ = self._weapon_stats(wep)
        dmg = random.randint(base_min + wmin, base_max + max(wmax,0))
        dmg = max(1, dmg)
        self.current_enemy_hp -= dmg
        self.say(f"You strike with {(wep.get('name') or wep.get('Name') or 'your weapon')} for {dmg}.")
        self._maybe_apply_status('melee', self.current_enemy, wep)
        if self.current_enemy_hp <= 0:
            self.say("Enemy defeated!")
            t = self.tile(); t.encounter.enemy = None
>>>>>>> Stashed changes
            self.current_enemy = None; self.mode = "explore"
        else:
            self.enemy_turn()

    def cast_spell(self):
        if not self.current_enemy:
            self.say("No target."); return
        if not self.player.equipped_focus:
            self.say("You need a wand or staff to focus your magic."); return
<<<<<<< Updated upstream
        if not self.magic:
            self.say("You don't recall any spells."); return
        spell = random.choice(self.magic)
        dmg = random.randint(4,8)
        self.current_enemy_hp -= dmg; self.say(f"You cast {spell.get('name','a spell')} through {item_name(self.player.equipped_focus)} for {dmg}!")
        self._maybe_apply_status('spell', self.current_enemy, self.player.equipped_focus)
        if self.current_enemy_hp <= 0:
            self.say("Enemy crumples.")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
=======
        spell_name = "a spell"
        dmg = random.randint(4,8)
        self.current_enemy_hp -= dmg; self.say(f"You cast {spell_name} through {(self.player.equipped_focus.get('name') or self.player.equipped_focus.get('Name') or 'your focus')} for {dmg}!")
        self._maybe_apply_status('spell', self.current_enemy, self.player.equipped_focus)
        if self.current_enemy_hp <= 0:
            self.say("Enemy crumples.")
            t = self.tile(); t.encounter.enemy = None
>>>>>>> Stashed changes
            self.current_enemy = None; self.mode = "explore"
        else:
            self.enemy_turn()

    def try_sneak(self):
        t = self.tile()
        if not (t.encounter and t.encounter.enemy and not t.encounter.spotted):
            self.say("No unnoticed enemy to sneak by."); return
        dc = 8 + random.randint(0,4); roll = 4 + random.randint(1,10)
        if roll >= dc:
<<<<<<< Updated upstream
            self.say("You slip past unnoticed."); t.encounter.enemy = None; t.encounter.must_resolve = False; self.mode = "explore"
=======
            self.say("You slip past unnoticed."); t.encounter.enemy = None; self.mode = "explore"
>>>>>>> Stashed changes
        else:
            self.say("You stumble—you're spotted!"); t.encounter.spotted = True; self.start_combat(t.encounter.enemy)

    def bypass_enemy(self):
        t = self.tile()
        if t.encounter and t.encounter.enemy and not t.encounter.spotted:
<<<<<<< Updated upstream
            self.say("You give the area a wide berth. (You can leave now.)")
            t.encounter.must_resolve = False; self.mode = "explore"
=======
            self.say("You skirt around the danger.")
            t.encounter.enemy = None
            self.mode = "explore"
>>>>>>> Stashed changes
        else:
            self.say("Too risky to bypass.")

    def talk_enemy(self):
        if not self.current_enemy: return
        will = int(self.current_enemy.get('will', 4))
<<<<<<< Updated upstream
        chance = max(0.1, min(0.8, 0.5 - 0.05*(will-4) + 0.05*len(self.player.romance_flags)))
        if random.random() < chance:
            self.say("You talk them down. The hostility fades.")
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
=======
        chance = max(0.1, min(0.8, 0.5 - 0.05*(will-4)))
        if random.random() < chance:
            self.say("You talk them down. The hostility fades.")
            t = self.tile(); t.encounter.enemy = None
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
            if item_type(it).lower() in ('trinket','material','accessory','materials'):
                item = it; break
        if item:
            self.player.inventory.remove(item)
            self.say(f"You offer {item_name(item)}...")
=======
            if (it.get('type') or it.get('Type')) in ('trinket','material','accessory','materials'):
                item = it; break
        if item:
            self.player.inventory.remove(item)
            self.say(f"You offer {(item.get('name') or item.get('Name') or 'a trinket')}...")
>>>>>>> Stashed changes
        else:
            self.say("You offer future favors...")
        if random.random() < chance:
            self.say("The bribe works. They let you pass.")
<<<<<<< Updated upstream
            t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
=======
            t = self.tile(); t.encounter.enemy = None
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
            if self.player.y+1 < 8: self.player.y += 1
=======
            # Move one step forward along the path if possible
            for dx,dy in [(1,0),(0,1),(-1,0),(0,-1)]:
                nx, ny = self.player.x+dx, self.player.y+dy
                if 0 <= nx < 12 and 0 <= ny < 8 and self.grid[ny][nx].walkable:
                    self.player.x, self.player.y = nx, ny; break
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
            self.say(f"You found: {item_name(item)}!"); t.encounter.item_here = None
=======
            self.say(f"You found: {(item.get('name') or item.get('Name') or 'something')}!"); t.encounter.item_here = None
>>>>>>> Stashed changes
        else:
            self.say("You search thoroughly, but find nothing this time.")

# ======================== Start game (UI) ========================
def start_game():
    if pg is None:
        try:
            import pygame as _pg  # late import to show friendly error
        except ImportError:
            print("[ERR] pygame not installed. Run: pip install pygame")
            sys.exit(1)

    version = get_version()
    pg.init()
    pg.display.set_caption(f"RPGenesis {version} – Text RPG")
    screen = pg.display.set_mode((980, 640))
    clock = pg.time.Clock()

    game = Game()
    running = True
    while running:
        dt = clock.tick(60)
        for event in pg.event.get():
            if event.type == pg.QUIT:
                running = False
            elif event.type == pg.KEYDOWN:
<<<<<<< Updated upstream
                if event.key == pg.K_ESCAPE: 
=======
                if event.key == pg.K_ESCAPE:
>>>>>>> Stashed changes
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
    start_game()

if __name__ == "__main__":
    main()
