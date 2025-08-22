#!/usr/bin/env python3
from __future__ import annotations
import os, sys, json, re, argparse, random
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field

# ============================================================
#                       VALIDATION
# ============================================================

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

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

# Unified short prefixes
ID_RULES = {
    "item":    re.compile(r"^IT\d{8}$"),
    "npc":     re.compile(r"^NP\d{8}$"),
    "enchant": re.compile(r"^EN\d{8}$"),
    "trait":   re.compile(r"^TR\d{8}$"),
    "magic":   re.compile(r"^MG\d{8}$"),
    "status":  re.compile(r"^ST\d{8}$"),
}

def load_json(path: str, fallback=None):
    """BOM-tolerant JSON loader."""
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

def validate_project(root: str, strict: bool=False) -> Tuple[List[str], List[str], Dict[str, Any]]:
    errs: List[str] = []
    warns: List[str] = []
    ctx: Dict[str, Any] = {}

    def abspath(rel: str) -> str:
        return os.path.join(root, rel)

    # Existence
    missing = [rel for rel in (EXPECTED["root_files"] + EXPECTED["item_files"] + EXPECTED["npc_files"])
               if not os.path.exists(abspath(rel))]
    if missing:
        warns.append("[WARN] Missing files: " + ", ".join(missing))

    # Load root docs & header sanity
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

    # Items
    item_index: Dict[str, dict] = {}
    dup_items: List[str] = []
    for rel in EXPECTED["item_files"]:
        try:
            doc = load_json(abspath(rel), {"items": []})
        except Exception as e:
            warns.append(f"[WARN] {rel}: {e}")
            doc = {"items": []}
        for it in doc.get("items", []):
            if not isinstance(it, dict): 
                continue
            iid = it.get("id")
            if not validate_id(iid, "item"):
                errs.append(f"[ERR] {rel} item id '{iid}' must match IT########")
            if iid in item_index:
                dup_items.append(iid)
            item_index[iid] = it

    # NPCs
    npc_index: Dict[str, dict] = {}
    dup_npcs: List[str] = []
    for rel in EXPECTED["npc_files"]:
        try:
            doc = load_json(abspath(rel), {"npcs": []})
        except Exception as e:
            warns.append(f"[WARN] {rel}: {e}")
            doc = {"npcs": []}
        for npc in doc.get("npcs", []):
            if not isinstance(npc, dict): 
                continue
            nid = npc.get("id")
            if not validate_id(nid, "npc"):
                errs.append(f"[ERR] {rel} npc id '{nid}' must match NP########")
            if nid in npc_index:
                dup_npcs.append(nid)
            npc_index[nid] = npc

    # Enchants / Traits / Magic / Status ID checks
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

    # Loot table references (lightweight)
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
                errs.append(f"[ERR] loot table '{tname}' should be a list"); 
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

    # Dialogues presence
    dlg_dir = abspath(EXPECTED["dialogues_dir"])
    dlg_count = 0
    if os.path.isdir(dlg_dir):
        for fn in os.listdir(dlg_dir):
            if fn.lower().endswith(".json"):
                dlg_count += 1
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

    ctx["items"] = list(item_index.values())
    ctx["npcs"]  = list(npc_index.values())
    return errs, warns, ctx

# ============================================================
#                       GAME (Pygame)
# ============================================================

# UI constants
WIN_W, WIN_H = 980, 640
GRID_W, GRID_H = 12, 8
TILE = 44
PANEL_W = 360
FPS = 60
FONT_NAME = None  # default pygame font

def safe_load_doc(rel: str, array_key: str) -> List[dict]:
    doc = load_json(os.path.join(DATA_DIR, rel), {array_key: []})
    return [x for x in doc.get(array_key, []) if isinstance(x, dict)]

def gather_items() -> List[Dict]:
    items: List[Dict] = []
    items_dir = os.path.join(DATA_DIR, "items")
    if os.path.isdir(items_dir):
        for name in ["weapons.json","armours.json","accessories.json","clothing.json","materials.json","quest_items.json","trinkets.json"]:
            for it in safe_load_doc(os.path.join("items", name), "items"):
                items.append(it)
    if not items:
        items = [
            {"id":"IT00000001","name":"Rust-Kissed Dagger","type":"weapon","rarity":"common","desc":"A pitted blade that still finds gaps in armor."},
            {"id":"IT00000002","name":"Traveler’s Cloak","type":"clothing","rarity":"common","desc":"Smells like rain and road dust."},
            {"id":"IT00000003","name":"Moonfern","type":"material","rarity":"uncommon","desc":"Glows faintly in the dark."},
        ]
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
            {"id":"NP00000001","name":"Lissar of the Birch","kind":"elf","romanceable":True,
             "desc":"An elf archer with bright eyes and a sly smile.","dialogue":[
              {"text":"The woods whisper of you. Will you listen?","options":[
                {"label":"Listen","effect":"affinity+1"},
                {"label":"Flirt","effect":"romance_attempt"}
              ]} ]},
            {"id":"NP00000002","name":"Grukk","kind":"beast","hostile":True,
             "desc":"A hulking brute whose breath smells like old stew."}
        ]
    return npcs

