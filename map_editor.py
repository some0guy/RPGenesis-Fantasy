#!/usr/bin/env python3
# RPGenesis Map Editor — Real Maps + Chips + Filters + UNDO/REDO
# - Full undo/redo stack (Ctrl+Z / Ctrl+Y or Ctrl+Shift+Z; buttons too)
# - History capped to 150 snapshots, stored as deep copies of the scene
# - Commit points after every mutating action (add/remove/clear/toggle/link ops, load/new)
# - All prior features kept: multiple per tile, z-order dropdowns, discovery, map picker, chips, filters

import pygame as pg
import json, os, re
from pathlib import Path
from typing import List, Dict, Any, Tuple

WIN_W, WIN_H = 1340, 940
PANEL_W = 600
GRID_MARGIN = 16
BG = (24,25,28); FG = (230,230,230); ACCENT = (160,200,255); MUTED = (140,140,150); HL = (70,120,200)

DATA_DIR = Path("data")
MAP_DIR = DATA_DIR / "maps"
MAP_DIR.mkdir(parents=True, exist_ok=True)

# ---------- utility ----------
def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def as_list(obj: Any):
    if obj is None: return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for k in ["npcs","enemies","items","characters","actors","list","data","entries","creatures","monsters"]:
            if k in obj and isinstance(obj[k], list):
                return [x for x in obj[k] if isinstance(x, dict)]
        out = []
        for k,v in obj.items():
            if isinstance(v, dict):
                vv = dict(v); vv.setdefault("id", k); out.append(vv)
        return out
    return []

def slugify(s: str) -> str:
    s = str(s).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"

def filename_hints_enemy(name: str) -> bool:
    name = name.lower()
    return any(k in name for k in ["enemy","enemies","monster","monsters","bestiary","creature","creatures","foe","foes","hostile","hostiles"])

def record_is_enemy(rec: Dict[str, Any]) -> bool:
    if rec.get("hostile") is True: return True
    fac = str(rec.get("faction","")).lower()
    if fac in ("hostile","enemy","monsters","creatures"): return True
    typ = str(rec.get("type","")).lower()
    cat = str(rec.get("category","")).lower()
    if typ in ("enemy","monster","creature") or cat in ("enemy","monster","creature"): return True
    tags = rec.get("tags") or rec.get("keywords") or []
    if isinstance(tags, str): tags = [t.strip().lower() for t in tags.split(",")]
    if isinstance(tags, list) and any(t.lower() in ("enemy","monster","creature","hostile","foe") for t in tags):
        return True
    return False

def discover_catalogs() -> Tuple[List[Dict], List[Dict], List[Dict], List[str]]:
    npcs: List[Dict] = []; enemies: List[Dict] = []; items: List[Dict] = []
    link_targets: List[str] = []

    # Candidate single files (top-level data/)
    single_candidates = [
        ("npcs.json","npc"), ("enemies.json","enemy"), ("items.json","item"),
        ("characters.json","split"), ("actors.json","split"),
        ("monsters.json","enemy"), ("bestiary.json","enemy"), ("creatures.json","enemy"), ("foes.json","enemy"),
    ]
    for fname, mode in single_candidates:
        p = DATA_DIR / fname
        if not p.exists(): continue
        arr = as_list(read_json(p))
        if mode == "npc": npcs.extend(arr)
        elif mode == "item": items.extend(arr)
        elif mode == "enemy": enemies.extend(arr)
        elif mode == "split":
            for e in arr: (enemies if record_is_enemy(e) else npcs).append(e)

    # Folders under data/ (with filename-based classification inside each folder)
    folder_candidates = [
        "npcs","enemies","items","characters","actors",
        "monsters","bestiary","creatures","foes","hostiles"
    ]
    for folder in folder_candidates:
        base = DATA_DIR / folder
        if not base.exists(): continue
        for path in base.glob("*.json"):
            arr = as_list(read_json(path))
            fname = path.name.lower()
            if folder == "items":
                items.extend(arr); continue
            if folder in ("enemies","monsters","bestiary","creatures","foes","hostiles") or filename_hints_enemy(fname):
                enemies.extend(arr); continue
            if folder in ("characters","actors"):
                for e in arr: (enemies if record_is_enemy(e) else npcs).append(e)
                continue
            npcs.extend(arr)

    def norm(lst: List[Dict]):
        out = []
        for e in lst:
            name = e.get("name") or e.get("title") or e.get("id") or "Unknown"
            _id = e.get("id") or slugify(name)
            out.append({"id": str(_id), "name": str(name), **e})
        return out
    def dedup(lst: List[Dict]):
        seen = set(); out = []
        for e in lst:
            if e["id"] in seen: continue
            seen.add(e["id"]); out.append(e)
        return out

    npcs = dedup(norm(npcs))
    enemies = dedup(norm(enemies))
    items = dedup(norm(items))

    # link targets from data/maps/*.json
    for p in MAP_DIR.glob("*.json"):
        link_targets.append(p.stem)

    return npcs, enemies, items, sorted(set(link_targets))

