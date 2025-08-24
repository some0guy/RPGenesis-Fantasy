#!/usr/bin/env python3
# RPGenesis Map Editor (Tile-first, real maps dir)
# Loads NPCs/Enemies/Items catalogs from data/* and maps from data/maps/*.json
# Click a tile, then use the right panel to Set/Clear content. Save writes back to the selected map file.

import pygame as pg
import json, os, glob

WIN_W, WIN_H = 1280, 860
PANEL_W = 520
GRID_MARGIN = 16
TILE = 24

BG = (24,25,28)
FG = (235,235,238)
ACCENT = (160, 200, 255)
MUTED = (140, 140, 150)
HL = (84, 130, 212)

MAPS_DIR = "data/maps"

def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def collect_catalog():
    # NPCs (all files under data/npcs/*.json)
    npcs = []
    for p in glob.glob("data/npcs/*.json"):
        d = load_json(p, {})
        arr = d.get("npcs") or d.get("allies") or d.get("data") or []
        if isinstance(arr, list):
            for n in arr:
                if isinstance(n, dict):
                    vid = n.get("id") or n.get("name") or ""
                    name = n.get("name") or vid
                    race = n.get("race") or ""
                    npcs.append((vid, f"{name} [{race}]"))
    # Enemies (data/npcs/enemies.json preferred; else any with 'hostile')
    enemies = []
    for p in glob.glob("data/npcs/*.json"):
        d = load_json(p, {})
        arr = d.get("npcs") or []
        for n in arr if isinstance(arr, list) else []:
            if isinstance(n, dict) and (n.get("hostile") or (isinstance(n.get("stats"), dict) and n.get("level"))):
                vid = n.get("id") or n.get("name") or ""
                name = n.get("name") or vid
                race = n.get("race") or ""
                enemies.append((vid, f"{name} [{race}]"))
    # Items (merge all data/items/*.json)
    items = []
    for p in glob.glob("data/items/*.json"):
        d = load_json(p, {})
        arr = d.get("items") or []
        for it in arr if isinstance(arr, list) else []:
            if isinstance(it, dict):
                vid = it.get("id") or it.get("name") or ""
                nm = it.get("name") or vid
                items.append((vid, nm))
    # World map targets (build from filenames in maps dir)
    links = []
    for p in sorted(glob.glob(os.path.join(MAPS_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(p))[0]
        links.append((f"map:{name}", f"Map→{name}"))
    if not npcs: npcs=[("", "(no NPCs found)")]
    if not enemies: enemies=[("", "(no Enemies)")]
    if not items: items=[("", "(no Items)")]
    if not links: links=[("", "(no scenes)")]
    return npcs, enemies, items, links

class Button:
    def __init__(self, rect, text, cb):
        self.rect = pg.Rect(rect); self.text = text; self.cb = cb
    def draw(self, surf, font):
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        surf.blit(font.render(self.text, True, FG), self.rect.move(10,6))
    def handle(self, ev):
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1 and self.rect.collidepoint(ev.pos):
            self.cb()

class DropDown:
    def __init__(self, rect, placeholder, options, on_change=None):
        self.rect = pg.Rect(rect)
        self.placeholder = placeholder
        self.options = list(options)
        self.open = False
        self.sel_index = -1
        self.on_change = on_change
        self.item_h = 26
        self.max_show = 8
        self.scroll = 0
    @property
    def value(self):
        if 0 <= self.sel_index < len(self.options):
            return self.options[self.sel_index][0]
        return ""
    def set_value(self, val):
        for i,(v,_) in enumerate(self.options):
            if v==val:
                self.sel_index=i
                if self.on_change: self.on_change(val)
                return
    def draw(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        text = self.placeholder if self.sel_index<0 else self.options[self.sel_index][1]
        surf.blit(font.render(text, True, FG), (self.rect.x+8, self.rect.y+6))
        # list
        if self.open:
            L = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, self.item_h*min(self.max_show, len(self.options)))
            pg.draw.rect(surf, (40,42,46), L, border_radius=6)
            pg.draw.rect(surf, HL, L, width=2, border_radius=6)
            start=self.scroll; end=min(len(self.options), start+self.max_show)
            for i,opt_i in enumerate(range(start,end)):
                r = pg.Rect(L.x, L.y+i*self.item_h, L.w, self.item_h)
                surf.blit(font.render(self.options[opt_i][1], True, FG), (r.x+8, r.y+4))
    def handle(self, ev):
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1:
            if self.rect.collidepoint(ev.pos):
                self.open = not self.open
                return
            if self.open:
                L = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, self.item_h*min(self.max_show, len(self.options)))
                if L.collidepoint(ev.pos):
                    idx = (ev.pos[1]-L.y)//self.item_h
                    opt_i = self.scroll + int(idx)
                    if 0 <= opt_i < len(self.options):
                        self.sel_index = opt_i; self.open=False
                        if self.on_change: self.on_change(self.options[opt_i][0])
                else:
                    self.open=False
        elif ev.type==pg.MOUSEWHEEL and self.open:
            self.scroll = max(0, min(max(0, len(self.options)-self.max_show), self.scroll - ev.y))

class TextInput:
    def __init__(self, rect, placeholder=""):
        self.rect = pg.Rect(rect); self.text=""; self.placeholder=placeholder; self.focus=False
    def draw(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        shown = self.text if self.text else self.placeholder
        color = FG if self.text else MUTED
        surf.blit(font.render(shown, True, color), (self.rect.x+8, self.rect.y+6))
    def handle(self, ev):
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1:
            self.focus = self.rect.collidepoint(ev.pos)
        if self.focus and ev.type==pg.KEYDOWN:
            if ev.key==pg.K_BACKSPACE: self.text=self.text[:-1]
            elif ev.key==pg.K_RETURN: self.focus=False
            else:
                if ev.unicode and ev.unicode.isprintable(): self.text += ev.unicode

class Editor:
    def __init__(self):
        self.scene = {"name":"untitled","w":20,"h":12,"tiles":{},"links":[]}
        self.sel=None
        pg.init()
        pg.display.set_caption("RPGenesis Map Editor — Tile-first")
        self.screen = pg.display.set_mode((WIN_W, WIN_H))
        self.font = pg.font.SysFont(None, 18); self.small = pg.font.SysFont(None, 14)

        # catalogs
        self.npcs, self.enemies, self.items, self.link_targets = collect_catalog()

        # files
        files = [(f, os.path.splitext(os.path.basename(f))[0]) for f in sorted(glob.glob(os.path.join(MAPS_DIR, "*.json")))]
        if not files: files=[("", "(no map files found — create with New)")]
        self.dd_file = DropDown((WIN_W-PANEL_W+16, 18, 320, 30), "Select map file", [(p, label) for p,label in files], on_change=lambda p:self.load_path(p))

        # content controls
        y = 64; x0 = WIN_W-PANEL_W+16
        self.dd_npc = DropDown((x0, y, 280, 30), "NPC", self.npcs, on_change=lambda _:(self.set_npc() if self.sel else None))
        self.btn_set_npc = Button((x0+290, y, 80, 30), "Set", self.set_npc)
        self.btn_clr_npc = Button((x0+375, y, 80, 30), "Clear", self.clear_npc); y+=36

        self.dd_enemy = DropDown((x0, y, 280, 30), "Enemy", self.enemies, on_change=lambda _:(self.set_enemy() if self.sel else None))
        self.btn_set_enemy = Button((x0+290, y, 80, 30), "Set", self.set_enemy)
        self.btn_clr_enemy = Button((x0+375, y, 80, 30), "Clear", self.clear_enemy); y+=36

        self.dd_item = DropDown((x0, y, 280, 30), "Item", self.items, on_change=lambda _:(self.set_item() if self.sel else None))
        self.btn_set_item = Button((x0+290, y, 80, 30), "Set", self.set_item)
        self.btn_clr_item = Button((x0+375, y, 80, 30), "Clear", self.clear_item); y+=36

        self.dd_link = DropDown((x0, y, 280, 30), "Link target", self.link_targets, on_change=lambda _:(self.set_link() if self.sel else None))
        self.btn_set_link = Button((x0+290, y, 80, 30), "Set", self.set_link)
        self.btn_clr_link = Button((x0+375, y, 80, 30), "Clear", self.clear_link); y+=36

        self.inp_entry = TextInput((x0, y, 280, 30), "Entry name (e.g., east_gate)")
        self.btn_toggle_entry = Button((x0+290, y, 165, 30), "Toggle Entry", self.toggle_entry); y+=36

        self.inp_target_entry = TextInput((x0, y, 280, 30), "Target entry (optional)"); y+=40

        self.btn_save = Button((x0, y, 120, 32), "Save", self.save_file)
        self.btn_new  = Button((x0+130, y, 120, 32), "New", self.new_scene)
        self.btn_reload = Button((x0+260, y, 120, 32), "Reload", self.reload_catalogs)

        self.message=""
        self.path = files[0][0] if files and files[0][0] else ""

        # grid rect
        self.grid_rect = pg.Rect(GRID_MARGIN, GRID_MARGIN, WIN_W-PANEL_W-2*GRID_MARGIN, WIN_H-2*GRID_MARGIN)
        self.tile = max(16, min(32, min(self.grid_rect.w//self.scene["w"], self.grid_rect.h//self.scene["h"])))

        # auto-load first map
        if self.path:
            self.load_path(self.path)

    # --- catalog & files ---
    def reload_catalogs(self):
        self.npcs, self.enemies, self.items, self.link_targets = collect_catalog()
        self.dd_npc.options = self.npcs; self.dd_enemy.options=self.enemies; self.dd_item.options=self.items; self.dd_link.options=self.link_targets
        self.message = "Catalogs reloaded."

    def load_path(self, path):
        if not path: return
        try:
            d = load_json(path, None)
            if not d: raise RuntimeError("empty or invalid file")
            self.scene = d
            self.path = path
            # resize grid tile
            self.tile = max(16, min(32, min(self.grid_rect.w//self.scene.get("width", self.scene.get("w",20)),
                                            self.grid_rect.h//self.scene.get("height", self.scene.get("h",12)))))
            self.message = f"Loaded {os.path.basename(path)}"
        except Exception as e:
            self.message = f"Load failed: {e}"

    def save_file(self):
        if not self.path:
            # create new in maps dir
            os.makedirs(MAPS_DIR, exist_ok=True)
            self.path = os.path.join(MAPS_DIR, f"{self.scene.get('name','untitled')}.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.scene, f, indent=2, ensure_ascii=False)
        self.message = f"Saved {os.path.basename(self.path)}"

    def new_scene(self):
        self.scene = {"schema":"rpgen.map@1","name":"untitled","kind":"map","biome":"forest","safe":False,
                      "width":20,"height":12,"terrain":[[1]*20 for _ in range(12)], "entries":[], "links":[], "tiles":{}}
        self.sel=None; self.path=""; self.message="New scene created."

    # --- tile data helpers ---
    def _key(self,x,y): return f"{x},{y}"
    def _td(self,x,y): return self.scene.setdefault("tiles",{}).setdefault(self._key(x,y),{})

    # --- apply/clear ---
    def set_npc(self):
        if not self.sel: return
        v=self.dd_npc.value
        if not v: return
        self._td(*self.sel)["npc"]=v; self.message=f"NPC set {v}"
    def clear_npc(self):
        if not self.sel: return
        td=self.scene.get("tiles",{}).get(self._key(*self.sel)); 
        if td and "npc" in td: td.pop("npc")

    def set_enemy(self):
        if not self.sel: return
        v=self.dd_enemy.value
        if not v: return
        self._td(*self.sel)["enemy"]=v; self.message=f"Enemy set {v}"
    def clear_enemy(self):
        if not self.sel: return
        td=self.scene.get("tiles",{}).get(self._key(*self.sel)); 
        if td and "enemy" in td: td.pop("enemy")

    def set_item(self):
        if not self.sel: return
        v=self.dd_item.value
        if not v: return
        self._td(*self.sel)["item"]=v; self.message=f"Item set {v}"
    def clear_item(self):
        if not self.sel: return
        td=self.scene.get("tiles",{}).get(self._key(*self.sel)); 
        if td and "item" in td: td.pop("item")

    def set_link(self):
        if not self.sel: return
        v=self.dd_link.value
        if not v or ":" not in v: return
        kind,name = v.split(":",1)
        x,y = self.sel
        te = self.inp_target_entry.text.strip() or None
        # replace link at this tile
        self.scene.setdefault("links", [])
        self.scene["links"] = [ln for ln in self.scene["links"] if ln.get("at") != [x,y]]
        L={"at":[x,y],"to":name,"kind":kind}
        if te: L["target_entry"]=te
        self.scene["links"].append(L)
        self.message=f"Link set {kind}:{name}"
    def clear_link(self):
        if not self.sel: return
        x,y = self.sel
        if self.scene.get("links"):
            self.scene["links"]=[ln for ln in self.scene["links"] if ln.get("at") != [x,y]]

    def toggle_entry(self):
        if not self.sel: return
        nm = self.inp_entry.text.strip()
        td = self._td(*self.sel)
        if "entry" in td: td.pop("entry")
        else:
            if nm: td["entry"] = nm

    # --- draw ---
    def draw(self):
        s=self.screen; s.fill(BG)
        # grid
        gx,gy = GRID_MARGIN, GRID_MARGIN
        ts = self.tile
        W = self.scene.get("width", self.scene.get("w", 20))
        H = self.scene.get("height", self.scene.get("h", 12))
        for y in range(H):
            for x in range(W):
                r = pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
                pg.draw.rect(s, (36,37,40), r)
        # markers
        for key,td in self.scene.get("tiles",{}).items():
            x,y = map(int, key.split(","))
            r = pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
            txt = "".join([c for c in ["N" if "npc" in td else "", "X" if "enemy" in td else "", "$" if "item" in td else "", "E" if "entry" in td else ""]])
            s.blit(self.small.render(txt, True, ACCENT), (r.x+3, r.y+2))
        for ln in self.scene.get("links", []):
            x,y = ln.get("at",[0,0])
            r = pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
            pg.draw.rect(s, (120,180,120), r, width=2)
        if self.sel:
            x,y=self.sel
            r = pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
            pg.draw.rect(s, ACCENT, r, width=3)

        # right panel
        rp = pg.Rect(WIN_W-PANEL_W, 0, PANEL_W, WIN_H)
        pg.draw.rect(s, (30,31,35), rp)
        # widgets
        self.dd_file.draw(s, self.font)
        self.dd_npc.draw(s, self.font); self.btn_set_npc.draw(s, self.font); self.btn_clr_npc.draw(s, self.font)
        self.dd_enemy.draw(s, self.font); self.btn_set_enemy.draw(s, self.font); self.btn_clr_enemy.draw(s, self.font)
        self.dd_item.draw(s, self.font); self.btn_set_item.draw(s, self.font); self.btn_clr_item.draw(s, self.font)
        self.dd_link.draw(s, self.font); self.btn_set_link.draw(s, self.font); self.btn_clr_link.draw(s, self.font)
        self.inp_entry.draw(s, self.font); self.btn_toggle_entry.draw(s, self.font)
        self.inp_target_entry.draw(s, self.font)
        self.btn_save.draw(s, self.font); self.btn_new.draw(s, self.font); self.btn_reload.draw(s, self.font)

        # tile readout
        y0 = 420
        s.blit(self.font.render("Selected tile:", True, FG), (WIN_W-PANEL_W+16, y0))
        if self.sel:
            x,y = self.sel
            td = self.scene.get("tiles",{}).get(self._key(x,y), {})
            link = None
            for ln in self.scene.get("links",[]):
                if ln.get("at")==[x,y]: link=ln; break
            lines=[f"({x},{y})",
                   f"NPC: {td.get('npc','—')}",
                   f"Enemy: {td.get('enemy','—')}",
                   f"Item: {td.get('item','—')}",
                   f"Entry: {td.get('entry','—')}"]
            if link:
                link_text = f"{link.get('kind','?')}:{link.get('to','?')}"
                if link.get('target_entry'): link_text += f" @{link['target_entry']}"
            else:
                link_text = "—"
            lines.append(f"Link: {link_text}")
            for i,txt in enumerate(lines):
                s.blit(self.small.render(txt, True, FG), (WIN_W-PANEL_W+16, y0+24+18*i))
        else:
            s.blit(self.small.render("(none) — click a tile", True, MUTED), (WIN_W-PANEL_W+16, y0+24))

        if self.message:
            s.blit(self.small.render(self.message, True, ACCENT), (16, WIN_H-28))

        pg.display.flip()

    def handle(self, ev):
        # UI
        self.dd_file.handle(ev)
        self.dd_npc.handle(ev); self.btn_set_npc.handle(ev); self.btn_clr_npc.handle(ev)
        self.dd_enemy.handle(ev); self.btn_set_enemy.handle(ev); self.btn_clr_enemy.handle(ev)
        self.dd_item.handle(ev); self.btn_set_item.handle(ev); self.btn_clr_item.handle(ev)
        self.dd_link.handle(ev); self.btn_set_link.handle(ev); self.btn_clr_link.handle(ev)
        self.inp_entry.handle(ev); self.btn_toggle_entry.handle(ev)
        self.inp_target_entry.handle(ev); self.btn_save.handle(ev); self.btn_new.handle(ev); self.btn_reload.handle(ev)

        # grid select
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1 and self.grid_rect.collidepoint(ev.pos):
            gx,gy = GRID_MARGIN, GRID_MARGIN; ts=self.tile
            x=(ev.pos[0]-gx)//ts; y=(ev.pos[1]-gy)//ts
            W = self.scene.get("width", self.scene.get("w", 20))
            H = self.scene.get("height", self.scene.get("h", 12))
            if 0<=x<W and 0<=y<H: self.sel=(int(x),int(y))

    def run(self):
        clock=pg.time.Clock(); running=True
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: running=False
                else: self.handle(ev)
            self.draw(); clock.tick(60)

if __name__=="__main__":
    Editor().run()
