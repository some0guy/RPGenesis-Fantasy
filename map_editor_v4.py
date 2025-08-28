
import os
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pygame

# -------------------- Paths & constants --------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
MAP_DIR  = os.path.join(DATA_DIR, "maps")
NPC_DIR  = os.path.join(DATA_DIR, "NPCs")
ITEM_DIR = os.path.join(DATA_DIR, "items")
MANIFEST = os.path.join(DATA_DIR, "maps.json")

os.makedirs(MAP_DIR, exist_ok=True)

NPC_SUBCATS   = ["allies", "enemies", "monsters", "animals", "citizens"]
ITEM_SUBCATS  = ["accessories", "armour", "clothing", "materials", "quest_items", "trinkets", "weapons"]

TILE_SIZE_DEFAULT = 32
GRID_W_DEFAULT, GRID_H_DEFAULT = 40, 30
TILE_MIN, TILE_MAX = 16, 96

ICON_NPC  = "👤"
ICON_ITEM = "🎒"
ICON_LINK = "🔗"

# Colors
PAPER_BG       = (23,24,28)
CANVAS_BG      = (27,29,35)
PANEL_BG       = (30,33,42)
PANEL_BG_DARK  = (26,28,34)
TEXT_MAIN      = (232,234,237)
TEXT_DIM       = (180,184,190)
ACCENT         = (122,162,247)
GRID_LINE      = (61,68,80)
LIGHT_WALKABLE = (46,51,64)
DARK_WALKABLE  = (42,47,59)
IMPASSABLE     = (74,79,89)
BTN_BG         = (47,52,66)
BTN_HOVER      = (73,80,99)
INPUT_BG       = (18,19,23)

# -------------------- JSON helpers --------------------
def _as_list(obj: Any) -> List[Dict[str, Any]]:
    if obj is None: return []
    if isinstance(obj, list): return obj
    if isinstance(obj, dict):
        for k in ("npcs","items","entries","data","list","records"):
            v = obj.get(k)
            if isinstance(v, list):
                return v
    return []

def read_json_any(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"[editor] JSON error in {path}: {e}")
        return default
    except Exception as e:
        print(f"[editor] Unexpected error reading {path}: {e}")
        return default

def read_json_list(path: str) -> List[Dict[str, Any]]:
    return _as_list(read_json_any(path, default=[]))

