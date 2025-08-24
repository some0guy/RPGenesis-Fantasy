#!/usr/bin/env python3
# RPGenesis Map Editor (Tile-first workflow, syntax-clean)

import pygame as pg
import json, os
from typing import List, Tuple

WIN_W, WIN_H = 1200, 800
PANEL_W = 480
GRID_MARGIN = 12

BG = (24,25,28)
FG = (230,230,230)
ACCENT = (160, 200, 255)
MUTED = (120, 120, 130)
HL = (60, 110, 180)

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
        self.rect = pg.Rect(rect)
        self.text = text
        self.cb = cb
    def draw(self, surf, font):
        pg.draw.rect(surf, HL, self.rect, border_radius=6, width=2)
        label = font.render(self.text, True, FG)
        surf.blit(label, label.get_rect(center=self.rect.center))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos):
                self.cb()

class DropDown:
    def __init__(self, rect, placeholder, options, on_change=None):
        self.rect = pg.Rect(rect)
        self.placeholder = placeholder
        self.options = list(options)
        self.open = False
        self.sel_index = -1
        self.on_change = on_change
        self.scroll = 0
        self.item_h = 26
        self.max_show = 8
    @property
    def value(self):
        if 0 <= self.sel_index < len(self.options):
            return self.options[self.sel_index][0]
        return ""
    def draw(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        text = self.placeholder if self.sel_index<0 else self.options[self.sel_index][1]
        surf.blit(font.render(text, True, FG), (self.rect.x+8, self.rect.y+5))
        if self.open:
            list_rect = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, self.item_h*min(self.max_show, len(self.options)))
            pg.draw.rect(surf, (40,42,46), list_rect, border_radius=6)
            for idx,opt_i in enumerate(range(self.scroll, min(len(self.options), self.scroll+self.max_show))):
                r = pg.Rect(self.rect.x, self.rect.bottom + idx*self.item_h, self.rect.w, self.item_h)
                label = self.options[opt_i][1]
                surf.blit(font.render(label, True, FG), (r.x+8, r.y+4))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos):
                self.open = not self.open
                return
            if self.open:
                list_rect = pg.Rect(self.rect.x, self.rect.bottom, self.rect.w, self.item_h*min(self.max_show, len(self.options)))
                if list_rect.collidepoint(ev.pos):
                    rel_y = ev.pos[1] - list_rect.y
                    idx = rel_y // self.item_h
                    opt_i = self.scroll + int(idx)
                    if 0 <= opt_i < len(self.options):
                        self.sel_index = opt_i
                        self.open = False
                        if self.on_change:
                            self.on_change(self.options[opt_i][0])
                else:
                    self.open = False

class TextInput:
    def __init__(self, rect, placeholder=""):
        self.rect = pg.Rect(rect)
        self.text = ""
        self.placeholder = placeholder
        self.focus = False
    def draw(self, surf, font):
        pg.draw.rect(surf, (40,42,46), self.rect, border_radius=6)
        pg.draw.rect(surf, HL, self.rect, width=2, border_radius=6)
        shown = self.text if self.text else self.placeholder
        color = FG if self.text else MUTED
        surf.blit(font.render(shown, True, color), (self.rect.x+8, self.rect.y+6))
    def handle(self, ev):
        if ev.type == pg.MOUSEBUTTONDOWN and ev.button == 1:
            self.focus = self.rect.collidepoint(ev.pos)
        if self.focus and ev.type == pg.KEYDOWN:
            if ev.key == pg.K_BACKSPACE:
                self.text = self.text[:-1]
            elif ev.key == pg.K_RETURN:
                self.focus = False
            else:
                if ev.unicode and ev.unicode.isprintable():
                    self.text += ev.unicode