# ---------- UI widgets ----------
class Button:
    def __init__(self, rect, text, cb):
        self.rect = pg.Rect(rect); self.text = text; self.cb = cb; self.enabled = True
    def draw(self, surf, font):
        pg.draw.rect(surf, HL if self.enabled else MUTED, self.rect, width=2, border_radius=6)
        label = font.render(self.text, True, FG if self.enabled else MUTED)
        surf.blit(label, label.get_rect(center=self.rect.center))
    def handle(self, ev):
        if not self.enabled: return False
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1 and self.rect.collidepoint(ev.pos):
            self.cb(); return True
        return False

class DropDown:
    def __init__(self, rect, placeholder, options, on_change=None):
        self.rect = pg.Rect(rect); self.placeholder = placeholder; self.options = list(options)
        self.on_change = on_change
        self.open = False; self.sel_index = -1; self.scroll = 0
        self.item_h = 26; self.max_show = 14
    @property
    def value(self):
        if 0 <= self.sel_index < len(self.options): return self.options[self.sel_index][0]
        return ""
    def set_options(self, options):
        self.options = list(options); self.sel_index = -1; self.scroll = 0
    def select_value(self, val: str):
        for i,(v,_) in enumerate(self.options):
            if v == val: self.sel_index = i; return
    def draw_base(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        text = self.placeholder if self.sel_index<0 else self.options[self.sel_index][1]
        surf.blit(font.render(text, True, FG), (self.rect.x+8, self.rect.y+5))
    def draw_popup(self, surf, font):
        if not self.open: return
        h = self.item_h * min(self.max_show, len(self.options))
        list_rect = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, h)
        pg.draw.rect(surf, (40,42,46), list_rect, border_radius=6)
        pg.draw.rect(surf, HL, list_rect, width=2, border_radius=6)
        start = self.scroll; end = min(len(self.options), start + self.max_show)
        mx,my = pg.mouse.get_pos()
        for idx, opt_i in enumerate(range(start, end)):
            r = pg.Rect(list_rect.x, list_rect.y + idx*self.item_h, list_rect.w, self.item_h)
            if r.collidepoint((mx,my)): pg.draw.rect(surf, (55,57,61), r)
            label = self.options[opt_i][1]
            surf.blit(pg.font.SysFont(None, 18).render(label, True, FG), (r.x+8, r.y+4))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos):
                self.open = not self.open; return True
            if self.open:
                list_rect = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, self.item_h*min(self.max_show, len(self.options)))
                if list_rect.collidepoint(ev.pos):
                    rel_y = ev.pos[1] - list_rect.y; idx = rel_y // self.item_h
                    opt_i = self.scroll + int(idx)
                    if 0 <= opt_i < len(self.options):
                        self.sel_index = opt_i; self.open = False
                        if self.on_change: self.on_change(self.options[opt_i][0])
                    return True
                else:
                    self.open = False
        elif ev.type == pg.MOUSEWHEEL and self.open:
            self.scroll = max(0, min(max(0, len(self.options)-self.max_show), self.scroll - ev.y)); return True
        return False