def write_json(path: str, obj: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# -------------------- Data models --------------------
@dataclass
class TileData:
    walkable: bool = False  # 1) default IMPASSABLE
    npcs: List[Dict[str, Any]] = field(default_factory=list)
    items: List[Dict[str, Any]] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class MapData:
    name: str = "Untitled"
    description: str = ""
    width: int = GRID_W_DEFAULT
    height: int = GRID_H_DEFAULT
    tiles: List[List[TileData]] = field(default_factory=list)

    @staticmethod
    def new(name: str, description: str, w: int, h: int) -> "MapData":
        # all tiles start IMPASSABLE
        tiles = [[TileData() for _ in range(w)] for __ in range(h)]
        return MapData(name=name, description=description, width=w, height=h, tiles=tiles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "tiles": [[{
                "walkable": t.walkable,
                "npcs": t.npcs,
                "items": t.items,
                "links": t.links,
            } for t in row] for row in self.tiles],
        }

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> "MapData":
        name = obj.get("name", "Untitled")
        desc = obj.get("description", "")
        w = int(obj.get("width", GRID_W_DEFAULT))
        h = int(obj.get("height", GRID_H_DEFAULT))
        raw_tiles = obj.get("tiles") or []
        tiles: List[List[TileData]] = []
        for y in range(h):
            row: List[TileData] = []
            for x in range(w):
                cell = (raw_tiles[y][x] if y < len(raw_tiles) and x < len(raw_tiles[y]) else {}) or {}
                row.append(TileData(
                    walkable=bool(cell.get("walkable", False)),  # default False if absent
                    npcs=list(cell.get("npcs", [])),
                    items=list(cell.get("items", [])),
                    links=list(cell.get("links", [])),
                ))
            tiles.append(row)
        return MapData(name=name, description=desc, width=w, height=h, tiles=tiles)

# -------------------- Pygame UI --------------------
pygame.init()
pygame.display.set_caption("RPGenesis – Map Editor (Pygame)")
FONT = pygame.font.SysFont("segoeui", 16)
FONT_BOLD = pygame.font.SysFont("segoeui", 18, bold=True)

def draw_text(surface, text, pos, color=TEXT_MAIN, font=FONT):
    surface.blit(font.render(text, True, color), pos)

# ---------- UI widgets ----------
class Button:
    def __init__(self, rect, text, on_click):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.on_click = on_click
        self.hover = False
    def handle(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.on_click()
    def draw(self, surf):
        pygame.draw.rect(surf, BTN_HOVER if self.hover else BTN_BG, self.rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=8)
        txt = FONT.render(self.text, True, TEXT_MAIN)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

class TextInput:
    def __init__(self, rect, text=""):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.active = False
        self.cursor_timer = 0
        self.cursor_show = True
    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active = self.rect.collidepoint(event.pos)
        if self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                self.active = False
            else:
                if event.unicode and event.key != pygame.K_ESCAPE:
                    self.text += event.unicode
    def update(self, dt):
        self.cursor_timer += dt
        if self.cursor_timer >= 500:
            self.cursor_timer = 0
            self.cursor_show = not self.cursor_show
    def draw(self, surf):
        pygame.draw.rect(surf, INPUT_BG, self.rect, border_radius=6)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=6)
        txt = FONT.render(self.text, True, TEXT_MAIN)
        surf.blit(txt, (self.rect.x+8, self.rect.y+6))
        if self.active and self.cursor_show:
            cx = self.rect.x + 8 + txt.get_width() + 1
            cy = self.rect.y + 6
            pygame.draw.line(surf, TEXT_MAIN, (cx, cy), (cx, cy+txt.get_height()), 1)

class TextArea:
    """Simple multiline text area with wrapping and wheel scrolling."""
    def __init__(self, rect, text=""):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.active = False
        self.scroll = 0
        self.cursor_timer = 0
        self.cursor_show = True
        self.line_spacing = 4

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(0, self.scroll - event.y * 20)
        elif self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                self.text += "\n"
            elif event.key == pygame.K_TAB:
                self.text += "  "
            else:
                if event.unicode and event.key != pygame.K_ESCAPE:
                    self.text += event.unicode

    def update(self, dt):
        self.cursor_timer += dt
        if self.cursor_timer >= 500:
            self.cursor_timer = 0
            self.cursor_show = not self.cursor_show

    def _wrap(self, text, width_px):
        words = text.split(" ")
        lines = []
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            if FONT.size(test)[0] <= width_px or not line:
                line = test
            else:
                lines.append(line)
                line = w
        lines.append(line)
        out = []
        for raw in "\n".join(lines).split("\n"):
            # hard-wrap per line
            cur = ""
            for ch in raw:
                if FONT.size(cur + ch)[0] <= width_px or not cur:
                    cur += ch
                else:
                    out.append(cur)
                    cur = ch
            out.append(cur)
        return out

    def draw(self, surf):
        pygame.draw.rect(surf, INPUT_BG, self.rect, border_radius=6)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=6)
        clip = surf.get_clip()
        surf.set_clip(self.rect)
        inner_w = self.rect.w - 12
        lines = self._wrap(self.text, inner_w)
        y = self.rect.y + 6 - self.scroll
        for ln in lines:
            surf.blit(FONT.render(ln, True, TEXT_MAIN), (self.rect.x+6, y))
            y += FONT.get_height() + self.line_spacing
        # (optional) cursor could be added; omitted for simplicity
        surf.set_clip(clip)