def load_traits() -> List[Dict]:   return safe_load_doc("traits.json", "traits")
def load_enchants() -> List[Dict]: return safe_load_doc("enchants.json", "enchants")
def load_magic() -> List[Dict]:    return safe_load_doc("magic.json", "spells")
def load_status() -> List[Dict]:   return safe_load_doc("status.json", "status")
def load_names() -> Dict:          return load_json(os.path.join(DATA_DIR, "names.json"), {})

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

@dataclass
class Player:
    x: int = 0
    y: int = 0
    hp: int = 20
    max_hp: int = 20
    atk: Tuple[int,int] = (3,6)
    stealth: int = 4
    affinity: Dict[str,int] = field(default_factory=dict)
    romance_flags: Dict[str,bool] = field(default_factory=dict)
    inventory: List[Dict] = field(default_factory=list)

def pick_enemy(npcs: List[Dict]) -> Optional[Dict]:
    hostile = [n for n in npcs if n.get("hostile")]
    return random.choice(hostile) if hostile else None

def pick_npc(npcs: List[Dict]) -> Optional[Dict]:
    friendly = [n for n in npcs if not n.get("hostile")]
    return random.choice(friendly) if friendly else None

def pick_item(items: List[Dict]) -> Optional[Dict]:
    return random.choice(items) if random.random() < 0.5 else None

def generate_world(items, npcs) -> List[List[Tile]]:
    grid: List[List[Tile]] = []
    for y in range(8):
        row = []
        for x in range(12):
            t = Tile(x=x, y=y)
            t.description = random.choice([
                "Wind-swept brush and bent reeds.",
                "Ancient stones half-swallowed by moss.",
                "A hush falls here, like a held breath.",
                "Dappled light flickers between tall birches.",
                "A trampled path suggests recent travelers."
            ])
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
    return grid

