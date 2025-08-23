#!/usr/bin/env python3
# RPGenesis-Fantasy Map/Dungeon Editor
# - Default map size 5x5
# - Right-panel resize controls (no hotkeys)
# - Undo button (history of last 50 edits)
# - Interaction model: click a tile first, then choose what to place from the right panel
# - Simple palette on the right: Terrain (., #, S, E), NPC, Enemy, Chest, Entrance/Exit
#
from __future__ import annotations
import os, sys, json, copy
from pathlib import Path
from typing import Dict, Tuple, List

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MAPS_DIR = DATA_DIR / "maps"
DUNGEONS_DIR = DATA_DIR / "dungeons"
WORLD_MAP = DATA_DIR / "world_map.txt"
OVERRIDES = DATA_DIR / "world_overrides.json"

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MAPS_DIR = DATA_DIR / "maps"
DUNGEONS_DIR = DATA_DIR / "dungeons"
WORLD_MAP = DATA_DIR / "world_map.txt"
OVERRIDES = DATA_DIR / "world_overrides.json"

EDITOR_VERSION = "map-editor 0.2.0"

print(f"[EDITOR] {EDITOR_VERSION}")
print(f"[EDITOR] CWD       = {os.getcwd()}")
print(f"[EDITOR] SCRIPT    = {__file__}")
print(f"[EDITOR] DATA_DIR  = {DATA_DIR}")
print(f"[EDITOR] WORLD_MAP = {WORLD_MAP}")
print(f"[EDITOR] OVERRIDES = {OVERRIDES}")

WIN_W, WIN_H = 1400, 860
PANEL_W = 520
CELL, GAP, PAD = 36, 5, 12

GRID_BG = (20,22,28)
PANEL_BG = (18,18,24)
PANEL_BORDER = (70,74,92)
COL_OPEN = (56,60,76)
COL_WALL = (28,30,40)
COL_START = (60,84,64)
COL_EXIT = (84,64,60)
COL_HOVER = (160,160,200)
COL_BORDER = (90,94,112)
COL_TEXT = (230,230,240)
COL_SUBTLE = (170,176,192)
COL_ACCENT = (200,200,80)
COL_BTN = (48,50,64)
COL_BTN_H = (64,66,86)

try:
    import pygame as pg
except ImportError:
    print("[ERR] pygame not installed. Try: pip install pygame")
    sys.exit(1)

def safe_load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return fallback
    except Exception as e:
        print(f"[WARN] Failed to load {path}: {e}")
        return fallback

def safe_write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

def safe_write_json(path: Path, obj):
    safe_write_text(path, json.dumps(obj, indent=2))

def gather_items() -> List[Dict]:
    items = []
    items_dir = DATA_DIR / "items"
    if items_dir.is_dir():
        for name in ["weapons.json","armours.json","accessories.json","clothing.json","materials.json","quest_items.json","trinkets.json"]:
            p = items_dir / name
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8-sig"))
                    items += [x for x in data.get("items", []) if isinstance(x, dict)]
                except Exception as e:
                    print(f"[WARN] load {p}: {e}")
    out = []
    for it in items:
        nm = it.get("name") or it.get("Name") or it.get("id") or "?"
        out.append({"id": it.get("id", "?"), "name": nm, "type": it.get("type") or it.get("Type") or "item"})
    return out

def gather_npcs():
    friendly, hostile = [], []
    npcs_dir = DATA_DIR / "npcs"
    files = [("allies.json", False), ("animals.json", False), ("citizens.json", False),
             ("enemies.json", True), ("monsters.json", True)]
    if npcs_dir.is_dir():
        for fname, is_hostile in files:
            p = npcs_dir / fname
            if not p.exists(): continue
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                for n in data.get("npcs", []):
                    nm = n.get("name") or n.get("id") or "?"
                    obj = {"id": n.get("id","?"), "name": nm, "race": n.get("race","-")}
                    if is_hostile: hostile.append(obj)
                    else: friendly.append(obj)
            except Exception as e:
                print(f"[WARN] load {p}: {e}")
    return friendly, hostile