class Dropdown:
    def __init__(self, rect, options, value=None, on_change=None):
        self.rect = pygame.Rect(rect)
        self.options = options[:]
        self.value = value if value in options else (options[0] if options else "")
        self.on_change = on_change
        self.opened = False
        self.hover = False
        self.popup_rects: List[pygame.Rect] = []
        self.popup_upwards = False
    def handle(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.opened = not self.opened
            elif self.opened:
                for i, r in enumerate(self.popup_rects):
                    if r.collidepoint(event.pos):
                        self.value = self.options[i]
                        if self.on_change:
                            self.on_change(self.value)
                        break
                self.opened = False
    def draw_base(self, surf):
        pygame.draw.rect(surf, BTN_HOVER if self.hover else BTN_BG, self.rect, border_radius=6)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=6)
        draw_text(surf, self.value, (self.rect.x+8, self.rect.y+6))
        self.popup_rects.clear()
        if not self.opened: return
        screen_h = surf.get_height()
        needed_h = self.rect.h * len(self.options)
        below_space = screen_h - self.rect.bottom
        self.popup_upwards = below_space < needed_h
        y = self.rect.top - self.rect.h if self.popup_upwards else self.rect.bottom
        for _ in self.options:
            self.popup_rects.append(pygame.Rect(self.rect.x, y, self.rect.w, self.rect.h))
            y += -self.rect.h if self.popup_upwards else self.rect.h
    def draw_popup(self, surf):
        if not self.opened: return
        for r, opt in zip(self.popup_rects, self.options):
            pygame.draw.rect(surf, PANEL_BG, r)
            pygame.draw.rect(surf, GRID_LINE, r, 1)
            draw_text(surf, opt, (r.x+8, r.y+6))

class ListBox:
    def __init__(self, rect, items=None):
        self.rect = pygame.Rect(rect)
        self.items = items[:] if items else []
        self.scroll = 0
        self.selected = -1
        self.hover_index = -1
        self.item_height = 24
    def set_items(self, items):
        self.items = items[:]
        self.scroll = 0
        self.selected = -1
    def handle(self, event):
        if event.type == pygame.MOUSEMOTION:
            if self.rect.collidepoint(event.pos):
                idx = (event.pos[1] - self.rect.y + self.scroll) // self.item_height
                self.hover_index = idx if 0 <= idx < len(self.items) else -1
            else:
                self.hover_index = -1
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                idx = (event.pos[1] - self.rect.y + self.scroll) // self.item_height
                if 0 <= idx < len(self.items):
                    self.selected = idx
    def get_selected(self):
        if 0 <= self.selected < len(self.items):
            return self.items[self.selected]
        return None
    def draw(self, surf):
        pygame.draw.rect(surf, PANEL_BG_DARK, self.rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=8)
        clip = surf.get_clip()
        surf.set_clip(self.rect)
        y = self.rect.y - self.scroll
        for i, text in enumerate(self.items):
            r = pygame.Rect(self.rect.x+4, y, self.rect.w-8, self.item_height)
            bg = BTN_HOVER if i == self.hover_index or i == self.selected else PANEL_BG
            pygame.draw.rect(surf, bg, r, border_radius=4)
            draw_text(surf, text, (r.x+6, r.y+4))
            y += self.item_height
        surf.set_clip(clip)