# ---------------- Pygame UI ----------------
def start_game():
    try:
        import pygame
    except ImportError:
        print("[ERR] pygame not installed. Run: pip install pygame")
        sys.exit(1)

    WIN_W, WIN_H = 980, 640
    GRID_W, GRID_H = 12, 8
    TILE = 44
    PANEL_W = 360
    FPS = 60
    FONT_NAME = None

    pygame.init()
    pygame.display.set_caption("RPGenesis – Text RPG")
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    clock = pygame.time.Clock()
    FONT = pygame.font.Font(FONT_NAME, 18)
    FONT_SMALL = pygame.font.Font(FONT_NAME, 14)
    FONT_BIG = pygame.font.Font(FONT_NAME, 22)

    def draw_text(surface, text, pos, color=(230,230,230), font=FONT, max_w=None):
        if not max_w:
            surface.blit(font.render(text, True, color), pos); return
        words = text.split(" "); x,y = pos; line = ""
        for w in words:
            test = (line + " " + w).strip()
            if font.size(test)[0] <= max_w: line = test
            else:
                surface.blit(font.render(line, True, color), (x,y)); y += font.get_linesize(); line = w
        if line: surface.blit(font.render(line, True, color), (x,y))

    class Button:
        def __init__(self, rect, label, cb):
            self.rect = pygame.Rect(rect); self.label = label; self.cb = cb
        def draw(self, surf):
            pygame.draw.rect(surf, (60,60,70), self.rect, border_radius=8)
            pygame.draw.rect(surf, (110,110,130), self.rect, 2, border_radius=8)
            label = FONT.render(self.label, True, (240,240,255))
            surf.blit(label, (self.rect.x + 10, self.rect.y + (self.rect.h - label.get_height())//2))
        def handle(self, event):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
                self.cb()

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
            self.mode = "explore"  # explore | dialogue | combat | event
            self.current_enemy_hp = 0
            self.current_enemy = None
            self.current_npc = None

        def tile(self, x=None, y=None) -> Tile:
            if x is None: x = self.player.x
            if y is None: y = self.player.y
            return self.grid[y][x]

        def say(self, msg: str):
            self.log.append(msg)
            if len(self.log) > 8: self.log = self.log[-8:]

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
            if 0 <= nx < GRID_W and 0 <= ny < GRID_H:
                self.player.x, self.player.y = nx, ny
                t = self.tile(); t.discovered = True; t.visited += 1
                if t.encounter:
                    if t.encounter.enemy:
                        self.mode = "combat" if t.encounter.spotted else "explore"
                        if t.encounter.spotted:
                            self.start_combat(t.encounter.enemy); self.say(f"{t.encounter.enemy.get('name','A foe')} spots you!")
                        else: self.say("An enemy lurks here... maybe you could sneak by.")
                    elif t.encounter.npc:
                        self.mode = "dialogue"; self.start_dialogue(t.encounter.npc); self.say(f"You meet {t.encounter.npc.get('name','someone')}.")
                    elif t.encounter.event:
                        self.mode = "event"; self.say(f"You encounter {t.encounter.event}.")
                else: self.mode = "explore"

        # Dialogue / Romance
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
                    if random.random() < chance:
                        self.player.romance_flags[nid] = True
                        self.say(f"{npc.get('name','They')} returns your smile. (Romance blossoming)")
                    else: self.say("Not quite the moment. Maybe build more rapport.")
                else: self.say("They seem unreceptive to flirtation.")
            elif choice == "Leave":
                t = self.tile(); t.encounter.npc = None; t.encounter.must_resolve = False
                self.current_npc = None; self.mode = "explore"
            else:
                self.say("You share a few words.")

        # Combat
        def start_combat(self, enemy):
            self.current_enemy = enemy; self.current_enemy_hp = enemy.get("hp", 12)
        def attack(self):
            if not self.current_enemy: return
            dmg = random.randint(3,6); self.current_enemy_hp -= dmg; self.say(f"You strike for {dmg}.")
            if self.current_enemy_hp <= 0:
                self.say("Enemy defeated!")
                t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
                self.current_enemy = None; self.mode = "explore"
            else: self.enemy_turn()
        def cast_spell(self):
            if not self.current_enemy: self.say("No target."); return
            if not self.magic: self.say("You don't recall any spells."); return
            spell = random.choice(self.magic); dmg = random.randint(4,8)
            self.current_enemy_hp -= dmg; self.say(f"You cast {spell.get('name','a spell')} for {dmg}!")
            if self.current_enemy_hp <= 0:
                self.say("Enemy crumples.")
                t = self.tile(); t.encounter.enemy = None; t.encounter.must_resolve = False
                self.current_enemy = None; self.mode = "explore"
            else: self.enemy_turn()
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
            else: self.say("Too risky to bypass.")
        def enemy_turn(self):
            if not self.current_enemy: return
            dmg = random.randint(2,5); self.player.hp -= dmg; self.say(f"The enemy hits you for {dmg}.")
            if self.player.hp <= 0:
                self.say("You fall... but awaken at the trailhead, aching.")
                self.player.hp = self.player.max_hp; self.player.x = 0; self.player.y = 0; self.mode = "explore"

        # Search / Loot
        def search_tile(self):
            t = self.tile()
            if not t.encounter: self.say("You find little of note."); return
            if t.encounter.item_searched: self.say("You've already scoured this area."); return
            t.encounter.item_searched = True
            if t.encounter.item_here:
                item = t.encounter.item_here; self.player.inventory.append(item)
                self.say(f"You found: {item.get('name','something')}!"); t.encounter.item_here = None
            else: self.say("You search thoroughly, but find nothing this time.")

    def draw_grid(surf, game: Game):
        pygame.draw.rect(surf, (26,26,32), (0,0, WIN_W - PANEL_W, WIN_H))
        for y in range(GRID_H):
            for x in range(GRID_W):
                rx, ry = x*TILE + 12, y*TILE + 12
                r = pygame.Rect(rx, ry, TILE-4, TILE-4)
                tile = game.grid[y][x]
                base = (42,44,56) if tile.discovered else (28,30,38)
                pygame.draw.rect(surf, base, r, border_radius=6)
                pygame.draw.rect(surf, (70,74,92), r, 1, border_radius=6)
                if tile.encounter:
                    if tile.encounter.enemy: pygame.draw.circle(surf, (190,70,70), (r.centerx, r.centery), 4)
                    elif tile.encounter.npc: pygame.draw.circle(surf, (90,170,110), (r.centerx, r.centery), 4)
                    elif tile.encounter.event: pygame.draw.circle(surf, (160,130,200), (r.centerx, r.centery), 4)
        px = game.player.x*TILE + 12 + (TILE-4)//2
        py = game.player.y*TILE + 12 + (TILE-4)//2
        pygame.draw.circle(surf, (235,235,80), (px,py), 7)

    def draw_panel(surf, game: Game, buttons: List[Button]):
        x0 = WIN_W - PANEL_W
        pygame.draw.rect(surf, (18,18,24), (x0,0, PANEL_W, WIN_H))
        pygame.draw.rect(surf, (70,74,92), (x0,0, PANEL_W, WIN_H), 1)

        draw_text(surf, "RPGenesis – Field Log", (x0+16, 12), font=pygame.font.Font(FONT_NAME, 22))
        t = game.tile(); y = 48
        draw_text(surf, f"Tile ({t.x},{t.y})", (x0+16, y)); y += 20
        draw_text(surf, t.description, (x0+16, y), max_w=PANEL_W-32); y += 50

        if t.encounter:
            if t.encounter.enemy:
                s = t.encounter.enemy.get("name","Enemy"); spotted = " (alerted)" if t.encounter.spotted else " (unaware)"
                draw_text(surf, f"Enemy: {s}{spotted}", (x0+16, y)); y += 22
            if t.encounter.npc:
                draw_text(surf, f"NPC: {t.encounter.npc.get('name','Stranger')}", (x0+16, y)); y += 22
            if t.encounter.event:
                draw_text(surf, f"Event: {t.encounter.event}", (x0+16, y)); y += 22
            if not t.encounter.item_searched:
                draw_text(surf, "Area can be searched.", (x0+16, y), (200,200,240)); y += 20
            else:
                draw_text(surf, "Area already searched.", (x0+16, y), (160,160,180)); y += 20

        y += 6
        draw_text(surf, f"HP: {game.player.hp}/{game.player.max_hp}", (x0+16, y)); y += 20
        draw_text(surf, f"Inventory: {len(game.player.inventory)}", (x0+16, y)); y += 26
        draw_text(surf, "Recent:", (x0+16, y)); y += 18
        for line in game.log[-6:]:
            draw_text(surf, f"• {line}", (x0+20, y), max_w=PANEL_W-36); y += 18

        for b in buttons: b.draw(surf)

    def build_buttons(game: Game) -> List[Button]:
        x0 = WIN_W - PANEL_W + 16; y0 = WIN_H - 200
        btns: List[Button] = []
        def add(label, cb):
            nonlocal y0
            btns.append(Button((x0, y0, PANEL_W-32, 34), label, cb)); y0 += 38
        t = game.tile()
        if game.mode == "combat":
            add("Attack", game.attack); add("Cast Spell", game.cast_spell)
        elif game.mode == "dialogue":
            add("Talk", lambda: game.handle_dialogue_choice("Talk"))
            add("Flirt", lambda: game.handle_dialogue_choice("Flirt"))
            add("Leave", lambda: game.handle_dialogue_choice("Leave"))
        else:
            add("Search Area", game.search_tile)
            if t.encounter and t.encounter.enemy and not t.encounter.spotted:
                add("Sneak Past", game.try_sneak); add("Bypass (Skirt Around)", game.bypass_enemy)
            if t.encounter and t.encounter.enemy and t.encounter.spotted:
                add("Fight", lambda: game.start_combat(t.encounter.enemy))
            if t.encounter and t.encounter.npc:
                add("Talk", lambda: game.start_dialogue(t.encounter.npc))
                add("Leave NPC", lambda: game.handle_dialogue_choice("Leave"))
        return btns

    # --- Main loop ---
    game = Game()
    running = True
    while running:
        dt = clock.tick(FPS)
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: running = False
                elif event.key in (pygame.K_w, pygame.K_UP):    game.move(0,-1)
                elif event.key in (pygame.K_s, pygame.K_DOWN):  game.move(0,1)
                elif event.key in (pygame.K_a, pygame.K_LEFT):  game.move(-1,0)
                elif event.key in (pygame.K_d, pygame.K_RIGHT): game.move(1,0)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                for b in build_buttons(game): b.handle(event)

        screen.fill((16,16,22))
        draw_grid(screen, game)
        buttons = build_buttons(game)
        draw_panel(screen, game, buttons)
        pygame.display.flip()

    pygame.quit()

# ============================================================
#                       ENTRYPOINT
# ============================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description="RPGenesis – validate then launch game UI")
    ap.add_argument("--root", default=".", help="Project root")
    ap.add_argument("--validate-only", action="store_true", help="Run validation only, do not start UI")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as fatal")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    errs, warns, _ctx = validate_project(root, strict=args.strict)

    # If validate-only, exit with status
    if args.validate_only:
        sys.exit(1 if errs or (args.strict and warns) else 0)

    # If errors (or strict+warnings), stop before launching UI
    if errs or (args.strict and warns):
        print("\n[ABORT] Fix the issues above to launch the game (use --strict to elevate warnings).")
        sys.exit(1)

    print("\n[OK] Validation passed. Launching game...")
    start_game()

if __name__ == "__main__":
    main()