class Editor:
    def __init__(self, w=40, h=24):
        self.grid_w = w
        self.grid_h = h
        self.scene = {"name":"untitled","w":w,"h":h,"tiles":{}, "links":[]}
        self.sel = None

        self.npcs, self.enemies, self.items, self.world = load_catalogs()

        pg.init()
        self.screen = pg.display.set_mode((WIN_W, WIN_H))
        self.font = pg.font.SysFont(None, 18)
        self.small = pg.font.SysFont(None, 14)

        # right panel setup
        rp_x = WIN_W - PANEL_W + 16
        y = 20

        npc_opts   = [(n.get("id",""), n.get("name","?")) for n in self.npcs] or [("", "(no NPCs)")]
        enemy_opts = [(n.get("id",""), n.get("name","?")) for n in self.enemies] or [("", "(no Enemies)")]
        item_opts  = [(i.get("id",""), i.get("name","?")) for i in self.items] or [("", "(no Items)")]

        link_opts = []
        for nm in sorted((self.world.get("maps") or {}).keys()):
            link_opts.append((f"map:{nm}", f"Map→{nm}"))
        for nm in sorted((self.world.get("dungeons") or {}).keys()):
            link_opts.append((f"dungeon:{nm}", f"Dungeon→{nm}"))
        if not link_opts: link_opts=[("", "(no scenes)")]

        self.dd_npc = DropDown((rp_x, y, 200, 30), "NPC", npc_opts, on_change=lambda _:(self.set_npc() if self.sel else None))
        self.btn_set_npc = Button((rp_x+210, y, 60,30), "Set", self.set_npc)
        self.btn_clr_npc = Button((rp_x+280, y, 60,30), "Clr", self.clear_npc)
        y+=38

        self.dd_enemy = DropDown((rp_x, y, 200, 30), "Enemy", enemy_opts, on_change=lambda _:(self.set_enemy() if self.sel else None))
        self.btn_set_enemy = Button((rp_x+210, y, 60,30), "Set", self.set_enemy)
        self.btn_clr_enemy = Button((rp_x+280, y, 60,30), "Clr", self.clear_enemy)
        y+=38

        self.dd_item = DropDown((rp_x, y, 200, 30), "Item", item_opts, on_change=lambda _:(self.set_item() if self.sel else None))
        self.btn_set_item = Button((rp_x+210, y, 60,30), "Set", self.set_item)
        self.btn_clr_item = Button((rp_x+280, y, 60,30), "Clr", self.clear_item)
        y+=38

        self.dd_link = DropDown((rp_x, y, 200, 30), "Link", link_opts, on_change=lambda _:(self.set_link() if self.sel else None))
        self.btn_set_link = Button((rp_x+210, y, 60,30), "Set", self.set_link)
        self.btn_clr_link = Button((rp_x+280, y, 60,30), "Clr", self.clear_link)
        y+=38

        self.inp_entry = TextInput((rp_x, y, 200, 30), "Entry name")
        self.btn_toggle_entry = Button((rp_x+210, y, 130,30), "Toggle Entry", self.toggle_entry)
        y+=38

        self.inp_target_entry = TextInput((rp_x, y, 200, 30), "Target entry (optional)")
        y+=38

        self.btn_save = Button((rp_x, y, 100, 32), "Save", self.save_file)
        self.btn_load = Button((rp_x+110, y, 100, 32), "Load", self.load_file)
        self.btn_new  = Button((rp_x+220, y, 100, 32), "New", self.new_scene)

        self.message = ""

    def _key(self,x,y): return f"{x},{y}"
    def _td(self,x,y): return self.scene.setdefault("tiles",{}).setdefault(self._key(x,y),{})

    def set_npc(self):
        if not self.sel: return
        val=self.dd_npc.value
        if not val: return
        self._td(*self.sel)["npc"]=val
        self.message=f"NPC set {val}"
    def clear_npc(self):
        if not self.sel: return
        td=self.scene.get("tiles",{}).get(self._key(*self.sel))
        if td and "npc" in td: td.pop("npc")

    def set_enemy(self):
        if not self.sel: return
        val=self.dd_enemy.value
        if not val: return
        self._td(*self.sel)["enemy"]=val
        self.message=f"Enemy set {val}"
    def clear_enemy(self):
        if not self.sel: return
        td=self.scene.get("tiles",{}).get(self._key(*self.sel))
        if td and "enemy" in td: td.pop("enemy")

    def set_item(self):
        if not self.sel: return
        val=self.dd_item.value
        if not val: return
        self._td(*self.sel)["item"]=val
        self.message=f"Item set {val}"
    def clear_item(self):
        if not self.sel: return
        td=self.scene.get("tiles",{}).get(self._key(*self.sel))
        if td and "item" in td: td.pop("item")

    def set_link(self):
        if not self.sel: return
        val=self.dd_link.value
        if not val or ":" not in val: return
        kind,name=val.split(":",1)
        self.scene["links"]=[ln for ln in self.scene.get("links",[]) if ln.get("at")!=list(self.sel)]
        L={"at":list(self.sel),"to":name,"kind":kind}
        te=self.inp_target_entry.text.strip()
        if te: L["target_entry"]=te
        self.scene["links"].append(L)
        self.message=f"Link set {kind}:{name}"
    def clear_link(self):
        if not self.sel: return
        self.scene["links"]=[ln for ln in self.scene.get("links",[]) if ln.get("at")!=list(self.sel)]

    def toggle_entry(self):
        if not self.sel: return
        td=self._td(*self.sel)
        if "entry" in td:
            td.pop("entry")
        else:
            nm=self.inp_entry.text.strip()
            if nm: td["entry"]=nm

    def save_file(self):
        os.makedirs("data",exist_ok=True)
        with open("data/scene_out.json","w",encoding="utf-8") as f:
            json.dump(self.scene,f,indent=2)
        self.message="Saved."
    def load_file(self):
        try:
            with open("data/scene_out.json","r",encoding="utf-8") as f:
                self.scene=json.load(f)
            self.message="Loaded."
        except Exception as e:
            self.message=f"Load fail {e}"
    def new_scene(self):
        self.scene={"name":"untitled","w":self.grid_w,"h":self.grid_h,"tiles":{},"links":[]}

    def draw(self):
        s=self.screen
        s.fill(BG)
        ts=20
        gx,gy=20,20
        for y in range(self.scene.get("h",self.grid_h)):
            for x in range(self.scene.get("w",self.grid_w)):
                r=pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
                pg.draw.rect(s,(36,37,40),r)
        for key,td in self.scene.get("tiles",{}).items():
            x,y=map(int,key.split(","))
            r=pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
            txt="".join([c for c in ["N" if "npc" in td else "",
                                      "X" if "enemy" in td else "",
                                      "$" if "item" in td else "",
                                      "E" if "entry" in td else ""]])
            s.blit(self.small.render(txt,True,ACCENT),(r.x+2,r.y+2))
        for ln in self.scene.get("links",[]):
            x,y=ln["at"]
            r=pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
            pg.draw.rect(s,(120,180,120),r,2)
        if self.sel:
            x,y=self.sel
            r=pg.Rect(gx+x*ts, gy+y*ts, ts-1, ts-1)
            pg.draw.rect(s,ACCENT,r,2)
        # draw panel controls
        self.dd_npc.draw(s,self.font); self.btn_set_npc.draw(s,self.font); self.btn_clr_npc.draw(s,self.font)
        self.dd_enemy.draw(s,self.font); self.btn_set_enemy.draw(s,self.font); self.btn_clr_enemy.draw(s,self.font)
        self.dd_item.draw(s,self.font); self.btn_set_item.draw(s,self.font); self.btn_clr_item.draw(s,self.font)
        self.dd_link.draw(s,self.font); self.btn_set_link.draw(s,self.font); self.btn_clr_link.draw(s,self.font)
        self.inp_entry.draw(s,self.font); self.btn_toggle_entry.draw(s,self.font)
        self.inp_target_entry.draw(s,self.font)
        self.btn_save.draw(s,self.font); self.btn_load.draw(s,self.font); self.btn_new.draw(s,self.font)
        if self.message:
            s.blit(self.small.render(self.message,True,ACCENT),(20,WIN_H-30))
        pg.display.flip()

    def handle(self,ev):
        self.dd_npc.handle(ev); self.btn_set_npc.handle(ev); self.btn_clr_npc.handle(ev)
        self.dd_enemy.handle(ev); self.btn_set_enemy.handle(ev); self.btn_clr_enemy.handle(ev)
        self.dd_item.handle(ev); self.btn_set_item.handle(ev); self.btn_clr_item.handle(ev)
        self.dd_link.handle(ev); self.btn_set_link.handle(ev); self.btn_clr_link.handle(ev)
        self.inp_entry.handle(ev); self.btn_toggle_entry.handle(ev)
        self.inp_target_entry.handle(ev); self.btn_save.handle(ev); self.btn_load.handle(ev); self.btn_new.handle(ev)
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1:
            gx,gy=20,20; ts=20
            x=(ev.pos[0]-gx)//ts; y=(ev.pos[1]-gy)//ts
            if 0<=x<self.scene["w"] and 0<=y<self.scene["h"]: self.sel=(x,y)

    def run(self):
        clock=pg.time.Clock(); running=True
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: running=False
                else: self.handle(ev)
            self.draw(); clock.tick(60)

if __name__=="__main__":
    Editor().run()