# -------------------- StartScreen --------------------
class StartScreen:
    def __init__(self, app):
        self.app = app
        self.btn_refresh = Button((60, 120, 140, 32), "Refresh", self.refresh)
        self.btn_open   = Button((210, 120, 160, 32), "Open Selected", self.open_selected)
        # 3) Simplify: remove name/desc inputs; a single Create New Map
        self.btn_create = Button((60, 410, 180, 36), "Create New Map", self.create_map)
        self.maps_list = ListBox((60, 160, 520, 230))
        self.refresh()

    def refresh(self):
        obj = read_json_any(MANIFEST, {"maps": []})
        self.maps = obj.get("maps", [])
        items = [f"{m.get('name','(unnamed)')} — {m.get('file','?')}" for m in self.maps]
        self.maps_list.set_items(items)

    def draw(self, surf):
        surf.fill(PAPER_BG)
        draw_text(surf, "RPGenesis – Maps", (60, 40), TEXT_MAIN, FONT_BOLD)
        draw_text(surf, "Select a map or create a new one.", (60, 70), TEXT_DIM)
        self.btn_refresh.draw(surf); self.btn_open.draw(surf)
        self.maps_list.draw(surf)
        # create button
        pygame.draw.rect(surf, PANEL_BG, (60, 400, 520, 70), border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, (60, 400, 520, 70), 1, border_radius=8)
        self.btn_create.draw(surf)

    def handle(self, event):
        self.btn_refresh.handle(event)
        self.btn_open.handle(event)
        self.maps_list.handle(event)
        self.btn_create.handle(event)

    def update(self, dt): pass

    def open_selected(self):
        sel = self.maps_list.get_selected()
        if not sel: return
        idx = self.maps_list.selected
        entry = self.maps[idx]
        file_name = entry.get("file")
        if not file_name: return
        path = os.path.join(MAP_DIR, file_name)
        obj = read_json_any(path, None)
        if obj is None: return
        self.app.goto_editor(MapData.from_dict(obj))

    def create_map(self):
        # default Untitled map, all IMPASSABLE, default size
        md = MapData.new("Untitled", "", GRID_W_DEFAULT, GRID_H_DEFAULT)
        self.app.goto_editor(md)

