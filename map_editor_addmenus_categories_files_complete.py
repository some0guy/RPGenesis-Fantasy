#!/usr/bin/env python3
# RPGenesis Map Editor — Menus wired to category files (complete runnable build)
# - NPC menu → data/npcs/<category>.json (allies, animals, citizens, enemies, monsters)
# - Item menu → data/items/<category>.json (accessories, armour, clothing, materials, quest_items, trinkets, weapons)
# - Link menu (reciprocal optional)
# - Tiles default to Impassable; toggle to Path; bulk helpers for selection
# - Undo/Redo, Copy/Paste, Multi-Select
# - Chips show Name [id]; falls back gracefully if name missing

import pygame as pg
import json, re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

WIN_W, WIN_H = 1360, 1000
PANEL_W = 620
GRID_MARGIN = 16
BG = (24,25,28); FG = (230,230,230); ACCENT = (160,200,255); MUTED = (140,140,150); HL = (70,120,200)
SEL_COL = (210,170,80)

DATA_DIR = Path("data")
MAP_DIR = DATA_DIR / "maps"
NPC_DIR = DATA_DIR / "npcs"
ITEM_DIR = DATA_DIR / "items"
MAP_DIR.mkdir(parents=True, exist_ok=True)

NPC_CATS = ["allies","animals","citizens","enemies","monsters"]
ITEM_CATS = ["accessories","armour","clothing","materials","quest_items","trinkets","weapons"]

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
        for k in ["npcs","enemies","items","characters","actors","list","data","entries","creatures","monsters","records"]:
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

def discover_link_targets() -> List[str]:
    return sorted({p.stem for p in MAP_DIR.glob("*.json")})

