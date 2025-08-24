#!/usr/bin/env python3
# RPGenesis Map Editor — Tile-first, Multi-contents + Proper Dropdown Z-order
# - Multiple NPCs, Enemies, Items per tile (stored as lists: "npcs", "enemies", "items")
# - Backward compatible: if a tile uses legacy "npc"/"enemy"/"item" fields, they are migrated on load/use.
# - Dropdown menus render ON TOP of everything; when open, they eat clicks first.
# - Panel buttons: Add / Remove / Clear for each type. Link + Entry unchanged.
#
# Save/Load target: data/scene_out.json (adjust paths if needed)
# Catalogs: data/npcs.json, data/enemies.json, data/items.json, data/world_map.json

import pygame as pg
import json, os
from typing import List, Tuple

WIN_W, WIN_H = 1200, 820
PANEL_W = 500
GRID_MARGIN = 16
BG = (24,25,28); FG = (230,230,230); ACCENT = (160,200,255); MUTED = (140,140,150); HL = (70,120,200)

def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def load_catalogs():
    npcs = load_json("data/npcs.json", [])
    enemies = load_json("data/enemies.json", [])
    items = load_json("data/items.json", [])
    wm = load_json("data/world_map.json", {})
    return npcs, enemies, items, wm

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
        # options: List[(value,label)]
        self.rect = pg.Rect(rect); self.placeholder = placeholder; self.options = list(options)
        self.on_change = on_change
        self.open = False; self.sel_index = -1; self.scroll = 0
        self.item_h = 26; self.max_show = 10
    @property
    def value(self):
        if 0 <= self.sel_index < len(self.options): return self.options[self.sel_index][0]
        return ""
    def set_options(self, options):
        self.options = list(options); self.sel_index = -1; self.scroll = 0
    def draw_base(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        text = self.placeholder if self.sel_index < 0 else self.options[self.sel_index][1]
        surf.blit(font.render(text, True, FG), (self.rect.x+8, self.rect.y+5))
        pg.draw.polygon(surf, FG, [(self.rect.right-16, self.rect.y+10),
                                   (self.rect.right-8, self.rect.y+10),
                                   (self.rect.right-12, self.rect.y+16)])
    def draw_popup(self, surf, font):
        if not self.open: return
        h = self.item_h * min(self.max_show, len(self.options))
        list_rect = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, h)
        pg.draw.rect(surf, (40,42,46), list_rect, border_radius=6)
        pg.draw.rect(surf, HL, list_rect, width=2, border_radius=6)
        start = self.scroll; end = min(len(self.options), start + self.max_show)
        for idx, opt_i in enumerate(range(start, end)):
            r = pg.Rect(list_rect.x, list_rect.y + idx*self.item_h, list_rect.w, self.item_h)
            if r.collidepoint(pg.mouse.get_pos()): pg.draw.rect(surf, (55,57,61), r)
            label = self.options[opt_i][1]
            surf.blit(font.render(label, True, FG), (r.x+8, r.y+4))
    def handle(self, ev):
        # returns True if the event was consumed
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos):
                self.open = not self.open; return True
            if self.open:
                # clicks priority while open
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
        shown = self.text if self.text else self.placeholder; color = FG if self.text else MUTED
        surf.blit(font.render(shown, True, color), (self.rect.x+8, self.rect.y+6))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1: self.focus = self.rect.collidepoint(ev.pos); return self.focus
        if self.focus and ev.type == pg.KEYDOWN:
            if ev.key == pg.K_BACKSPACE: self.text = self.text[:-1]
            elif ev.key == pg.K_RETURN: self.focus = False
            else:
                if ev.unicode and ev.unicode.isprintable(): self.text += ev.unicode
            return True
        return False