# -------------------- EditorScreen --------------------
class EditorScreen:
    def __init__(self, app, mapdata: MapData):
        self.app = app
        self.map = mapdata
        self.tile_size = TILE_SIZE_DEFAULT
        self.offset_x = 60
        self.offset_y = 60
        self.selected: Optional[Tuple[int,int]] = None
        self.link_arm: Optional[Tuple[str, str]] = None  # (target_map, entry_id)

        # top bar
        self.name_inp = TextInput((80, 12, 240, 28), self.map.name)
        self.btn_save = Button((340, 12, 100, 28), "Save", self.save)
        self.btn_back = Button((450, 12, 120, 28), "Back to Menu", self.app.goto_start)

        # 2) Resize controls
        self.resize_w_inp = TextInput((600, 12, 60, 28), str(self.map.width))
        self.resize_h_inp = TextInput((670, 12, 60, 28), str(self.map.height))
        self.btn_resize   = Button((740, 12, 120, 28), "Apply Size", self.apply_resize)

        # right panel
        self.category = "NPCs"
        self.btn_cat_npcs  = Button((920, 60, 140, 30), "NPCs",  lambda: self._switch_category("NPCs"))
        self.btn_cat_items = Button((920, 95, 140, 30), "Items", lambda: self._switch_category("Items"))
        self.btn_cat_links = Button((920, 130, 140, 30), "Links", lambda: self._switch_category("Links"))

        # NPCs / Items
        self.dd_npc_sub  = Dropdown((920, 180, 140, 26), NPC_SUBCATS,  value=NPC_SUBCATS[0], on_change=lambda v: self._reload_npcs())
        self.dd_item_sub = Dropdown((920, 180, 140, 26), ITEM_SUBCATS, value=ITEM_SUBCATS[0], on_change=lambda v: self._reload_items())
        self.list_box = ListBox((920, 214, 340, 220))
        self.btn_add_to_tile      = Button((920, 440, 160, 30), "Add to Selected", self.add_selected_to_tile)
        self.btn_toggle_walkable  = Button((1090, 440, 170, 30), "Toggle Walkable", self.toggle_walkable)

        # Links
        self.maps_available = [f for f in os.listdir(MAP_DIR) if f.lower().endswith(".json")]
        link_default = self.maps_available[0] if self.maps_available else ""
        self.dd_link_map = Dropdown((920, 180, 220, 26), self.maps_available, value=link_default, on_change=None)
        self.link_entry_inp = TextInput((1150, 180, 110, 26), "")
        self.btn_arm_link   = Button((920, 214, 180, 30), "Arm Link (click tile)", self.arm_link)

        # 4) Big description editor
        self.desc_area = TextArea((920, 480, 340, 180), self.map.description)

        # inspector (smaller, above description or we can fold in later)
        self.inspector_rect = pygame.Rect(920, 666, 340, 54)

        # canvas panning
        self.panning = False
        self.pan_start = (0,0)

        # preload lists
        self._reload_npcs()
        self._reload_items()

    # ---------- helpers ----------
    def _switch_category(self, label: str):
        self.category = label

    def _reload_npcs(self):
        sub = self.dd_npc_sub.value
        entries = read_json_list(os.path.join(NPC_DIR, f"{sub}.json"))
        self.npc_entries = entries
        self.list_box.set_items([self._display_label(e) for e in entries])

    def _reload_items(self):
        sub = self.dd_item_sub.value
        entries = read_json_list(os.path.join(ITEM_DIR, f"{sub}.json"))
        self.item_entries = entries
        self.list_box.set_items([self._display_label(e) for e in entries])

    def _display_label(self, e: Dict[str, Any]) -> str:
        name = e.get("name") or e.get("title") or "(unnamed)"
        ident = e.get("id") or e.get("code") or e.get("uid") or ""
        return f"{name} [{ident}]" if ident else name

    # ---------- actions ----------
    def add_selected_to_tile(self):
        if not self.selected: return
        x,y = self.selected
        t = self.map.tiles[y][x]
        if self.category == "NPCs":
            idx = self.list_box.selected
            if idx < 0: return
            e = self.npc_entries[idx]
            t.npcs.append({
                "subcategory": self.dd_npc_sub.value,
                "id": e.get("id") or e.get("code") or e.get("uid") or e.get("name"),
                "name": e.get("name") or e.get("title"),
                "description": e.get("description","")
            })
        elif self.category == "Items":
            idx = self.list_box.selected
            if idx < 0: return
            e = self.item_entries[idx]
            t.items.append({
                "subcategory": self.dd_item_sub.value,
                "id": e.get("id") or e.get("code") or e.get("uid") or e.get("name"),
                "name": e.get("name") or e.get("title"),
                "description": e.get("description","")
            })

    def toggle_walkable(self):
        if not self.selected: return
        x,y = self.selected
        t = self.map.tiles[y][x]
        t.walkable = not t.walkable

    def arm_link(self):
        target_map = self.dd_link_map.value
        entry_id = self.link_entry_inp.text.strip()
        if not target_map: return
        self.link_arm = (target_map, entry_id)

    def save(self):
        # consolidate description from big area
        self.map.name = self.name_inp.text.strip() or "Untitled"
        self.map.description = self.desc_area.text
        file_name = f"{self.map.name}.json"
        write_json(os.path.join(MAP_DIR, file_name), self.map.to_dict())
        obj = read_json_any(MANIFEST, {"maps": []}); maps = obj.get("maps", [])
        entry = {"file": file_name, "name": self.map.name, "description": self.map.description, "width": self.map.width, "height": self.map.height}
        replaced = False
        for i, m in enumerate(maps):
            if m.get("file")==file_name:
                maps[i] = entry; replaced=True; break
        if not replaced: maps.append(entry)
        write_json(MANIFEST, {"maps": maps})

    # 2) Resize logic (preserve existing tiles where possible)
    def apply_resize(self):
        try: new_w = max(1, int(self.resize_w_inp.text))
        except: new_w = self.map.width
        try: new_h = max(1, int(self.resize_h_inp.text))
        except: new_h = self.map.height

        if new_w == self.map.width and new_h == self.map.height:
            return

        new_tiles: List[List[TileData]] = []
        for y in range(new_h):
            row: List[TileData] = []
            for x in range(new_w):
                if y < self.map.height and x < self.map.width:
                    row.append(self.map.tiles[y][x])
                else:
                    row.append(TileData())  # default impassable
            new_tiles.append(row)
        self.map.tiles = new_tiles
        self.map.width = new_w
        self.map.height = new_h
        # update fields
        self.resize_w_inp.text = str(new_w)
        self.resize_h_inp.text = str(new_h)

    # ---------- canvas geometry ----------
    def screen_to_tile(self, sx: int, sy: int) -> Optional[Tuple[int,int]]:
        x = int((sx - self.offset_x) / self.tile_size)
        y = int((sy - self.offset_y) / self.tile_size)
        if 0 <= x < self.map.width and 0 <= y < self.map.height:
            return (x,y)
        return None

    def tile_rect(self, x: int, y: int) -> pygame.Rect:
        ts = self.tile_size
        x0 = self.offset_x + x * ts
        y0 = self.offset_y + y * ts
        return pygame.Rect(x0, y0, ts, ts)

    # ---------- render ----------
    def draw(self, surf):
        surf.fill(PAPER_BG)
        # top bar
        pygame.draw.rect(surf, PANEL_BG, (0,0,1280,50))
        draw_text(surf, "Name:", (14, 18), TEXT_DIM)
        draw_text(surf, "Size W×H:", (520, 18), TEXT_DIM)
        self.name_inp.draw(surf)
        self.btn_save.draw(surf); self.btn_back.draw(surf)
        self.resize_w_inp.draw(surf); self.resize_h_inp.draw(surf); self.btn_resize.draw(surf)

        # canvas bg
        pygame.draw.rect(surf, CANVAS_BG, (0,50,900,670))

        # grid
        for y in range(self.map.height):
            for x in range(self.map.width):
                r = self.tile_rect(x,y)
                color = (LIGHT_WALKABLE if (x+y)%2==0 else DARK_WALKABLE) if self.map.tiles[y][x].walkable else IMPASSABLE
                pygame.draw.rect(surf, color, r)
                pygame.draw.rect(surf, GRID_LINE, r, 1)

        # icons overlay
        for y in range(self.map.height):
            for x in range(self.map.width):
                t = self.map.tiles[y][x]
                if t.npcs or t.items or t.links:
                    r = self.tile_rect(x,y)
                    cx, cy = r.center
                    parts = []
                    if t.npcs:  parts.append(ICON_NPC)
                    if t.items: parts.append(ICON_ITEM)
                    if t.links: parts.append(ICON_LINK)
                    txt = FONT.render(" ".join(parts), True, TEXT_MAIN)
                    surf.blit(txt, txt.get_rect(center=(cx, cy)))

        # selection outline
        if self.selected:
            r = self.tile_rect(*self.selected)
            pygame.draw.rect(surf, ACCENT, r, 2)

        # right panel
        sidebar = pygame.Rect(900,50,380,670)
        pygame.draw.rect(surf, PANEL_BG, sidebar); pygame.draw.rect(surf, GRID_LINE, sidebar, 1)

        # categories
        self.btn_cat_npcs.draw(surf); self.btn_cat_items.draw(surf); self.btn_cat_links.draw(surf)

        if self.category == "NPCs":
            draw_text(surf, "Subcategory", (920, 160), TEXT_DIM)
            self.dd_npc_sub.draw_base(surf)
            self.list_box.draw(surf)
            self.btn_add_to_tile.draw(surf); self.btn_toggle_walkable.draw(surf)
        elif self.category == "Items":
            draw_text(surf, "Subcategory", (920, 160), TEXT_DIM)
            self.dd_item_sub.draw_base(surf)
            self.list_box.draw(surf)
            self.btn_add_to_tile.draw(surf); self.btn_toggle_walkable.draw(surf)
        else:
            draw_text(surf, "Target Map", (920, 160), TEXT_DIM)
            self.dd_link_map.draw_base(surf)
            draw_text(surf, "Target Entry (opt)", (1150, 160), TEXT_DIM)
            self.link_entry_inp.draw(surf)
            self.btn_arm_link.draw(surf)
            self.btn_toggle_walkable.draw(surf)

        # big description
        draw_text(surf, "Map Description", (920, 460), TEXT_DIM)
        self.desc_area.draw(surf)

        # inspector (summary line)
        pygame.draw.rect(surf, PANEL_BG_DARK, self.inspector_rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.inspector_rect, 1, border_radius=8)
        if self.selected:
            x,y = self.selected
            t = self.map.tiles[y][x]
            info = f"({x},{y}) {'Walk' if t.walkable else 'Block'} | NPCs:{len(t.npcs)} Items:{len(t.items)} Links:{len(t.links)}"
        else:
            info = "(no tile selected)"
        draw_text(surf, info, (self.inspector_rect.x+8, self.inspector_rect.y+8))

        # draw dropdown popups last
        if self.category == "NPCs":
            self.dd_npc_sub.draw_popup(surf)
        elif self.category == "Items":
            self.dd_item_sub.draw_popup(surf)
        else:
            self.dd_link_map.draw_popup(surf)

    def handle(self, event):
        # top
        self.name_inp.handle(event)
        self.btn_save.handle(event); self.btn_back.handle(event)
        self.resize_w_inp.handle(event); self.resize_h_inp.handle(event); self.btn_resize.handle(event)

        # right panel
        self.btn_cat_npcs.handle(event); self.btn_cat_items.handle(event); self.btn_cat_links.handle(event)
        if self.category == "NPCs":
            self.dd_npc_sub.handle(event); self.list_box.handle(event); self.btn_add_to_tile.handle(event); self.btn_toggle_walkable.handle(event)
        elif self.category == "Items":
            self.dd_item_sub.handle(event); self.list_box.handle(event); self.btn_add_to_tile.handle(event); self.btn_toggle_walkable.handle(event)
        else:
            self.dd_link_map.handle(event); self.link_entry_inp.handle(event); self.btn_arm_link.handle(event); self.btn_toggle_walkable.handle(event)

        # description area
        self.desc_area.handle(event)

        # canvas interactions
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if pygame.Rect(0,50,900,670).collidepoint(event.pos):
                t = self.screen_to_tile(*event.pos)
                if t:
                    self.selected = t
                    if self.link_arm:
                        x,y = t
                        self.map.tiles[y][x].links.append({"target_map": self.link_arm[0], "target_entry": self.link_arm[1]})
                        self.link_arm = None
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            if pygame.Rect(0,50,900,670).collidepoint(event.pos):
                self.panning = True
                self.pan_start = event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            self.panning = False
        elif event.type == pygame.MOUSEMOTION and self.panning:
            dx = event.pos[0] - self.pan_start[0]; dy = event.pos[1] - self.pan_start[1]
            self.offset_x += dx; self.offset_y += dy; self.pan_start = event.pos
        elif event.type == pygame.MOUSEWHEEL:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            canvas_rect = pygame.Rect(0,50,900,670)
            if canvas_rect.collidepoint((mouse_x, mouse_y)):
                old_ts = self.tile_size
                world_x = (mouse_x - self.offset_x) / old_ts
                world_y = (mouse_y - self.offset_y) / old_ts
                zoom_factor = 1.1 if event.y > 0 else (1/1.1)
                new_ts = max(TILE_MIN, min(TILE_MAX, int(old_ts * zoom_factor)))
                if new_ts != old_ts:
                    self.tile_size = new_ts
                    self.offset_x = int(mouse_x - world_x * new_ts)
                    self.offset_y = int(mouse_y - world_y * new_ts)

    def update(self, dt):
        self.name_inp.update(dt)
        self.resize_w_inp.update(dt); self.resize_h_inp.update(dt)
        self.desc_area.update(dt)

# -------------------- App --------------------
class App:
    def __init__(self):
        self.screen = pygame.display.set_mode((1280, 720))
        pygame.display.set_caption("RPGenesis – Map Editor (Pygame)")
        self.clock = pygame.time.Clock()
        self.running = True
        self.start_screen = StartScreen(self)
        self.editor_screen: Optional[EditorScreen] = None

    def goto_start(self):
        self.editor_screen = None

    def goto_editor(self, mapdata: MapData):
        self.editor_screen = EditorScreen(self, mapdata)

    def run(self):
        while self.running:
            dt = self.clock.tick(60)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif self.editor_screen:
                    self.editor_screen.handle(event)
                else:
                    self.start_screen.handle(event)

            if self.editor_screen:
                self.editor_screen.update(dt)
                self.editor_screen.draw(self.screen)
            else:
                self.start_screen.update(dt)
                self.start_screen.draw(self.screen)

            pygame.display.flip()

# ---------- main ----------
if __name__ == "__main__":
    App().run()