def load_category_records(base_dir: Path, category: str) -> List[Dict[str,Any]]:
    filename = f"{category}.json"
    path = base_dir / filename
    recs = as_list(read_json(path))
    out = []
    for e in recs:
        name = e.get("name") or e.get("title") or e.get("id") or "Unknown"
        _id = e.get("id") or slugify(name)
        out.append({"id": str(_id), "name": str(name), **e})
    return out

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
        self.current_map: Optional[Path] = None

        # History
        self.history: List[dict] = []; self.redo_stack: List[dict] = []; self.max_history = 150

        # Clipboard
        self.clip_payload: Optional[dict] = None

        # Multi-selection
        self.multi_on = False; self.multi: set[tuple[int,int]] = set()

        # Link targets
        self.link_targets = discover_link_targets()

        # Name lookups populated from category loads
        self.name_by_id: Dict[str,str] = {}

        pg.init(); pg.display.set_caption("RPGenesis Editor — Menus + Category Files + Walkability")
        self.screen = pg.display.set_mode((WIN_W, WIN_H))
        self.font = pg.font.SysFont(None, 18); self.small = pg.font.SysFont(None, 14)

        self.grid_rect = pg.Rect(GRID_MARGIN, GRID_MARGIN, WIN_W-PANEL_W-2*GRID_MARGIN, WIN_H-2*GRID_MARGIN)
        self.tile_size = max(16, min(28, min(self.grid_rect.w//w, self.grid_rect.h//h)))

        rp_x = WIN_W-PANEL_W+16; y = 16

        # Map IO
        map_list = sorted([p.name for p in MAP_DIR.glob("*.json")])
        self.dd_map = DropDown((rp_x, y, 360, 30), "Select map file", [(name, name) for name in map_list])
        self.btn_open = Button((rp_x+370, y, 80, 30), "Open", self.open_selected_map)
        self.btn_save = Button((rp_x+455, y, 80, 30), "Save", self.save_file); y += 38

        self.btn_save_as = Button((rp_x, y, 120, 30), "Save As...", self.save_as_dialog)
        self.btn_new_map = Button((rp_x+130, y, 140, 30), "New Map", self.new_scene)
        self.btn_reload = Button((rp_x+280, y, 140, 30), "Reload Catalogs", self.reload_catalogs); y += 42

        # Undo/Redo
        self.btn_undo = Button((rp_x, y, 120, 30), "Undo (Ctrl+Z)", self.undo)
        self.btn_redo = Button((rp_x+130, y, 140, 30), "Redo (Ctrl+Y)", self.redo); y += 38

        # Copy/Paste
        self.btn_copy = Button((rp_x, y, 120, 30), "Copy Tile", self.copy_tile)
        self.btn_paste_merge = Button((rp_x+130, y, 140, 30), "Paste Merge", self.paste_merge)
        self.btn_paste_replace = Button((rp_x+280, y, 140, 30), "Paste Replace", self.paste_replace); y += 38

        # Multi-Select
        self.btn_multi_toggle = Button((rp_x, y, 160, 30), "Multi-Select: OFF", self.toggle_multi)
        self.btn_multi_clear  = Button((rp_x+170, y, 110, 30), "Clear Sel", self.clear_multi)
        self.btn_multi_merge  = Button((rp_x+285, y, 160, 30), "Paste→Sel (Merge)", self.paste_to_selection_merge)
        self.btn_multi_replace= Button((rp_x+450, y, 140, 30), "Paste→Sel (Repl)", self.paste_to_selection_replace)
        y += 42

        # --- NPC menu ---
        s = 28
        self.lbl_npc = Button((rp_x, y, 70, s), "NPC", lambda: None); self.lbl_npc.enabled = False
        self.dd_npc_cat = DropDown((rp_x+80, y, 180, s), "Category", [(c, c.title()) for c in NPC_CATS], on_change=lambda _ : self._rebuild_npc_options())
        self.inp_npc_filter = TextInput((rp_x+270, y, 150, s), "Filter…")
        self.dd_npc_entity = DropDown((rp_x+430, y, 160, s), "Select NPC", [])
        self.btn_add_npc = Button((rp_x+430, y+34, 160, s), "Add NPC to Tile", self.add_npc_from_menu)
        y += 70

        # --- Item menu ---
        self.lbl_item = Button((rp_x, y, 70, s), "Item", lambda: None); self.lbl_item.enabled = False
        self.dd_item_cat = DropDown((rp_x+80, y, 180, s), "Category", [(c, c.title()) for c in ITEM_CATS], on_change=lambda _ : self._rebuild_item_options())
        self.inp_item_filter = TextInput((rp_x+270, y, 150, s), "Filter…")
        self.dd_item_entity = DropDown((rp_x+430, y, 160, s), "Select Item", [])
        self.btn_add_item = Button((rp_x+430, y+34, 160, s), "Add Item to Tile", self.add_item_from_menu)
        y += 70

        # --- Link menu ---
        self.lbl_link = Button((rp_x, y, 70, s), "Link", lambda: None); self.lbl_link.enabled = False
        self.dd_link_map = DropDown((rp_x+80, y, 230, s), "Target map", [("map:"+n, "Map→"+n) for n in self.link_targets] or [("", "(no maps)")])
        self.inp_link_entry = TextInput((rp_x+320, y, 160, s), "Target entry (optional)")
        self.btn_add_link = Button((rp_x+490, y, 100, s), "Link it", self.add_link_from_menu)
        y += 46

        # Walkability
        self.btn_toggle_pass = Button((rp_x, y, 160, 30), "Toggle Path", self.toggle_passable)
        self.btn_sel_path = Button((rp_x+170, y, 140, 30), "Sel → Path", self.selection_path)
        self.btn_sel_block = Button((rp_x+315, y, 160, 30), "Sel → Impassable", self.selection_block)
        y += 42

        self.message = ""
        self.click_chips: List[Tuple[pg.Rect, str, str]] = []

        self._reset_history()

        # Initialize option lists empty
        self._rebuild_npc_options()
        self._rebuild_item_options()

    # ---------- history ----------
    def _snapshot_scene(self) -> dict:
        return json.loads(json.dumps(self.scene))
    def _reset_history(self):
        self.history = [self._snapshot_scene()]; self.redo_stack = []
    def _commit(self, msg: Optional[str] = None):
        snap = self._snapshot_scene()
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
            self.scene = json.loads(json.dumps(self.history[-1]))
            self.message = "Undo"
    def redo(self):
        if self.redo_stack:
            snap = self.redo_stack.pop()
            self.history.append(snap)
            self.scene = json.loads(json.dumps(snap))
            self.message = "Redo"

    # ---------- scene helpers ----------
    def _td(self, x, y):
        td = self.scene.setdefault("tiles", {}).setdefault(f"{x},{y}", {})
        if "npc" in td and "npcs" not in td: td["npcs"] = [td.pop("npc")]
        if "enemy" in td and "enemies" not in td: td["enemies"] = [td.pop("enemy")]
        if "item" in td and "items" not in td: td["items"] = [td.pop("item")]
        td.setdefault("npcs", []); td.setdefault("enemies", []); td.setdefault("items", [])
        if "passable" not in td: td["passable"] = False
        return td

    # ---------- rebuild option lists from files ----------
    def _rebuild_npc_options(self):
        cat = self.dd_npc_cat.value or ""
        recs = load_category_records(NPC_DIR, cat) if cat else []
        flt = (self.inp_npc_filter.text or "").lower().strip()
        opts = []
        for e in recs:
            if not flt or flt in e["name"].lower() or flt in e["id"].lower():
                label = f"{e['name']} [{e['id']}]"
                opts.append((e["id"], label))
                self.name_by_id[e["id"]] = e["name"]
        self.dd_npc_entity.set_options(opts or [("", "(no matches)")])

    def _rebuild_item_options(self):
        cat = self.dd_item_cat.value or ""
        recs = load_category_records(ITEM_DIR, cat) if cat else []
        flt = (self.inp_item_filter.text or "").lower().strip()
        opts = []
        for e in recs:
            if not flt or flt in e["name"].lower() or flt in e["id"].lower():
                label = f"{e['name']} [{e['id']}]"
                opts.append((e["id"], label))
                self.name_by_id[e["id"]] = e["name"]
        self.dd_item_entity.set_options(opts or [("", "(no matches)")])

    # ---------- add from menus ----------
    def add_npc_from_menu(self):
        if not self.sel: self.message = "Select a tile first"; return
        cat = self.dd_npc_cat.value or ""
        val = self.dd_npc_entity.value or ""
        if not cat or not val:
            self.message = "Choose NPC category & entity"; return
        td = self._td(*self.sel)
        if cat in ("enemies","monsters"):
            arr = td["enemies"]; tag = "Enemy"
        else:
            arr = td["npcs"]; tag = "NPC"
        if val not in arr:
            arr.append(val); self._commit(f"Added {tag}:{val}")
        else:
            self.message = "Already on tile"

    def add_item_from_menu(self):
        if not self.sel: self.message = "Select a tile first"; return
        cat = self.dd_item_cat.value or ""
        val = self.dd_item_entity.value or ""
        if not cat or not val:
            self.message = "Choose Item category & entity"; return
        td = self._td(*self.sel)
        arr = td["items"]
        if val not in arr:
            arr.append(val); self._commit(f"Added Item:{val}")
        else:
            self.message = "Already on tile"

    def add_link_from_menu(self):
        if not self.sel: self.message = "Select a tile first"; return
        val = self.dd_link_map.value
        if not val or ":" not in val: self.message = "Choose a target map"; return
        kind, name = val.split(":",1)
        x,y = self.sel
        before = json.dumps(self.scene.get("links", []), sort_keys=True)
        self.scene["links"] = [ln for ln in self.scene.get("links", []) if ln.get("at") != [x,y]]
        L = {"at":[x,y], "to":name, "kind":kind}
        te = self.inp_link_entry.text.strip()
        if te: L["target_entry"] = te
        self.scene.setdefault("links", []).append(L)
        after = json.dumps(self.scene.get("links", []), sort_keys=True)
        if after != before:
            self._commit(f"Set Link {kind}:{name}")
            if te:
                self._make_reciprocal_link(name, te)
        else:
            self.message = "Link unchanged"

    def _make_reciprocal_link(self, target_map: str, target_entry: str):
        if not self.current_map:
            self.message += " (reciprocal skipped: current map unsaved)"
            return
        cur_map_name = self.current_map.stem
        tpath = MAP_DIR / f"{target_map}.json"
        data = read_json(tpath)
        if not isinstance(data, dict) or "tiles" not in data:
            self.message += " (reciprocal skipped: target missing/invalid)"
            return
        tx,ty = None,None
        for key, td in data.get("tiles", {}).items():
            if isinstance(td, dict) and td.get("entry") == target_entry:
                try:
                    tx,ty = map(int, key.split(",")); break
                except Exception:
                    continue
        if tx is None:
            self.message += " (reciprocal skipped: target entry not found)"
            return
        links = data.setdefault("links", [])
        links = [ln for ln in links if ln.get("at") != [tx,ty]]
        links.append({"at":[tx,ty], "to":cur_map_name, "kind":"map", "target_entry": self._td(*self.sel).get("entry","")})
        data["links"] = links
        write_json(tpath, data)
        self.message += " (reciprocal created)"

    # ---------- copy/paste ----------
    def _tile_payload(self, x: int, y: int) -> dict:
        td = self._td(x,y)
        payload = {
            "npcs": list(td.get("npcs", [])),
            "enemies": list(td.get("enemies", [])),
            "items": list(td.get("items", [])),
            "passable": bool(td.get("passable", False)),
        }
        if "entry" in td: payload["entry"] = td["entry"]
        return payload
    def _apply_payload(self, x: int, y: int, payload: dict, mode: str):
        td = self._td(x,y)
        if mode == "replace":
            td["npcs"] = list(payload.get("npcs", []))
            td["enemies"] = list(payload.get("enemies", []))
            td["items"] = list(payload.get("items", []))
            td["passable"] = bool(payload.get("passable", False))
            if "entry" in payload: td["entry"] = payload["entry"]
            else: td.pop("entry", None)
        else:
            for k in ("npcs","enemies","items"):
                vals = payload.get(k, [])
                if not vals: continue
                have = set(td.get(k, []))
                for v in vals:
                    if v not in have:
                        td.setdefault(k, []).append(v); have.add(v)
            if "entry" in payload: td["entry"] = payload["entry"]
            if payload.get("passable") is True: td["passable"] = True

    def copy_tile(self):
        if not self.sel: self.message = "Copy: select a tile first"; return
        x,y = self.sel
        self.clip_payload = self._tile_payload(x,y)
        nN = len(self.clip_payload.get("npcs",[])); nE = len(self.clip_payload.get("enemies",[])); nI = len(self.clip_payload.get("items",[]))
        ent = self.clip_payload.get("entry"); pas = self.clip_payload.get("passable")
        self.message = f"Copied ({nN}N, {nE}X, {nI}$" + (f", entry:{ent}" if ent else "") + (", path" if pas else ", impassable") + ")"

    def paste_merge(self): self._paste_do("merge")
    def paste_replace(self): self._paste_do("replace")
    def _paste_do(self, mode: str):
        if not self.sel: self.message = "Paste: select a tile first"; return
        if not self.clip_payload: self.message = "Clipboard is empty"; return
        x,y = self.sel
        before = json.dumps(self._td(x,y), sort_keys=True)
        self._apply_payload(x,y,self.clip_payload,mode)
        after = json.dumps(self._td(x,y), sort_keys=True)
        if after != before:
            self._commit(f"Pasted ({mode}) to {x},{y}")
        else:
            self.message = "Paste made no changes"

    # ---------- multi-select bulk paste ----------
    def toggle_multi(self):
        self.multi_on = not self.multi_on
        self.btn_multi_toggle.text = f"Multi-Select: {'ON' if self.multi_on else 'OFF'}"
        if not self.multi_on: self.multi.clear()
        self.message = "Multi-Select enabled" if self.multi_on else "Multi-Select cleared & off"
    def clear_multi(self):
        self.multi.clear(); self.message = "Selection cleared"
    def paste_to_selection_merge(self): self._paste_to_selection("merge")
    def paste_to_selection_replace(self): self._paste_to_selection("replace")
    def _paste_to_selection(self, mode: str):
        if not self.clip_payload: self.message = "Clipboard is empty"; return
        if not self.multi: self.message = "No tiles selected"; return
        before_scene = json.dumps(self.scene, sort_keys=True)
        changed = 0
        for (x,y) in sorted(self.multi):
            before = json.dumps(self._td(x,y), sort_keys=True)
            self._apply_payload(x,y,self.clip_payload,mode)
            after = json.dumps(self._td(x,y), sort_keys=True)
            if after != before: changed += 1
        if json.dumps(self.scene, sort_keys=True) != before_scene:
            self._commit(f"Pasted to {changed} tiles ({mode})")
        else:
            self.message = "Selection paste made no changes"

    # ---------- walkability ----------
    def toggle_passable(self):
        if not self.sel: self.message = "Select a tile first"; return
        td = self._td(*self.sel)
        td["passable"] = not bool(td.get("passable", False))
        self._commit("Set to Path" if td["passable"] else "Set to Impassable")
    def selection_path(self):
        if not self.multi: self.message = "No tiles selected"; return
        changed = 0
        for (x,y) in self.multi:
            td = self._td(x,y)
            if not td.get("passable", False):
                td["passable"] = True; changed += 1
        if changed: self._commit(f"Marked {changed} tiles as Path")
        else: self.message = "All selected already Path"
    def selection_block(self):
        if not self.multi: self.message = "No tiles selected"; return
        changed = 0
        for (x,y) in self.multi:
            td = self._td(x,y)
            if td.get("passable", False):
                td["passable"] = False; changed += 1
        if changed: self._commit(f"Marked {changed} tiles Impassable")
        else: self.message = "All selected already Impassable"

    # ---------- map IO ----------
    def open_selected_map(self):
        name = self.dd_map.value
        if not name: self.message = "Select a map file first."; return
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
        fn = (self.inp_link_entry.text or "new_map").strip()
        safe = slugify(fn)
        path = MAP_DIR / f"{safe}.json"
        write_json(path, self.scene)
        self.current_map = path
        names = sorted([p.name for p in MAP_DIR.glob("*.json")])
        self.dd_map.set_options([(n, n) for n in names])
        self.dd_map.select_value(path.name)
        self.message = f"Saved As {path.name}"

    def new_scene(self):
        self.scene = {"name":"untitled","w":self.grid_w,"h":self.grid_h,"tiles":{},"links":[]}
        self.sel = None; self.current_map = None
        self._reset_history(); self.message = "New map created (unsaved)"

    def reload_catalogs(self):
        self.link_targets = discover_link_targets()
        self.dd_link_map.set_options([("map:"+n, "Map→"+n) for n in self.link_targets] or [("", "(no maps)")])
        self._rebuild_npc_options(); self._rebuild_item_options()
        names = sorted([p.name for p in MAP_DIR.glob("*.json")])
        self.dd_map.set_options([(n, n) for n in names])
        self.message = "Catalogs + maps reloaded"

    # ---------- draw ----------
    def _update_button_states(self):
        self.btn_undo.enabled = len(self.history) > 1
        self.btn_redo.enabled = len(self.redo_stack) > 0

    def _label_for_id(self, _id: str) -> str:
        name = self.name_by_id.get(_id)
        if name and name != _id:
            return f"{name} [{_id}]"
        return _id

    def _draw_chips_row(self, surf, x0, y0, ids, kind):
        cur_x = x0; cur_y = y0; max_w = PANEL_W - 32
        for _id in ids:
            label = self._label_for_id(_id) + " ✖"
            rend = self.small.render(label, True, FG)
            w,h = rend.get_size()
            chip_w, chip_h = w+12, h+8
            if cur_x + chip_w > x0 + max_w:
                cur_x = x0; cur_y += chip_h + 6
            rect = pg.Rect(cur_x, cur_y, chip_w, chip_h)
            pg.draw.rect(surf, (45,47,52), rect, border_radius=10)
            pg.draw.rect(surf, HL, rect, width=1, border_radius=10)
            surf.blit(rend, (rect.x+6, rect.y+4))
            x_rect = pg.Rect(rect.right-18, rect.y+2, 16, max(16, h))
            self.click_chips.append((x_rect, kind, _id))
            cur_x += chip_w + 8
        return cur_y + 28

    def draw(self):
        s = self.screen; s.fill(BG)
        self._update_button_states()

        # grid
        gx,gy,gw,gh = self.grid_rect; ts = self.tile_size
        for yy in range(self.scene.get("h", self.grid_h)):
            for xx in range(self.scene.get("w", self.grid_w)):
                r = pg.Rect(gx + xx*ts, gy + yy*ts, ts-1, ts-1)
                pg.draw.rect(s, (36,37,40), r)
                td = self.scene.get("tiles", {}).get(f"{xx},{yy}")
                passable = bool(td.get("passable", False)) if isinstance(td, dict) else False
                if passable:
                    pg.draw.rect(s, (40,60,40), r)
        # tile tags
        for key, td0 in self.scene.get("tiles", {}).items():
            xx,yy = map(int, key.split(","))
            td = self._td(xx,yy)
            r = pg.Rect(gx + xx*ts, gy + yy*ts, ts-1, ts-1)
            tags = []
            if td["npcs"]: tags.append(f"N{len(td['npcs']) if len(td['npcs'])>1 else ''}")
            if td["enemies"]: tags.append(f"X{len(td['enemies']) if len(td['enemies'])>1 else ''}")
            if td["items"]: tags.append(f"${len(td['items']) if len(td['items'])>1 else ''}")
            if "entry" in td: tags.append("E")
            if td.get("passable", False): tags.append("·")
            s.blit(self.small.render(" ".join(tags), True, ACCENT), (r.x+3, r.y+2))
        # links outline
        for ln in self.scene.get("links", []):
            x,y = ln.get("at", [0,0])
            r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1); pg.draw.rect(s, (110,180,120), r, 2)
        # selections
        for (x,y) in self.multi:
            r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1); pg.draw.rect(s, SEL_COL, r, 2)
        if self.sel:
            x,y = self.sel; r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1); pg.draw.rect(s, ACCENT, r, 3)

        # right panel
        rp = pg.Rect(WIN_W-PANEL_W, 0, PANEL_W, WIN_H)
        pg.draw.rect(s, (30,31,35), rp)

        for w in [
            self.dd_map, self.btn_open, self.btn_save,
            self.btn_save_as, self.btn_new_map, self.btn_reload,
            self.btn_undo, self.btn_redo,
            self.btn_copy, self.btn_paste_merge, self.btn_paste_replace,
            self.btn_multi_toggle, self.btn_multi_clear, self.btn_multi_merge, self.btn_multi_replace,
            self.lbl_npc, self.dd_npc_cat, self.inp_npc_filter, self.dd_npc_entity, self.btn_add_npc,
            self.lbl_item, self.dd_item_cat, self.inp_item_filter, self.dd_item_entity, self.btn_add_item,
            self.lbl_link, self.dd_link_map, self.inp_link_entry, self.btn_add_link,
            self.btn_toggle_pass, self.btn_sel_path, self.btn_sel_block
        ]:
            if isinstance(w, DropDown): w.draw_base(s, self.font)
            elif isinstance(w, TextInput): w.draw(s, self.font)
            else: w.draw(s, self.font)

        # Selected tile detail
        self.click_chips.clear()
        x0 = WIN_W-PANEL_W+16; y0 = 560
        s.blit(self.font.render("Selected tile:", True, FG), (x0, y0))
        if self.sel:
            x,y = self.sel; td = self._td(x,y)
            s.blit(self.small.render(f"({x},{y})  Walkability: {'Path' if td.get('passable') else 'Impassable'}", True, FG), (x0, y0+24))
            line_y = y0 + 50
            s.blit(self.small.render("NPCs:", True, FG), (x0, line_y)); line_y += 20
            line_y = self._draw_chips_row(s, x0, line_y, td["npcs"], "npc")
            s.blit(self.small.render("Enemies:", True, FG), (x0, line_y)); line_y += 20
            line_y = self._draw_chips_row(s, x0, line_y, td["enemies"], "enemy")
            s.blit(self.small.render("Items:", True, FG), (x0, line_y)); line_y += 20
            line_y = self._draw_chips_row(s, x0, line_y, td["items"], "item")
            # link info
            link = None
            for ln in self.scene.get("links", []):
                if ln.get("at")==[x,y]: link = ln; break
            s.blit(self.small.render(f"Entry: {td.get('entry','—')}", True, FG), (x0, line_y)); line_y += 20
            link_text = "—"
            if link:
                link_text = f"{link['kind']}:{link['to']}"
                if link.get('target_entry'): link_text += f" @{link['target_entry']}"
            s.blit(self.small.render(f"Link: {link_text}", True, FG), (x0, line_y))
        else:
            s.blit(self.small.render("(none) — click a tile", True, MUTED), (x0, y0+24))

        # Popups last
        for dd in [self.dd_map, self.dd_npc_cat, self.dd_npc_entity, self.dd_item_cat, self.dd_item_entity, self.dd_link_map]:
            dd.draw_popup(s, self.font)

        hist_txt = f"History: {len(self.history)} | Redo: {len(self.redo_stack)}"
        s.blit(self.small.render(hist_txt, True, MUTED), (16, WIN_H-48))
        if self.message:
            s.blit(self.small.render(self.message, True, ACCENT), (16, WIN_H-28))

        pg.display.flip()

    # ---------- handle ----------
    def handle(self, ev):
        # open dropdowns first
        for dd in [self.dd_map, self.dd_npc_cat, self.dd_npc_entity, self.dd_item_cat, self.dd_item_entity, self.dd_link_map]:
            if dd.open and dd.handle(ev): return

        # widgets
        for w in [
            self.dd_map, self.btn_open, self.btn_save,
            self.btn_save_as, self.btn_new_map, self.btn_reload,
            self.btn_undo, self.btn_redo,
            self.btn_copy, self.btn_paste_merge, self.btn_paste_replace,
            self.btn_multi_toggle, self.btn_multi_clear, self.btn_multi_merge, self.btn_multi_replace,
            self.dd_npc_cat, self.inp_npc_filter, self.dd_npc_entity, self.btn_add_npc,
            self.dd_item_cat, self.inp_item_filter, self.dd_item_entity, self.btn_add_item,
            self.dd_link_map, self.inp_link_entry, self.btn_add_link,
            self.btn_toggle_pass, self.btn_sel_path, self.btn_sel_block
        ]:
            if hasattr(w, "handle") and w.handle(ev): return

        # live filter updates + shortcuts
        if ev.type == pg.KEYDOWN:
            if self.inp_npc_filter.focus: self._rebuild_npc_options()
            if self.inp_item_filter.focus: self._rebuild_item_options()
            if (pg.key.get_mods() & pg.KMOD_CTRL):
                if ev.key == pg.K_s: self.save_file()
                elif ev.key == pg.K_c: self.copy_tile()
                elif ev.key == pg.K_v and (pg.key.get_mods() & pg.KMOD_SHIFT): self.paste_replace()
                elif ev.key == pg.K_v: self.paste_merge()
                elif ev.key == pg.K_z and (pg.key.get_mods() & pg.KMOD_SHIFT): self.redo()
                elif ev.key == pg.K_z: self.undo()
                elif ev.key == pg.K_y: self.redo()

        # chips remove
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, kind, _id in list(self.click_chips):
                if rect.collidepoint(ev.pos):
                    if not self.sel: return
                    td = self._td(*self.sel)
                    arr = td["items"] if kind=="item" else (td["enemies"] if kind=="enemy" else td["npcs"])
                    if _id in arr:
                        arr.remove(_id); self._commit(f"Removed {kind}:{_id}")
                    return

        # grid click
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1 and self.grid_rect.collidepoint(ev.pos):
            gx,gy,gw,gh = self.grid_rect; ts = self.tile_size
            x = (ev.pos[0]-gx)//ts; y = (ev.pos[1]-gy)//ts
            if 0<=x<self.scene.get("w", self.grid_w) and 0<=y<self.scene.get("h", self.grid_h):
                self.sel = (int(x), int(y))
                if self.multi_on:
                    if (x,y) in self.multi: self.multi.remove((x,y))
                    else: self.multi.add((x,y))

    # ---------- run ----------
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