def load_world():
    obj = safe_load_json(WORLD_MAP, {})
    obj.setdefault("maps", {})
    obj.setdefault("dungeons", {})
    obj.setdefault("start", {"map":"", "pos":[0,0]})
    return obj

def load_overrides():
    return safe_load_json(OVERRIDES, {})

class Button:
    def __init__(self, rect, label, cb):
        self.rect = pg.Rect(rect)
        self.label = label
        self.cb = cb
    def draw(self, surf, font):
        hovered = self.rect.collidepoint(pg.mouse.get_pos())
        pg.draw.rect(surf, COL_BTN_H if hovered else COL_BTN, self.rect, border_radius=8)
        pg.draw.rect(surf, (120,124,150), self.rect, 1, border_radius=8)
        txt = font.render(self.label, True, COL_TEXT)
        surf.blit(txt, (self.rect.x + 10, self.rect.y + (self.rect.h - txt.get_height())//2))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1 and self.rect.collidepoint(ev.pos):
            self.cb()

class TextInput:
    def __init__(self, rect, text=""):
        self.rect = pg.Rect(rect); self.text = text
        self.active = False; self.cursor = len(text)
    def draw(self, surf, font):
        pg.draw.rect(surf, (36,38,48), self.rect, border_radius=6)
        pg.draw.rect(surf, (90,94,112), self.rect, 1, border_radius=6)
        txt = font.render(self.text, True, COL_TEXT)
        surf.blit(txt, (self.rect.x + 8, self.rect.y + (self.rect.h - txt.get_height())//2))
        if self.active and (pg.time.get_ticks()//500)%2==0:
            cx = self.rect.x + 8 + font.size(self.text[:self.cursor])[0]
            cy = self.rect.y + (self.rect.h - txt.get_height())//2
            pg.draw.line(surf, COL_TEXT, (cx,cy), (cx,cy+txt.get_height()))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(ev.pos)
        if not self.active: return
        if ev.type == pg.KEYDOWN:
            if ev.key == pg.K_BACKSPACE:
                if self.cursor>0:
                    self.text = self.text[:self.cursor-1] + self.text[self.cursor:]
                    self.cursor -= 1
            elif ev.key == pg.K_DELETE:
                self.text = self.text[:self.cursor] + self.text[self.cursor+1:]
            elif ev.key == pg.K_LEFT:
                self.cursor = max(0, self.cursor-1)
            elif ev.key == pg.K_RIGHT:
                self.cursor = min(len(self.text), self.cursor+1)
            elif ev.key == pg.K_HOME:
                self.cursor = 0
            elif ev.key == pg.K_END:
                self.cursor = len(self.text)
            elif ev.unicode and ev.unicode.isprintable():
                self.text = self.text[:self.cursor] + ev.unicode + self.text[self.cursor:]
                self.cursor += 1

class ListBox:
    def __init__(self, rect):
        self.rect = pg.Rect(rect); self.items = []; self.scroll=0; self.sel=-1; self.filter=""
    def set_items(self, items):
        self.items = items; self.scroll=0; self.sel=-1
    def filtered(self):
        if not self.filter: return self.items
        f = self.filter.lower()
        return [it for it in self.items if f in it[1].lower() or f in it[0].lower()]
    def draw(self, surf, font):
        pg.draw.rect(surf, (32,34,46), self.rect, border_radius=8)
        pg.draw.rect(surf, (90,94,112), self.rect, 1, border_radius=8)
        visible = self.filtered()
        y = self.rect.y + 6 - self.scroll
        h = 26
        for idx, (iid, label) in enumerate(visible):
            r = pg.Rect(self.rect.x+6, y, self.rect.w-12, h-4)
            if r.bottom < self.rect.y: y += h; continue
            if r.top > self.rect.bottom: break
            hovered = r.collidepoint(pg.mouse.get_pos())
            sel = (idx == self.sel)
            base = (58,60,76) if hovered else (42,44,56)
            if sel: base = (76,78,96)
            pg.draw.rect(surf, base, r, border_radius=6)
            txt = font.render(label, True, COL_TEXT)
            surf.blit(txt, (r.x + 8, r.y + (r.h - txt.get_height())//2))
            y += h
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and self.rect.collidepoint(ev.pos):
            rel_y = ev.pos[1] - self.rect.y + self.scroll
            idx = rel_y // 26
            vis = self.filtered()
            if 0 <= idx < len(vis): self.sel = idx
        if ev.type == pg.MOUSEWHEEL and self.rect.collidepoint(pg.mouse.get_pos()):
            self.scroll = max(0, self.scroll - ev.y*26)

# ---------- Start Picker ----------
class StartPicker:
    def __init__(self, sw, sh):
        self.SW, self.SH = sw, sh
        self.kind = "map"
        self.font = pg.font.Font(None, 28); self.small = pg.font.Font(None, 20)
        self.inp_name = TextInput((sw//2-220, sh//2-30, 440, 34), "newmap")
        self.inp_w = TextInput((sw//2-220, sh//2+40, 100, 30), "5")
        self.inp_h = TextInput((sw//2-100, sh//2+40, 100, 30), "5")
        self.list = ListBox((sw//2-300, 120, 600, 300)); self.refresh_list()
        self.choice = None
    def refresh_list(self):
        wm = load_world(); coll = wm.get("maps" if self.kind=="map" else "dungeons", {})
        items = [(k, f"{k} → {v.get('file','?')}") for k,v in sorted(coll.items())]
        self.list.set_items(items)
    def draw(self, screen):
        screen.fill((16,16,20))
        title = self.font.render("RPGenesis – Map/Dungeon Picker", True, COL_TEXT)
        screen.blit(title, (self.SW//2 - title.get_width()//2, 30))
        bx = self.SW//2 - 160
        for i,(lab,k) in enumerate([("Map","map"),("Dungeon","dungeon")]):
            r = pg.Rect(bx + i*180, 70, 160, 32); active = (self.kind==k)
            pg.draw.rect(screen, COL_BTN_H if active else COL_BTN, r, border_radius=8)
            pg.draw.rect(screen, (120,124,150), r, 1, border_radius=8)
            screen.blit(self.small.render(lab, True, COL_TEXT), (r.x+12, r.y+8))
        screen.blit(self.small.render("Open existing:", True, COL_SUBTLE), (self.SW//2-300, 100))
        self.list.draw(screen, self.small)
        y = self.SH//2
        screen.blit(self.small.render("Create new:", True, COL_SUBTLE), (self.SW//2-300, y-60))
        screen.blit(self.small.render("Name:", True, COL_SUBTLE), (self.SW//2-300, y-28))
        self.inp_name.draw(screen, self.small)
        screen.blit(self.small.render("Size (W x H):", True, COL_SUBTLE), (self.SW//2-300, y+14))
        self.inp_w.draw(screen, self.small); self.inp_h.draw(screen, self.small)
        btn_open = pg.Rect(self.SW//2-300, self.SH-120, 180, 36)
        btn_create = pg.Rect(self.SW//2-100, self.SH-120, 180, 36)
        for r,lab in [(btn_open,"Open Selected"),(btn_create,"Create New")]:
            pg.draw.rect(screen, COL_BTN, r, border_radius=8)
            pg.draw.rect(screen, (120,124,150), r, 1, border_radius=8)
            screen.blit(self.small.render(lab, True, COL_TEXT), (r.x+14, r.y+8))
        return btn_open, btn_create
    def handle(self, ev):
        self.inp_name.handle(ev); self.inp_w.handle(ev); self.inp_h.handle(ev); self.list.handle(ev)
        if ev.type == pg.MOUSEBUTTONDOWN:
            bx = self.SW//2 - 160
            r_map = pg.Rect(bx, 70, 160, 32); r_dng = pg.Rect(bx + 180, 70, 160, 32)
            if r_map.collidepoint(ev.pos): self.kind = "map"; self.refresh_list()
            if r_dng.collidepoint(ev.pos): self.kind = "dungeon"; self.refresh_list()
    def click_buttons(self, btn_open, btn_create):
        mx,my = pg.mouse.get_pos()
        if pg.mouse.get_pressed()[0]:
            if btn_open.collidepoint((mx,my)):
                sel = self.list.filtered(); idx = self.list.sel
                if 0 <= idx < len(sel):
                    name = sel[idx][0]; self.choice = ("open", self.kind, name, 0, 0)
            if btn_create.collidepoint((mx,my)):
                try: w = max(1, min(200, int(self.inp_w.text))); h = max(1, min(200, int(self.inp_h.text)))
                except: w,h = 5,5
                name = (self.inp_name.text or "newmap").strip()
                self.choice = ("create", self.kind, name, w, h)

# ---------- Editor ----------
class Editor:
    def __init__(self, screen_w, screen_h, kind, name, w, h, create=False):
        self.SW, self.SH = screen_w, screen_h
        self.edit_kind = kind; self.map_name = name
        self.W, self.H = max(1,w), max(1,h)
        self.grid = [["." for _ in range(self.W)] for __ in range(self.H)]
        self.overlays: Dict[Tuple[int,int], Dict] = {}
        self.links: Dict[Tuple[int,int], Dict] = {}
        self.map_meta = {"biome":"forest","safe": False}
        self.items = gather_items()
        self.npcs_friendly, self.npcs_hostile = gather_npcs()
        self.cam_x, self.cam_y = 0, 0
        self.font = pg.font.Font(None, 24); self.small = pg.font.Font(None, 18)
        self.panel_x = self.SW - PANEL_W
        self.selected_tile: Tuple[int,int] | None = None
        # history for undo
        self.history: List[Tuple] = []
        # UI - Name field
        y = 16; self.label_name_pos = (self.panel_x+16, y); y += 22
        self.inp_map = TextInput((self.panel_x+16, y, PANEL_W-32, 30), self.map_name); y += 40
        # Resize controls
        self.resize_w = TextInput((self.panel_x+16, y, 80, 28), str(self.W))
        self.resize_h = TextInput((self.panel_x+106, y, 80, 28), str(self.H))
        self.btn_apply_resize = Button((self.panel_x+196, y, 100, 28), "Apply Size", self.apply_resize)
        self.btn_undo = Button((self.panel_x+306, y, 90, 28), "Undo", self.undo)
        y += 40
        # Palette title
        self.palette_y = y
        # Tabs: Terrain / NPC / Enemy / Chest / Exit
        self.tab = "terrain"
        self.tab_buttons = [
            Button((self.panel_x+16, y, 90, 26), "Terrain", lambda: self.set_tab("terrain")),
            Button((self.panel_x+112, y, 90, 26), "NPC", lambda: self.set_tab("npc")),
            Button((self.panel_x+208, y, 90, 26), "Enemy", lambda: self.set_tab("enemy")),
            Button((self.panel_x+304, y, 90, 26), "Chest", lambda: self.set_tab("chest")),
            Button((self.panel_x+400, y, 100, 26), "Entrance", lambda: self.set_tab("link")),
        ]
        y += 34
        # Filter + list for NPC/Enemy/Chest/Link target
        self.label_filter_pos = (self.panel_x+16, y); y += 18
        self.inp_filter = TextInput((self.panel_x+16, y, PANEL_W-32, 28)); y += 34
        self.list_box = ListBox((self.panel_x+16, y, PANEL_W-32, 360)); y += 370
        # Place/Clear buttons
        self.btn_place = Button((self.panel_x+16, y, 120, 32), "Place", self.place_from_selection)
        self.btn_clear = Button((self.panel_x+146, y, 120, 32), "Clear", self.clear_selected)
        self.btn_save = Button((self.panel_x+276, y, 120, 32), "Save", self.save_all)
        # Init
        if not create:
            self.load_map_file(name)
        self.refresh_list()

    # ---- helpers ----
    def snapshot(self):
        # push a copy for undo
        if len(self.history) > 50: self.history.pop(0)
        self.history.append((copy.deepcopy(self.grid),
                             copy.deepcopy(self.overlays),
                             copy.deepcopy(self.links),
                             self.W, self.H))
    def undo(self):
        if not self.history: return
        self.grid, self.overlays, self.links, self.W, self.H = self.history.pop()
        print("[OK] Undo")

    def set_tab(self, t):
        self.tab = t
        self.refresh_list()

    def _dir_for_kind(self):
        return MAPS_DIR if self.edit_kind == "map" else DUNGEONS_DIR
    def _section_for_kind(self):
        return "maps" if self.edit_kind == "map" else "dungeons"

    def apply_resize(self):
        try:
            w = max(1, min(200, int(self.resize_w.text)))
            h = max(1, min(200, int(self.resize_h.text)))
        except:
            w,h = self.W, self.H
        if (w,h) != (self.W,self.H):
            self.snapshot()
            new_grid = [["." for _ in range(w)] for __ in range(h)]
            for y in range(min(self.H, h)):
                for x in range(min(self.W, w)):
                    new_grid[y][x] = self.grid[y][x]
            self.grid = new_grid
            self.overlays = {k:v for k,v in self.overlays.items() if k[0] < w and k[1] < h}
            self.links = {k:v for k,v in self.links.items() if k[0] < w and k[1] < h}
            self.W, self.H = w, h
            print(f"[OK] Resized to {w}x{h}")

    def refresh_list(self):
        if self.tab == "npc":
            self.list_box.set_items([(n["id"], f"{n['name']} ({n.get('race','-')})") for n in self.npcs_friendly])
        elif self.tab == "enemy":
            entries = [("random_unaware","Random (unaware)"),("random","Random (alerted)")]
            entries += [(n["id"], f"{n['name']} ({n.get('race','-')})") for n in self.npcs_hostile]
            self.list_box.set_items(entries)
        elif self.tab == "chest":
            self.list_box.set_items([("chest_common","Chest (Common)"),("chest_rare","Chest (Rare)"),("chest_epic","Chest (Epic)")])
        elif self.tab == "link":
            wm = load_world(); sec_maps = list(wm.get("maps",{}).keys()); sec_dng = list(wm.get("dungeons",{}).keys())
            items = [("map:"+k, f"[MAP] {k}") for k in sec_maps] + [("dungeon:"+k, f"[DUNGEON] {k}") for k in sec_dng]
            self.list_box.set_items(items)
        else:
            self.list_box.set_items([])

    def list_selected(self):
        vis = self.list_box.filtered()
        if 0 <= self.list_box.sel < len(vis): return vis[self.list_box.sel]
        return None

    # ---- file I/O ----
    def load_map_file(self, name: str):
        p = self._dir_for_kind() / f"{name}.txt"
        if not p.exists():
            print(f"[WARN] {self.edit_kind} '{name}' not found. Starting new.")
            return
        txt = p.read_text(encoding="utf-8").splitlines()
        txt = [ln.rstrip("\n") for ln in txt if ln.strip()!=""]
        w = max(len(ln) for ln in txt) if txt else 1
        self.H = len(txt); self.W = w
        self.resize_w.text = str(self.W); self.resize_h.text = str(self.H)
        self.grid = [list(ln.ljust(w, ".")) for ln in txt]
        self.map_name = name; self.inp_map.text = name
        # overrides
        ov = load_overrides(); key = name if self.edit_kind=="map" else f"dungeon:{name}"
        self.overlays = {}
        if key in ov:
            for k,v in ov[key].get("tiles",{}).items():
                try:
                    xs,ys = k.split(","); x,y = int(xs), int(ys)
                    self.overlays[(x,y)] = dict(v)
                except: pass
        # links from world
        world = load_world(); sec = self._section_for_kind()
        md = world.get(sec,{}).get(name,{})
        self.links = {}
        for L in md.get("links",[]):
            at = L.get("at"); to = L.get("to"); spawn = L.get("spawn",[0,0]); kind = L.get("kind","map")
            if at and to:
                self.links[tuple(at)] = {"to": to, "spawn": list(spawn), "kind": kind}

    def save_all(self):
        name = (self.inp_map.text or "noname").strip()
        self.map_name = name
        folder = self._dir_for_kind(); folder.mkdir(parents=True, exist_ok=True)
        lines = ["".join(row) for row in self.grid]
        safe_write_text(folder / f"{name}.txt", "\n".join(lines) + "\n")
        # overrides
        ov = load_overrides(); key = name if self.edit_kind=="map" else f"dungeon:{name}"
        mt = ov.get(key, {"tiles":{}}); mt["tiles"] = {}
        for (x,y), cfg in self.overlays.items():
            if cfg: mt["tiles"][f"{x},{y}"] = cfg
        ov[key] = mt; safe_write_json(OVERRIDES, ov)
        # world map links
        wm = load_world(); sec = self._section_for_kind(); coll = wm.get(sec, {})
        entry = coll.get(name, {"links": []})
        entry["file"] = f"{'maps' if self.edit_kind=='map' else 'dungeons'}/{name}.txt"
        links = []
        for (x,y), cfg in self.links.items():
            if cfg and "to" in cfg:
                links.append({"at":[x,y], "to": cfg["to"], "spawn": list(cfg.get("spawn",[0,0])), "kind": cfg.get("kind","map")})
        entry["links"] = links
        coll[name] = entry; wm[sec] = coll; safe_write_json(WORLD_MAP, wm)
        print(f"[OK] Saved {self.edit_kind} '{name}'")

    # ---- interactions ----
    def grid_pos_at_mouse(self):
        mx,my = pg.mouse.get_pos()
        if mx >= self.SW - PANEL_W: return None
        gx = (mx + self.cam_x) - PAD; gy = (my + self.cam_y) - PAD
        x = gx // (CELL+GAP); y = gy // (CELL+GAP)
        if 0 <= x < self.W and 0 <= y < self.H: return int(x), int(y)
        return None

    def left_click_grid(self):
        g = self.grid_pos_at_mouse()
        if g: self.selected_tile = g

    def place_from_selection(self):
        if not self.selected_tile: return
        x,y = self.selected_tile
        self.snapshot()
        if self.tab == "terrain":
            # use which button is pressed below (we detect by last clicked in quick palette state)
            # for simplicity, place OPEN; real choice via terrain buttons
            pass
        elif self.tab == "npc":
            sel = self.list_selected(); iid = sel[0] if sel else None
            if iid: self.overlays.setdefault((x,y),{})["npc"] = iid
        elif self.tab == "enemy":
            sel = self.list_selected(); iid = sel[0] if sel else None
            if iid: self.overlays.setdefault((x,y),{})["enemy"] = iid
        elif self.tab == "chest":
            sel = self.list_selected(); iid = sel[0] if sel else None
            if iid: self.overlays.setdefault((x,y),{})["item"] = iid
        elif self.tab == "link":
            sel = self.list_selected(); tgt = sel[0] if sel else None
            if tgt:
                kind,name = tgt.split(":",1)
                self.grid[y][x] = "E"
                self.links[(x,y)] = {"to": name, "spawn":[0,0], "kind": kind}
        print("[OK] Placed on", self.selected_tile)

    def clear_selected(self):
        if not self.selected_tile: return
        x,y = self.selected_tile
        self.snapshot()
        # clear overlay & link, keep terrain
        if (x,y) in self.overlays: del self.overlays[(x,y)]
        if (x,y) in self.links: del self.links[(x,y)]
        print("[OK] Cleared overlays at", (x,y))

    def paint_terrain(self, ch):
        if not self.selected_tile: return
        x,y = self.selected_tile
        self.snapshot()
        self.grid[y][x] = ch
        # if clearing exit, drop link
        if ch != "E" and (x,y) in self.links: del self.links[(x,y)]
        print(f"[OK] Painted {ch} at {(x,y)}")

    # ---- draw ----
    def draw(self, screen):
        screen.fill(GRID_BG)
        view_w = self.SW - PANEL_W
        mx,my = pg.mouse.get_pos()
        for y in range(self.H):
            for x in range(self.W):
                rx = PAD + x*(CELL+GAP) - self.cam_x
                ry = PAD + y*(CELL+GAP) - self.cam_y
                r = pg.Rect(rx, ry, CELL, CELL)
                if r.right < 0 or r.bottom < 0 or r.left > view_w or r.top > self.SH: continue
                ch = self.grid[y][x]
                base = COL_OPEN if ch=="." else COL_WALL
                if ch=="S": base = COL_START
                if ch=="E": base = COL_EXIT
                pg.draw.rect(screen, base, r, border_radius=6)
                pg.draw.rect(screen, COL_BORDER, r, 1, border_radius=6)
                ov = self.overlays.get((x,y))
                if ov:
                    tag = ("N" if ov.get("npc") else "") + ("X" if ov.get("enemy") else "") + ("$" if ov.get("item") else "")
                    if tag:
                        t = self.small.render(tag, True, COL_ACCENT)
                        screen.blit(t, (r.x+4, r.y+4))
                if (x,y) in self.links:
                    t2 = self.small.render("L", True, (200,180,120))
                    screen.blit(t2, (r.x + CELL-14, r.y+4))
                if (x,y) == self.selected_tile:
                    pg.draw.rect(screen, (255,220,120), r, 3, border_radius=6)
                elif r.collidepoint(mx,my):
                    pg.draw.rect(screen, COL_HOVER, r, 2, border_radius=6)

        # panel
        x0 = self.panel_x
        pg.draw.rect(screen, PANEL_BG, (x0, 0, PANEL_W, self.SH)); pg.draw.rect(screen, PANEL_BORDER, (x0, 0, PANEL_W, self.SH), 1)
        hdr = self.font.render(f"{self.edit_kind.upper()} — {self.map_name}  ({self.W}x{self.H})", True, COL_TEXT)
        screen.blit(hdr, (x0+16, 8))
        screen.blit(self.small.render("Name:", True, COL_SUBTLE), self.label_name_pos)
        self.inp_map.draw(screen, self.small)
        # resize row + undo
        self.resize_w.draw(screen, self.small); self.resize_h.draw(screen, self.small)
        self.btn_apply_resize.draw(screen, self.small); self.btn_undo.draw(screen, self.small)
        # selected tile info
        yinfo = 100
        lab = f"Selected: {self.selected_tile if self.selected_tile else '(click a tile)'}"
        screen.blit(self.small.render(lab, True, COL_SUBTLE), (x0+16, yinfo)); yinfo += 20

        # Tabs
        for b in self.tab_buttons: b.draw(screen, self.small)
        # Filter + list for tabs
        screen.blit(self.small.render("Filter:", True, COL_SUBTLE), self.label_filter_pos)
        self.inp_filter.draw(screen, self.small)
        self.list_box.filter = self.inp_filter.text
        if self.tab in ("npc","enemy","chest","link"):
            self.list_box.draw(screen, self.small)
        else:
            # show terrain palette buttons
            py = self.list_box.rect.y
            b1 = Button((x0+16, py, 80, 32), "Open '.'", lambda: self.paint_terrain("."))
            b2 = Button((x0+106, py, 80, 32), "Wall '#'", lambda: self.paint_terrain("#"))
            b3 = Button((x0+196, py, 80, 32), "Start 'S'", lambda: self.paint_terrain("S"))
            b4 = Button((x0+286, py, 80, 32), "Exit 'E'", lambda: self.paint_terrain("E"))
            for b in (b1,b2,b3,b4): b.draw(screen, self.small)
            # store to handle after drawing
            self.terrain_buttons = (b1,b2,b3,b4)

        # bottom action buttons
        self.btn_place.draw(screen, self.small); self.btn_clear.draw(screen, self.small); self.btn_save.draw(screen, self.small)

    # ---- events ----
    def handle_event(self, ev):
        # panel controls
        self.inp_map.handle(ev); self.resize_w.handle(ev); self.resize_h.handle(ev)
        self.inp_filter.handle(ev); self.list_box.handle(ev)
        for b in self.tab_buttons: b.handle(ev)
        self.btn_apply_resize.handle(ev); self.btn_undo.handle(ev)
        self.btn_place.handle(ev); self.btn_clear.handle(ev); self.btn_save.handle(ev)
        if self.tab == "terrain":
            for b in getattr(self, "terrain_buttons", []): b.handle(ev)

        # grid click
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            if ev.pos[0] < self.SW - PANEL_W:
                self.left_click_grid()

    # ---- save plumbing ----
    def _dir_for_kind(self):
        return MAPS_DIR if self.edit_kind == "map" else DUNGEONS_DIR
    def save_all(self):
        name = (self.inp_map.text or "noname").strip()
        self.map_name = name
        folder = self._dir_for_kind(); folder.mkdir(parents=True, exist_ok=True)
        lines = ["".join(row) for row in self.grid]
        safe_write_text(folder / f"{name}.txt", "\n".join(lines) + "\n")
        # overrides
        ov = load_overrides(); key = name if self.edit_kind=="map" else f"dungeon:{name}"
        mt = ov.get(key, {"tiles":{}}); mt["tiles"] = {}
        for (x,y), cfg in self.overlays.items():
            if cfg: mt["tiles"][f"{x},{y}"] = cfg
        ov[key] = mt; safe_write_json(OVERRIDES, ov)
        # world map links
        wm = load_world(); sec = "maps" if self.edit_kind=="map" else "dungeons"; coll = wm.get(sec, {})
        entry = coll.get(name, {"links": []})
        entry["file"] = f"{'maps' if self.edit_kind=='map' else 'dungeons'}/{name}.txt"
        links = []
        for (x,y), cfg in self.links.items():
            if cfg and "to" in cfg:
                links.append({"at":[x,y], "to": cfg["to"], "spawn": list(cfg.get("spawn",[0,0])), "kind": cfg.get("kind","map")})
        entry["links"] = links
        coll[name] = entry; wm[sec] = coll; safe_write_json(WORLD_MAP, wm)
        print(f"[OK] Saved {self.edit_kind} '{name}'")

# ---------- run ----------
def run():
    pg.init()
    (DATA_DIR/"maps").mkdir(parents=True, exist_ok=True)
    (DATA_DIR/"dungeons").mkdir(parents=True, exist_ok=True)

    screen = pg.display.set_mode((WIN_W, WIN_H))
    pg.display.set_caption("RPGenesis – Map/Dungeon Editor")
    clock = pg.time.Clock()

    picker = StartPicker(WIN_W, WIN_H); stage = "picker"; editor = None

    running = True
    while running:
        dt = clock.tick(60)
        for ev in pg.event.get():
            if ev.type == pg.QUIT: running = False
            elif ev.type == pg.KEYDOWN and ev.key == pg.K_ESCAPE: running = False

            if stage == "picker":
                picker.handle(ev)
            else:
                editor.handle_event(ev)

        if stage == "picker":
            btn_open, btn_create = picker.draw(screen)
            picker.click_buttons(btn_open, btn_create)
            if picker.choice:
                action, kind, name, w, h = picker.choice
                if action == "open":
                    editor = Editor(WIN_W, WIN_H, kind, name, 5, 5, create=False)
                else:
                    editor = Editor(WIN_W, WIN_H, kind, name, w, h, create=True)
                stage = "editor"
        else:
            editor.draw(screen)

        pg.display.flip()

    pg.quit()

if __name__ == "__main__":
    run()