class TextInput:
    def __init__(self, rect, placeholder=""):
        self.rect = pg.Rect(rect); self.text = ""; self.placeholder = placeholder; self.focus = False
    def draw(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        shown = self.text if self.text else self.placeholder
        color = FG if self.text else MUTED
        surf.blit(font.render(shown, True, color), (self.rect.x+8, self.rect.y+6))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            self.focus = self.rect.collidepoint(ev.pos); return self.focus
        if self.focus and ev.type == pg.KEYDOWN:
            if ev.key == pg.K_BACKSPACE: self.text = self.text[:-1]
            elif ev.key == pg.K_RETURN: self.focus = False
            else:
                if ev.unicode and ev.unicode.isprintable(): self.text += ev.unicode
            return True
        return False

# ---------- Editor ----------
class Editor:
    def __init__(self, w=40, h=24):
        self.grid_w = w; self.grid_h = h
        self.scene = {"name":"untitled","w":w,"h":h,"tiles":{}, "links":[]}
        self.sel = None; self.message = ""
        self.current_map: Path | None = None

        # History
        self.history: List[dict] = []
        self.redo_stack: List[dict] = []
        self.max_history = 150

        # Catalogs
        self.all_npcs, self.all_enemies, self.all_items, self.link_targets = discover_catalogs()
        # ID->name lookup
        self.npc_by_id = {e["id"]: e.get("name", e["id"]) for e in self.all_npcs}
        self.enemy_by_id = {e["id"]: e.get("name", e["id"]) for e in self.all_enemies}
        self.item_by_id = {e["id"]: e.get("name", e["id"]) for e in self.all_items}
        # Filtered views
        self.npcs = list(self.all_npcs); self.enemies = list(self.all_enemies); self.items = list(self.all_items)

        pg.init(); pg.display.set_caption("RPGenesis Editor — Chips + Filters + Undo/Redo")
        self.screen = pg.display.set_mode((WIN_W, WIN_H))
        self.font = pg.font.SysFont(None, 18); self.small = pg.font.SysFont(None, 14)

        self.grid_rect = pg.Rect(GRID_MARGIN, GRID_MARGIN, WIN_W-PANEL_W-2*GRID_MARGIN, WIN_H-2*GRID_MARGIN)
        self.tile_size = max(16, min(28, min(self.grid_rect.w//w, self.grid_rect.h//h)))

        rp_x = WIN_W-PANEL_W+16; y = 16

        # Map file dropdown
        map_list = sorted([p.name for p in MAP_DIR.glob("*.json")])
        self.dd_map = DropDown((rp_x, y, 360, 30), "Select map file", [(name, name) for name in map_list])
        self.btn_open = Button((rp_x+370, y, 80, 30), "Open", self.open_selected_map)
        self.btn_save = Button((rp_x+455, y, 80, 30), "Save", self.save_file); y += 38

        self.btn_save_as = Button((rp_x, y, 120, 30), "Save As...", self.save_as_dialog)
        self.btn_new_map = Button((rp_x+130, y, 140, 30), "New Map", self.new_scene)
        self.btn_reload = Button((rp_x+280, y, 140, 30), "Reload Catalogs", self.reload_catalogs); y += 42

        # Undo/Redo row
        self.btn_undo = Button((rp_x, y, 120, 30), "Undo (Ctrl+Z)", self.undo)
        self.btn_redo = Button((rp_x+130, y, 140, 30), "Redo (Ctrl+Y)", self.redo); y += 38

        # Filters + dropdowns (NPC)
        self.inp_filter_npc = TextInput((rp_x, y, 260, 26), "Filter NPCs (type...)"); y += 30
        self.dd_npc = DropDown((rp_x, y, 260, 30), "NPC", [(e["id"], e["name"]) for e in self.npcs] or [("", "(no NPCs)")], on_change=lambda _:(self.add_npc() if self.sel else None))
        self.btn_add_npc = Button((rp_x+270, y, 60,30), "Add", self.add_npc)
        self.btn_rem_npc = Button((rp_x+335, y, 75,30), "Remove", self.remove_npc)
        self.btn_clr_npc = Button((rp_x+415, y, 70,30), "Clear", self.clear_npcs); y += 38

        # Filters + dropdowns (Enemy)
        self.inp_filter_enemy = TextInput((rp_x, y, 260, 26), "Filter Enemies (type...)"); y += 30
        self.dd_enemy = DropDown((rp_x, y, 260, 30), "Enemy", [(e["id"], e["name"]) for e in self.enemies] or [("", "(no Enemies)")], on_change=lambda _:(self.add_enemy() if self.sel else None))
        self.btn_add_enemy = Button((rp_x+270, y, 60,30), "Add", self.add_enemy)
        self.btn_rem_enemy = Button((rp_x+335, y, 75,30), "Remove", self.remove_enemy)
        self.btn_clr_enemy = Button((rp_x+415, y, 70,30), "Clear", self.clear_enemies); y += 38

        # Filters + dropdowns (Item)
        self.inp_filter_item = TextInput((rp_x, y, 260, 26), "Filter Items (type...)"); y += 30
        self.dd_item = DropDown((rp_x, y, 260, 30), "Item", [(e["id"], e["name"]) for e in self.items] or [("", "(no Items)")], on_change=lambda _:(self.add_item() if self.sel else None))
        self.btn_add_item = Button((rp_x+270, y, 60,30), "Add", self.add_item)
        self.btn_rem_item = Button((rp_x+335, y, 75,30), "Remove", self.remove_item)
        self.btn_clr_item = Button((rp_x+415, y, 70,30), "Clear", self.clear_items); y += 38

        self.inp_entry = TextInput((rp_x, y, 260, 30), "Entry name (e.g., east_gate)")
        self.btn_toggle_entry = Button((rp_x+270, y, 215,30), "Toggle Entry", self.toggle_entry); y += 38

        self.dd_link = DropDown((rp_x, y, 260, 30), "Link target", [("map:"+n, "Map→"+n) for n in self.link_targets] or [("", "(no maps)")], on_change=lambda _:(self.set_link() if self.sel else None))
        self.btn_set_link = Button((rp_x+270, y, 100,30), "Set Link", self.set_link)
        self.btn_clr_link = Button((rp_x+375, y, 110,30), "Clear Link", self.clear_link); y += 38

        self.inp_target_entry = TextInput((rp_x, y, 260, 30), "Target entry (optional)"); y += 38

        self.message = ""
        self.click_chips: List[Tuple[pg.Rect, str, str]] = []  # (rect, kind, id) for clickable 'x'
        self._last_filters = {"npc":"","enemy":"","item":""}

        # Start history with initial snapshot
        self._reset_history()

    # ---------- history ----------
    def _snapshot_scene(self) -> dict:
        # Deep copy via JSON cycle (scene is JSON-safe)
        return json.loads(json.dumps(self.scene))
    def _reset_history(self):
        self.history = [self._snapshot_scene()]
        self.redo_stack = []
    def _commit(self, msg: str | None = None):
        snap = self._snapshot_scene()
        # Avoid duplicate snapshot if same as last
        if json.dumps(snap, sort_keys=True) != json.dumps(self.history[-1], sort_keys=True):
            self.history.append(snap)
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
            self.redo_stack.clear()
        if msg: self.message = msg
    def undo(self):
        if len(self.history) >= 2:
            last = self.history.pop()
            self.redo_stack.append(last)
            self.scene = self._snapshot_scene() if not self.history else json.loads(json.dumps(self.history[-1]))
            self.message = "Undo"
    def redo(self):
        if self.redo_stack:
            snap = self.redo_stack.pop()
            self.history.append(snap)
            self.scene = json.loads(json.dumps(snap))
            self.message = "Redo"

    # ---------- filtering ----------
    def update_filtered_options(self):
        fn = self.inp_filter_npc.text.strip().lower()
        fe = self.inp_filter_enemy.text.strip().lower()
        fi = self.inp_filter_item.text.strip().lower()

        if fn != self._last_filters["npc"]:
            if fn:
                self.npcs = [e for e in self.all_npcs if fn in e["name"].lower() or fn in e["id"].lower()]
            else:
                self.npcs = list(self.all_npcs)
            self.dd_npc.set_options([(e["id"], e["name"]) for e in self.npcs] or [("", "(no NPCs)")])
            self._last_filters["npc"] = fn

        if fe != self._last_filters["enemy"]:
            if fe:
                self.enemies = [e for e in self.all_enemies if fe in e["name"].lower() or fe in e["id"].lower()]
            else:
                self.enemies = list(self.all_enemies)
            self.dd_enemy.set_options([(e["id"], e["name"]) for e in self.enemies] or [("", "(no Enemies)")])
            self._last_filters["enemy"] = fe

        if fi != self._last_filters["item"]:
            if fi:
                self.items = [e for e in self.all_items if fi in e["name"].lower() or fi in e["id"].lower()]
            else:
                self.items = list(self.all_items)
            self.dd_item.set_options([(e["id"], e["name"]) for e in self.items] or [("", "(no Items)")])
            self._last_filters["item"] = fi

    # ---------- file ops ----------
    def open_selected_map(self):
        name = self.dd_map.value
        if not name: 
            self.message = "Select a map file first."; return
        path = MAP_DIR / name
        data = read_json(path)
        if not isinstance(data, dict):
            self.message = f"Failed to load {name}"; return
        self.scene = data
        self.current_map = path
        self._reset_history()
        self.message = f"Opened {name}"

    def save_file(self):
        if not self.current_map:
            self.message = "No current map. Use Save As..."; return
        write_json(self.current_map, self.scene)
        self.message = f"Saved {self.current_map.name}"

    def save_as_dialog(self):
        name_hint = self.inp_target_entry.text.strip()
        if not name_hint:
            self.message = "Type a filename in 'Target entry', then click Save As... again."
            return
        safe = slugify(name_hint)
        path = MAP_DIR / f"{safe}.json"
        write_json(path, self.scene)
        self.current_map = path
        names = sorted([p.name for p in MAP_DIR.glob("*.json")])
        self.dd_map.set_options([(n, n) for n in names])
        self.dd_map.select_value(path.name)
        self.message = f"Saved As {path.name}"

    def new_scene(self):
        self.scene = {"name":"untitled","w":self.grid_w,"h":self.grid_h,"tiles":{},"links":[]}
        self.sel = None
        self.current_map = None
        self._reset_history()
        self.message = "New map created (unsaved)"

    def reload_catalogs(self):
        self.all_npcs, self.all_enemies, self.all_items, self.link_targets = discover_catalogs()
        self.npc_by_id = {e["id"]: e.get("name", e["id"]) for e in self.all_npcs}
        self.enemy_by_id = {e["id"]: e.get("name", e["id"]) for e in self.all_enemies}
        self.item_by_id = {e["id"]: e.get("name", e["id"]) for e in self.all_items}
        # reset filters & lists
        self.inp_filter_npc.text = ""; self.inp_filter_enemy.text = ""; self.inp_filter_item.text = ""
        self._last_filters = {"npc":"","enemy":"","item":""}
        self.npcs = list(self.all_npcs); self.enemies = list(self.all_enemies); self.items = list(self.all_items)
        self.dd_npc.set_options([(e["id"], e["name"]) for e in self.npcs] or [("", "(no NPCs)")])
        self.dd_enemy.set_options([(e["id"], e["name"]) for e in self.enemies] or [("", "(no Enemies)")])
        self.dd_item.set_options([(e["id"], e["name"]) for e in self.items] or [("", "(no Items)")])
        # refresh map list & link options
        names = sorted([p.name for p in MAP_DIR.glob("*.json")])
        self.dd_map.set_options([(n, n) for n in names])
        self.dd_link.set_options([("map:"+n, "Map→"+n) for n in self.link_targets] or [("", "(no maps)")])
        self.message = "Catalogs + maps reloaded"

    # ---------- tile helpers & migration ----------
    def _key(self, x, y): return f"{x},{y}"
    def _td(self, x, y):
        td = self.scene.setdefault("tiles", {}).setdefault(self._key(x,y), {})
        if "npc" in td and "npcs" not in td: td["npcs"] = [td.pop("npc")]
        if "enemy" in td and "enemies" not in td: td["enemies"] = [td.pop("enemy")]
        if "item" in td and "items" not in td: td["items"] = [td.pop("item")]
        td.setdefault("npcs", []); td.setdefault("enemies", []); td.setdefault("items", [])
        return td

    # ---------- add/remove/clear (with commits) ----------
    def add_npc(self):
        if not self.sel: return
        v = self.dd_npc.value; 
        if not v: return
        td = self._td(*self.sel)
        before = list(td["npcs"])
        if v not in td["npcs"]: td["npcs"].append(v)
        if td["npcs"] != before: self._commit(f"Added NPC:{v}")
    def remove_npc(self, val=None):
        if not self.sel: return
        v = val or self.dd_npc.value; td = self._td(*self.sel)
        before = list(td["npcs"])
        if v in td["npcs"]: td["npcs"].remove(v)
        if td["npcs"] != before: self._commit(f"Removed NPC:{v}")
    def clear_npcs(self):
        if not self.sel: return
        td = self._td(*self.sel); 
        if td["npcs"]:
            td["npcs"].clear(); self._commit("Cleared NPCs")

    def add_enemy(self):
        if not self.sel: return
        v = self.dd_enemy.value; 
        if not v: return
        td = self._td(*self.sel)
        before = list(td["enemies"])
        if v not in td["enemies"]: td["enemies"].append(v)
        if td["enemies"] != before: self._commit(f"Added Enemy:{v}")
    def remove_enemy(self, val=None):
        if not self.sel: return
        v = val or self.dd_enemy.value; td = self._td(*self.sel)
        before = list(td["enemies"])
        if v in td["enemies"]: td["enemies"].remove(v)
        if td["enemies"] != before: self._commit(f"Removed Enemy:{v}")
    def clear_enemies(self):
        if not self.sel: return
        td = self._td(*self.sel); 
        if td["enemies"]:
            td["enemies"].clear(); self._commit("Cleared Enemies")

    def add_item(self):
        if not self.sel: return
        v = self.dd_item.value; 
        if not v: return
        td = self._td(*self.sel)
        before = list(td["items"])
        if v not in td["items"]: td["items"].append(v)
        if td["items"] != before: self._commit(f"Added Item:{v}")
    def remove_item(self, val=None):
        if not self.sel: return
        v = val or self.dd_item.value; td = self._td(*self.sel)
        before = list(td["items"])
        if v in td["items"]: td["items"].remove(v)
        if td["items"] != before: self._commit(f"Removed Item:{v}")
    def clear_items(self):
        if not self.sel: return
        td = self._td(*self.sel); 
        if td["items"]:
            td["items"].clear(); self._commit("Cleared Items")

    # ---------- entry & links (with commits) ----------
    def toggle_entry(self):
        if not self.sel: return
        name = self.inp_entry.text.strip()
        td = self._td(*self.sel)
        before = td.get("entry")
        if "entry" in td:
            td.pop("entry", None); self._commit("Removed Entry")
        else:
            if name: td["entry"] = name; 
            self._commit(f"Set Entry:{name}" if name else "No entry name")
    def set_link(self):
        if not self.sel: return
        val = self.dd_link.value
        if not val or ":" not in val: return
        kind, name = val.split(":",1)
        x,y = self.sel
        before = json.dumps(self.scene.get("links", []), sort_keys=True)
        self.scene["links"] = [ln for ln in self.scene.get("links", []) if ln.get("at") != [x,y]]
        L = {"at":[x,y], "to":name, "kind":kind}
        te = self.inp_target_entry.text.strip()
        if te: L["target_entry"] = te
        self.scene.setdefault("links", []).append(L)
        after = json.dumps(self.scene.get("links", []), sort_keys=True)
        if after != before: self._commit(f"Set Link {kind}:{name}")
    def clear_link(self):
        if not self.sel: return
        x,y = self.sel
        before = json.dumps(self.scene.get("links", []), sort_keys=True)
        self.scene["links"] = [ln for ln in self.scene.get("links", []) if ln.get("at") != [x,y]]
        after = json.dumps(self.scene.get("links", []), sort_keys=True)
        if after != before: self._commit("Cleared Link")

    # ---------- chips drawing ----------
    def _draw_chips_row(self, surf, x0, y0, ids, kind):
        pad_x = 8; pad_y = 6
        cur_x = x0; cur_y = y0; max_w = PANEL_W - 32
        for _id in ids:
            name = (self.npc_by_id.get(_id) if kind=="npc" else
                    self.enemy_by_id.get(_id) if kind=="enemy" else
                    self.item_by_id.get(_id, _id))
            label = f"{name} ✖"
            rend = self.small.render(label, True, FG)
            w,h = rend.get_size()
            chip_w, chip_h = w+12, h+8
            if cur_x + chip_w > x0 + max_w:
                cur_x = x0; cur_y += chip_h + 6
            rect = pg.Rect(cur_x, cur_y, chip_w, chip_h)
            pg.draw.rect(surf, (45,47,52), rect, border_radius=10)
            pg.draw.rect(surf, HL, rect, width=1, border_radius=10)
            surf.blit(rend, (rect.x+6, rect.y+4))
            # Click target for the ✖ area (last ~16px)
            x_rect = pg.Rect(rect.right-18, rect.y+2, 16, max(16, h))
            self.click_chips.append((x_rect, kind, _id))
            cur_x += chip_w + 8
        return cur_y + 28  # new y after chips

    def _update_button_states(self):
        self.btn_undo.enabled = len(self.history) > 1
        self.btn_redo.enabled = len(self.redo_stack) > 0

    # ---------- draw ----------
    def draw(self):
        s = self.screen; s.fill(BG)
        self._update_button_states()
        # live filter update
        self.update_filtered_options()

        gx,gy,gw,gh = self.grid_rect; ts = self.tile_size
        for yy in range(self.scene.get("h", self.grid_h)):
            for xx in range(self.scene.get("w", self.grid_w)):
                r = pg.Rect(gx + xx*ts, gy + yy*ts, ts-1, ts-1)
                pg.draw.rect(s, (36,37,40), r)
        for key, td0 in self.scene.get("tiles", {}).items():
            xx,yy = map(int, key.split(","))
            td = self._td(xx,yy)
            r = pg.Rect(gx + xx*ts, gy + yy*ts, ts-1, ts-1)
            tags = []
            if td["npcs"]: tags.append(f"N{len(td['npcs']) if len(td['npcs'])>1 else ''}")
            if td["enemies"]: tags.append(f"X{len(td['enemies']) if len(td['enemies'])>1 else ''}")
            if td["items"]: tags.append(f"${len(td['items']) if len(td['items'])>1 else ''}")
            if "entry" in td: tags.append("E")
            s.blit(self.small.render(" ".join(tags), True, ACCENT), (r.x+3, r.y+2))
        for ln in self.scene.get("links", []):
            x,y = ln.get("at", [0,0])
            r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1)
            pg.draw.rect(s, (110,180,120), r, 2)
        if self.sel:
            x,y = self.sel
            r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1)
            pg.draw.rect(s, ACCENT, r, 3)

        # Panel
        rp = pg.Rect(WIN_W-PANEL_W, 0, PANEL_W, WIN_H)
        pg.draw.rect(s, (30,31,35), rp)

        # Base widgets (including filters & undo/redo)
        for w in [
            self.dd_map, self.btn_open, self.btn_save,
            self.btn_save_as, self.btn_new_map, self.btn_reload,
            self.btn_undo, self.btn_redo,
            self.inp_filter_npc, self.dd_npc, self.btn_add_npc, self.btn_rem_npc, self.btn_clr_npc,
            self.inp_filter_enemy, self.dd_enemy, self.btn_add_enemy, self.btn_rem_enemy, self.btn_clr_enemy,
            self.inp_filter_item, self.dd_item, self.btn_add_item, self.btn_rem_item, self.btn_clr_item,
            self.inp_entry, self.btn_toggle_entry,
            self.dd_link, self.btn_set_link, self.btn_clr_link,
            self.inp_target_entry
        ]:
            if isinstance(w, DropDown): w.draw_base(s, self.font)
            elif isinstance(w, TextInput): w.draw(s, self.font)
            else: w.draw(s, self.font)

        # Selected tile readout + chips
        self.click_chips.clear()
        x0 = WIN_W-PANEL_W+16; y0 = 580
        s.blit(self.font.render("Selected tile:", True, FG), (x0, y0))
        if self.sel:
            x,y = self.sel; td = self._td(x,y)
            link = None
            for ln in self.scene.get("links", []):
                if ln.get("at")==[x,y]: link = ln; break
            # Basic fields
            s.blit(self.small.render(f"({x},{y})", True, FG), (x0, y0+26))
            line_y = y0 + 50
            # chips sections
            s.blit(self.small.render("NPCs:", True, FG), (x0, line_y)); line_y += 20
            line_y = self._draw_chips_row(s, x0, line_y, td["npcs"], "npc")
            s.blit(self.small.render("Enemies:", True, FG), (x0, line_y)); line_y += 20
            line_y = self._draw_chips_row(s, x0, line_y, td["enemies"], "enemy")
            s.blit(self.small.render("Items:", True, FG), (x0, line_y)); line_y += 20
            line_y = self._draw_chips_row(s, x0, line_y, td["items"], "item")
            # entry + link
            line_y += 6
            s.blit(self.small.render(f"Entry: {td.get('entry','—')}", True, FG), (x0, line_y)); line_y += 20
            if link:
                link_text = f"{link['kind']}:{link['to']}"
                if link.get('target_entry'): link_text += f" @{link['target_entry']}"
            else:
                link_text = "—"
            s.blit(self.small.render(f"Link: {link_text}", True, FG), (x0, line_y))
        else:
            s.blit(self.small.render("(none) — click a tile", True, MUTED), (x0, y0+24))

        # Popups last (z-order)
        for dd in [self.dd_map, self.dd_npc, self.dd_enemy, self.dd_item, self.dd_link]:
            dd.draw_popup(s, self.font)

        # Status
        hist_txt = f"History: {len(self.history)} | Redo: {len(self.redo_stack)}"
        s.blit(self.small.render(hist_txt, True, MUTED), (16, WIN_H-48))
        if self.message:
            s.blit(self.small.render(self.message, True, ACCENT), (16, WIN_H-28))

        pg.display.flip()

    def handle(self, ev):
        # open dropdowns first
        for dd in [self.dd_map, self.dd_npc, self.dd_enemy, self.dd_item, self.dd_link]:
            if dd.open and dd.handle(ev): return

        # base widgets (including filters & undo/redo)
        consumed = False
        for w in [
            self.dd_map, self.btn_open, self.btn_save,
            self.btn_save_as, self.btn_new_map, self.btn_reload,
            self.btn_undo, self.btn_redo,
            self.inp_filter_npc, self.dd_npc, self.btn_add_npc, self.btn_rem_npc, self.btn_clr_npc,
            self.inp_filter_enemy, self.dd_enemy, self.btn_add_enemy, self.btn_rem_enemy, self.btn_clr_enemy,
            self.inp_filter_item, self.dd_item, self.btn_add_item, self.btn_rem_item, self.btn_clr_item,
            self.inp_entry, self.btn_toggle_entry,
            self.dd_link, self.btn_set_link, self.btn_clr_link,
            self.inp_target_entry
        ]:
            if hasattr(w, "handle") and w.handle(ev): consumed = True
        if consumed: return

        # chip clicks (remove specific id)
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, kind, _id in list(self.click_chips):
                if rect.collidepoint(ev.pos):
                    if not self.sel: return
                    if kind == "npc": self.remove_npc(_id)
                    elif kind == "enemy": self.remove_enemy(_id)
                    elif kind == "item": self.remove_item(_id)
                    return

        # grid select
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1 and self.grid_rect.collidepoint(ev.pos):
            gx,gy,gw,gh = self.grid_rect; ts = self.tile_size
            x = (ev.pos[0]-gx)//ts; y = (ev.pos[1]-gy)//ts
            if 0<=x<self.scene.get("w", self.grid_w) and 0<=y<self.scene.get("h", self.grid_h):
                self.sel = (int(x), int(y))

        # shortcuts
        if ev.type == pg.KEYDOWN and (pg.key.get_mods() & pg.KMOD_CTRL):
            if ev.key == pg.K_s:
                self.save_file()
            elif ev.key == pg.K_z and (pg.key.get_mods() & pg.KMOD_SHIFT):
                self.redo()
            elif ev.key == pg.K_z:
                self.undo()
            elif ev.key == pg.K_y:
                self.redo()

    def run(self):
        clock = pg.time.Clock(); running = True
        while running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT: running = False
                else: self.handle(ev)
            self.draw(); clock.tick(60)

if __name__ == "__main__":
    pg.init()
    Editor().run()