class Editor:
    def __init__(self, w=40, h=24):
        self.grid_w = w; self.grid_h = h
        self.scene = {"name":"untitled","w":w,"h":h,"tiles":{}, "links":[]}
        self.sel = None; self.message = ""
        self.npcs, self.enemies, self.items, self.world = load_catalogs()

        pg.init(); pg.display.set_caption("RPGenesis Editor — Multi")
        self.screen = pg.display.set_mode((WIN_W, WIN_H))
        self.font = pg.font.SysFont(None, 18); self.small = pg.font.SysFont(None, 14)

        # grid placement
        self.grid_rect = pg.Rect(GRID_MARGIN, GRID_MARGIN, WIN_W-PANEL_W-2*GRID_MARGIN, WIN_H-2*GRID_MARGIN)
        self.tile_size = max(16, min(28, min(self.grid_rect.w//w, self.grid_rect.h//h)))

        rp_x = WIN_W-PANEL_W+16; y = 16

        # dropdown data
        npc_opts   = [(n.get("id", n.get("name","")), n.get("name","?")) for n in self.npcs] or [("", "(no NPCs)")]
        enemy_opts = [(n.get("id", n.get("name","")), n.get("name","?")) for n in self.enemies] or [("", "(no Enemies)")]
        item_opts  = [(i.get("id", i.get("name","")), i.get("name","?")) for i in self.items] or [("", "(no Items)")]

        self.dd_npc = DropDown((rp_x, y, 240, 30), "NPC", npc_opts, on_change=lambda _:(self.add_npc() if self.sel else None))
        self.btn_add_npc = Button((rp_x+250, y, 60,30), "Add", self.add_npc)
        self.btn_rem_npc = Button((rp_x+315, y, 75,30), "Remove", self.remove_npc)
        self.btn_clr_npc = Button((rp_x+395, y, 70,30), "Clear", self.clear_npcs); y += 38

        self.dd_enemy = DropDown((rp_x, y, 240, 30), "Enemy", enemy_opts, on_change=lambda _:(self.add_enemy() if self.sel else None))
        self.btn_add_enemy = Button((rp_x+250, y, 60,30), "Add", self.add_enemy)
        self.btn_rem_enemy = Button((rp_x+315, y, 75,30), "Remove", self.remove_enemy)
        self.btn_clr_enemy = Button((rp_x+395, y, 70,30), "Clear", self.clear_enemies); y += 38

        self.dd_item = DropDown((rp_x, y, 240, 30), "Item", item_opts, on_change=lambda _:(self.add_item() if self.sel else None))
        self.btn_add_item = Button((rp_x+250, y, 60,30), "Add", self.add_item)
        self.btn_rem_item = Button((rp_x+315, y, 75,30), "Remove", self.remove_item)
        self.btn_clr_item = Button((rp_x+395, y, 70,30), "Clear", self.clear_items); y += 38

        self.inp_entry = TextInput((rp_x, y, 240, 30), "Entry name (e.g., east_gate)")
        self.btn_toggle_entry = Button((rp_x+250, y, 215,30), "Toggle Entry", self.toggle_entry); y += 38

        # link target
        link_opts = []
        for nm in sorted((self.world.get("maps") or {}).keys()): link_opts.append((f"map:{nm}", f"Map→{nm}"))
        for nm in sorted((self.world.get("dungeons") or {}).keys()): link_opts.append((f"dungeon:{nm}", f"Dungeon→{nm}"))
        if not link_opts: link_opts = [("", "(no scenes)")]

        self.dd_link = DropDown((rp_x, y, 240, 30), "Link target", link_opts, on_change=lambda _:(self.set_link() if self.sel else None))
        self.btn_set_link = Button((rp_x+250, y, 100,30), "Set Link", self.set_link)
        self.btn_clr_link = Button((rp_x+355, y, 110,30), "Clear Link", self.clear_link); y += 38

        self.inp_target_entry = TextInput((rp_x, y, 240, 30), "Target entry (optional)"); y += 38

        self.btn_save = Button((rp_x, y, 120, 34), "Save", self.save_file)
        self.btn_load = Button((rp_x+130, y, 120, 34), "Load", self.load_file)
        self.btn_new  = Button((rp_x+260, y, 120, 34), "New Scene", self.new_scene)

    # --- tile helpers & migration ---
    def _key(self, x, y): return f"{x},{y}"
    def _td(self, x, y):
        td = self.scene.setdefault("tiles", {}).setdefault(self._key(x,y), {})
        # migrate legacy single fields to lists (idempotent)
        if "npc" in td and "npcs" not in td:
            td["npcs"] = [td.pop("npc")]
        if "enemy" in td and "enemies" not in td:
            td["enemies"] = [td.pop("enemy")]
        if "item" in td and "items" not in td:
            td["items"] = [td.pop("item")]
        td.setdefault("npcs", []); td.setdefault("enemies", []); td.setdefault("items", [])
        return td

    # --- add/remove/clear for multiples ---
    def add_npc(self):
        if not self.sel: return
        v = self.dd_npc.value; 
        if not v: return
        td = self._td(*self.sel)
        if v not in td["npcs"]: td["npcs"].append(v)
    def remove_npc(self):
        if not self.sel: return
        v = self.dd_npc.value; td = self._td(*self.sel)
        if v in td["npcs"]: td["npcs"].remove(v)
    def clear_npcs(self):
        if not self.sel: return
        self._td(*self.sel)["npcs"].clear()

    def add_enemy(self):
        if not self.sel: return
        v = self.dd_enemy.value; 
        if not v: return
        td = self._td(*self.sel)
        if v not in td["enemies"]: td["enemies"].append(v)
    def remove_enemy(self):
        if not self.sel: return
        v = self.dd_enemy.value; td = self._td(*self.sel)
        if v in td["enemies"]: td["enemies"].remove(v)
    def clear_enemies(self):
        if not self.sel: return
        self._td(*self.sel)["enemies"].clear()

    def add_item(self):
        if not self.sel: return
        v = self.dd_item.value; 
        if not v: return
        td = self._td(*self.sel)
        if v not in td["items"]: td["items"].append(v)
    def remove_item(self):
        if not self.sel: return
        v = self.dd_item.value; td = self._td(*self.sel)
        if v in td["items"]: td["items"].remove(v)
    def clear_items(self):
        if not self.sel: return
        self._td(*self.sel)["items"].clear()

    # --- entry & links ---
    def toggle_entry(self):
        if not self.sel: return
        name = self.inp_entry.text.strip()
        td = self._td(*self.sel)
        if "entry" in td: td.pop("entry", None)
        else:
            if name: td["entry"] = name

    def set_link(self):
        if not self.sel: return
        val = self.dd_link.value
        if not val or ":" not in val: return
        kind, name = val.split(":",1)
        x,y = self.sel
        self.scene["links"] = [ln for ln in self.scene.get("links", []) if ln.get("at") != [x,y]]
        L = {"at":[x,y], "to":name, "kind":kind}
        te = self.inp_target_entry.text.strip()
        if te: L["target_entry"] = te
        self.scene.setdefault("links", []).append(L)
    def clear_link(self):
        if not self.sel: return
        x,y = self.sel
        self.scene["links"] = [ln for ln in self.scene.get("links", []) if ln.get("at") != [x,y]]

    # --- file ops ---
    def save_file(self):
        os.makedirs("data", exist_ok=True)
        with open("data/scene_out.json","w",encoding="utf-8") as f:
            json.dump(self.scene, f, indent=2)
    def load_file(self):
        try:
            with open("data/scene_out.json","r",encoding="utf-8") as f:
                self.scene = json.load(f)
        except Exception as e:
            self.scene = {"name":"untitled","w":self.grid_w,"h":self.grid_h,"tiles":{},"links":[]}

    def new_scene(self):
        self.scene = {"name":"untitled","w":self.grid_w,"h":self.grid_h,"tiles":{},"links":[]}
        self.sel = None

    # --- draw ---
    def draw(self):
        s = self.screen; s.fill(BG)
        # grid
        gx,gy,gw,gh = self.grid_rect; ts = self.tile_size
        for yy in range(self.scene.get("h", self.grid_h)):
            for xx in range(self.scene.get("w", self.grid_w)):
                r = pg.Rect(gx + xx*ts, gy + yy*ts, ts-1, ts-1)
                pg.draw.rect(s, (36,37,40), r)
        # contents markers (with counts)
        for key, td in self.scene.get("tiles", {}).items():
            xx,yy = map(int, key.split(","))
            td = self._td(xx,yy)  # ensures migration
            r = pg.Rect(gx + xx*ts, gy + yy*ts, ts-1, ts-1)
            tags = []
            if td["npcs"]: tags.append(f"N{len(td['npcs']) if len(td['npcs'])>1 else ''}")
            if td["enemies"]: tags.append(f"X{len(td['enemies']) if len(td['enemies'])>1 else ''}")
            if td["items"]: tags.append(f"${len(td['items']) if len(td['items'])>1 else ''}")
            if "entry" in td: tags.append("E")
            lab = self.small.render(" ".join(tags), True, ACCENT)
            s.blit(lab, (r.x+3, r.y+2))
        # links outline
        for ln in self.scene.get("links", []):
            x,y = ln.get("at", [0,0])
            r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1)
            pg.draw.rect(s, (110,180,120), r, 2)
        # selection
        if self.sel:
            x,y = self.sel
            r = pg.Rect(gx + x*ts, gy + y*ts, ts-1, ts-1)
            pg.draw.rect(s, ACCENT, r, 3)

        # right panel
        rp = pg.Rect(WIN_W-PANEL_W, 0, PANEL_W, WIN_H)
        pg.draw.rect(s, (30,31,35), rp)

        # --- draw base of widgets (not popups) ---
        for w in [
            self.dd_npc, self.btn_add_npc, self.btn_rem_npc, self.btn_clr_npc,
            self.dd_enemy, self.btn_add_enemy, self.btn_rem_enemy, self.btn_clr_enemy,
            self.dd_item, self.btn_add_item, self.btn_rem_item, self.btn_clr_item,
            self.inp_entry, self.btn_toggle_entry,
            self.dd_link, self.btn_set_link, self.btn_clr_link,
            self.inp_target_entry, self.btn_save, self.btn_load, self.btn_new
        ]:
            if isinstance(w, DropDown): w.draw_base(s, self.font)
            elif isinstance(w, TextInput): w.draw(s, self.font)
            else: w.draw(s, self.font)

        # Tile contents readout
        y0 = 420; x0 = WIN_W-PANEL_W+16
        s.blit(self.font.render("Selected tile:", True, FG), (x0, y0))
        if self.sel:
            x,y = self.sel; td = self._td(x,y)
            link = None
            for ln in self.scene.get("links", []):
                if ln.get("at")==[x,y]: link = ln; break
            lines = [
                f"({x},{y})",
                f"NPCs: {', '.join(td['npcs']) if td['npcs'] else '—'}",
                f"Enemies: {', '.join(td['enemies']) if td['enemies'] else '—'}",
                f"Items: {', '.join(td['items']) if td['items'] else '—'}",
                f"Entry: {td.get('entry','—')}",
            ]
            if link:
                link_text = f"{link['kind']}:{link['to']}"
                if link.get('target_entry'):
                    link_text += f" @{link['target_entry']}"
            else:
                link_text = "—"
            lines.append(f"Link: {link_text}")
            for i,t in enumerate(lines):
                s.blit(self.small.render(t, True, FG), (x0, y0+24+18*i))
        else:
            s.blit(self.small.render("(none) — click a tile", True, MUTED), (x0, y0+24))

        # --- draw dropdown popups LAST so they're on top ---
        for dd in [self.dd_npc, self.dd_enemy, self.dd_item, self.dd_link]:
            dd.draw_popup(s, self.font)

        pg.display.flip()

    def handle(self, ev):
        # If any dropdown is open, give it first dibs on events.
        for dd in [self.dd_npc, self.dd_enemy, self.dd_item, self.dd_link]:
            if dd.open and dd.handle(ev): return

        # Otherwise, handle base clicks; dropdown bases still get a chance.
        consumed = False
        for w in [self.dd_npc, self.dd_enemy, self.dd_item, self.dd_link,
                  self.btn_add_npc, self.btn_rem_npc, self.btn_clr_npc,
                  self.btn_add_enemy, self.btn_rem_enemy, self.btn_clr_enemy,
                  self.btn_add_item, self.btn_rem_item, self.btn_clr_item,
                  self.inp_entry, self.btn_toggle_entry,
                  self.btn_set_link, self.btn_clr_link,
                  self.inp_target_entry, self.btn_save, self.btn_load, self.btn_new]:
            if hasattr(w, "handle") and w.handle(ev): consumed = True
        if consumed: return

        # Grid selection
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1 and self.grid_rect.collidepoint(ev.pos):
            gx,gy,gw,gh = self.grid_rect; ts = self.tile_size
            x = (ev.pos[0]-gx)//ts; y = (ev.pos[1]-gy)//ts
            if 0<=x<self.scene["w"] and 0<=y<self.scene["h"]:
                self.sel = (int(x), int(y))

        # Save cmd
        if ev.type == pg.KEYDOWN and ev.key == pg.K_s and (pg.key.get_mods() & pg.KMOD_CTRL):
            self.save_file()

    def run(self):
        clock = pg.time.Clock(); running = True
        while running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT: running = False
                else: self.handle(ev)
            self.draw(); clock.tick(60)

if __name__ == "__main__":
    Editor().run()
