
import os
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable, Set

import pygame

# -------------------- Paths & constants --------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
MAP_DIR  = os.path.join(DATA_DIR, "maps")
NPC_DIR  = os.path.join(DATA_DIR, "npcs")
ITEM_DIR = os.path.join(DATA_DIR, "items")
MANIFEST = os.path.join(DATA_DIR, "maps.json")
TILE_IMG_DIR = os.path.join(ROOT_DIR, "assets", "images", "map_tiles")

os.makedirs(MAP_DIR, exist_ok=True)

NPC_SUBCATS   = ["allies", "enemies", "monsters", "animals", "citizens"]
ITEM_SUBCATS  = ["accessories", "armour", "clothing", "materials", "quest_items", "trinkets", "weapons"]

TILE_SIZE_DEFAULT = 32
GRID_W_DEFAULT, GRID_H_DEFAULT = 20, 10
TILE_MIN, TILE_MAX = 16, 96

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
DANGER         = (220, 66, 66)

# Encounter tint (RGBA)
SAFE_TINT_RGBA   = (50, 180, 90, 60)
DANGER_TINT_RGBA = (200, 70, 70, 60)

# Dot colors
COL_RED    = (220,70,70)     # enemies
COL_GREEN  = (80,200,120)    # allies
COL_BLUE   = (80,150,240)    # citizens
COL_PURPLE = (170,110,240)   # monsters
COL_YELLOW = (245,210,80)    # animals
COL_WHITE  = (240,240,240)   # items (non-quest)
COL_ORANGE = (255,160,70)    # quest items
COL_PINK   = (255,105,180)   # links (hot pink)

TYPE_DOT_COLORS = {
    "ally": COL_GREEN,
    "enemy": COL_RED,
    "citizen": COL_BLUE,
    "monster": COL_PURPLE,
    "animal": COL_YELLOW,
    "item": COL_WHITE,
    "quest_item": COL_ORANGE,
    "link": COL_PINK,
}

# Tooltip colors
TOOLTIP_BG_RGBA = (20, 22, 26, 220)  # dark with alpha
TOOLTIP_BORDER  = GRID_LINE
TOOLTIP_TEXT    = TEXT_MAIN

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
    walkable: bool = False  # default IMPASSABLE
    npcs: List[Dict[str, Any]] = field(default_factory=list)
    items: List[Dict[str, Any]] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)  # max 1 enforced in UI
    note: str = ""  # per-tile note/description
    encounter: str = ""  # "safe" | "danger" | "" (none)
    texture: str = ""  # filename from assets/images/map_tiles

@dataclass
class MapData:
    name: str = "Untitled"
    description: str = ""
    width: int = GRID_W_DEFAULT
    height: int = GRID_H_DEFAULT
    tile_size: int = TILE_SIZE_DEFAULT
    tiles: List[List[TileData]] = field(default_factory=list)

    @staticmethod
    def new(name: str, description: str, w: int, h: int) -> "MapData":
        tiles = [[TileData() for _ in range(w)] for __ in range(h)]
        return MapData(name=name, description=description, width=w, height=h, tile_size=TILE_SIZE_DEFAULT, tiles=tiles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "tile_size": int(self.tile_size),
            "tiles": [[{
                "walkable": t.walkable,
                "npcs": t.npcs,
                "items": t.items,
                "links": t.links,
                "note": t.note,
                "encounter": t.encounter,
                "texture": t.texture,
            } for t in row] for row in self.tiles],
        }

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> "MapData":
        name = obj.get("name", "Untitled")
        desc = obj.get("description", "")
        w = int(obj.get("width", GRID_W_DEFAULT))
        h = int(obj.get("height", GRID_H_DEFAULT))
        ts = int(obj.get("tile_size", TILE_SIZE_DEFAULT))
        raw_tiles = obj.get("tiles") or []
        tiles: List[List[TileData]] = []
        for y in range(h):
            row: List[TileData] = []
            for x in range(w):
                cell = (raw_tiles[y][x] if y < len(raw_tiles) and x < len(raw_tiles[y]) else {}) or {}
                row.append(TileData(
                    walkable=bool(cell.get("walkable", False)),
                    npcs=list(cell.get("npcs", [])),
                    items=list(cell.get("items", [])),
                    links=list(cell.get("links", [])),
                    note=str(cell.get("note", "")),
                    encounter=str(cell.get("encounter", "")),
                    texture=str(cell.get("texture", "")),
                ))
            tiles.append(row)
        return MapData(name=name, description=desc, width=w, height=h, tile_size=ts, tiles=tiles)

# -------------------- History (Undo/Redo) --------------------
class History:
    def __init__(self, limit: int = 200):
        self.limit = limit
        self.stack: List[Tuple[Callable[[], None], Callable[[], None], str]] = []
        self.index = -1  # last applied index
        self.batch: List[Tuple[Callable[[], None], Callable[[], None]]] = []
        self.in_batch = False
        self.batch_label = ""
    def push(self, do_fn: Callable[[], None], undo_fn: Callable[[], None], label: str = ""):
        if self.index < len(self.stack) - 1:
            self.stack = self.stack[:self.index+1]
        self.stack.append((do_fn, undo_fn, label))
        if len(self.stack) > self.limit:
            self.stack = self.stack[-self.limit:]
            self.index = len(self.stack) - 1
        do_fn()
        self.index += 1
    def begin_batch(self, label: str):
        if self.in_batch: return
        self.in_batch = True
        self.batch_label = label
        self.batch.clear()
    def add_to_batch(self, do_fn: Callable[[], None], undo_fn: Callable[[], None]):
        if not self.in_batch:
            self.push(do_fn, undo_fn, "single")
        else:
            self.batch.append((do_fn, undo_fn))
    def end_batch(self):
        if not self.in_batch:
            return
        if not self.batch:
            self.in_batch = False; self.batch_label = ""; return
        def do_all():
            for d,u in self.batch:
                d()
        def undo_all():
            for d,u in reversed(self.batch):
                u()
        self.push(do_all, undo_all, self.batch_label)
        self.in_batch = False
        self.batch_label = ""
        self.batch.clear()
    def can_undo(self) -> bool:
        return self.index >= 0
    def can_redo(self) -> bool:
        return self.index < len(self.stack) - 1
    def undo(self):
        if not self.can_undo(): return
        _, undo_fn, _ = self.stack[self.index]
        undo_fn()
        self.index -= 1
    def redo(self):
        if not self.can_redo(): return
        do_fn, _, _ = self.stack[self.index+1]
        do_fn()
        self.index += 1

# -------------------- Pygame UI --------------------
pygame.init()
pygame.display.set_caption("RPGenesis - Map Editor (Pygame)")
FONT = pygame.font.SysFont("segoeui", 16)
FONT_BOLD = pygame.font.SysFont("segoeui", 18, bold=True)

def draw_text(surface, text, pos, color=TEXT_MAIN, font=FONT):
    surface.blit(font.render(text, True, color), pos)

# ---------- Mouse position provider (to support window scaling) ----------
_mouse_pos_provider = None  # type: Optional[Callable[[], Tuple[int,int]]]

def set_mouse_pos_provider(fn: Optional[Callable[[], Tuple[int,int]]]):
    global _mouse_pos_provider
    _mouse_pos_provider = fn

def get_mouse_pos() -> Tuple[int,int]:
    if _mouse_pos_provider:
        try:
            return _mouse_pos_provider()
        except Exception:
            pass
    return pygame.mouse.get_pos()

# ---------- UI widgets ----------
class Button:
    def __init__(self, rect, text, on_click: Callable[[], None], *, danger=False):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.on_click = on_click
        self.hover = False
        self.danger = danger
    def handle(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.on_click()
    def draw(self, surf):
        base = DANGER if self.danger else BTN_BG
        pygame.draw.rect(surf, BTN_HOVER if self.hover else base, self.rect, border_radius=8)
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
            if self.rect.collidepoint(get_mouse_pos()):
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
        surf.set_clip(clip)

class Dropdown:
    def __init__(self, rect, options, value=None, on_change=None, get_icon=None):
        self.rect = pygame.Rect(rect)
        self.options = options[:]
        self.value = value if value in options else (options[0] if options else "")
        self.on_change = on_change
        self.opened = False
        self.hover = False
        self.popup_rects: List[pygame.Rect] = []
        self.popup_upwards = False
        # Optional callable: (opt: str, size_px: int) -> pygame.Surface | None
        self.get_icon = get_icon
    def is_open(self):
        return self.opened
    def close(self):
        self.opened = False
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
        x_text = self.rect.x + 8
        # Small icon inside base (if available)
        if self.get_icon and self.value:
            try:
                size = max(12, self.rect.h - 8)
                ico = self.get_icon(self.value, size)
                if ico is not None:
                    y = self.rect.y + (self.rect.h - ico.get_height()) // 2
                    surf.blit(ico, (x_text, y))
                    x_text += ico.get_width() + 6
            except Exception:
                pass
        draw_text(surf, self.value, (x_text, self.rect.y+6))
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
        # Compute hover based on current mouse position for immediate feedback
        try:
            mx, my = get_mouse_pos()
        except Exception:
            mx, my = pygame.mouse.get_pos()
        for r, opt in zip(self.popup_rects, self.options):
            hovered = r.collidepoint((mx, my))
            pygame.draw.rect(surf, BTN_HOVER if hovered else PANEL_BG, r)
            pygame.draw.rect(surf, GRID_LINE, r, 1)
            x = r.x + 8
            if self.get_icon:
                try:
                    size = max(12, r.h - 8)
                    ico = self.get_icon(opt, size)
                    if ico is not None:
                        y = r.y + (r.h - ico.get_height()) // 2
                        surf.blit(ico, (x, y))
                        x += ico.get_width() + 6
                except Exception:
                    pass
            draw_text(surf, opt, (x, r.y+6))

class ScrollListWithButtons:
    """Scrollable list that renders labels with Remove buttons; supports expand/collapse per row.
       Also exposes index_at_pos() to support right-click context menus.

       Items may be tuples of:
         (label: str, on_remove: Callable)
       or
         (label: str, on_remove: Callable, details: Dict[str, Any]) where details may contain:
           - 'kv': List[str]  # simple key/value lines
           - 'desc': str      # long description text
    """
    def __init__(self, rect: pygame.Rect):
        self.rect = pygame.Rect(rect)
        self.items: List[Tuple] = []
        self.scroll = 0
        self.item_h = 24
        self.spacing = 6
        self.expanded: Set[int] = set()

    def set_items(self, items: List[Tuple]):
        self.items = items
        # Preserve scroll and expanded state; clamp to new content
        inner_w = self.rect.w - 12
        try:
            max_scroll = max(0, self._content_height(inner_w) - self.rect.h)
        except Exception:
            max_scroll = 0
        self.scroll = max(0, min(self.scroll, max_scroll))
        self.expanded = {i for i in self.expanded if 0 <= i < len(self.items)}

    def _wrap(self, text: str, width_px: int) -> List[str]:
        # Basic pixel-width word wrap using current FONT
        words = (text or "").split(" ")
        lines: List[str] = []
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            if not line or FONT.size(test)[0] <= width_px:
                line = test
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        out: List[str] = []
        for raw in "\n".join(lines).split("\n"):
            cur = ""
            for ch in raw:
                if not cur or FONT.size(cur + ch)[0] <= width_px:
                    cur += ch
                else:
                    out.append(cur)
                    cur = ch
            out.append(cur)
        return out

    def _details_for(self, idx: int) -> Dict[str, Any]:
        if idx < 0 or idx >= len(self.items):
            return {}
        it = self.items[idx]
        if len(it) >= 3 and isinstance(it[2], dict):
            return it[2]
        return {}

    def _row_height(self, idx: int, width_px: int) -> int:
        h = self.item_h
        if idx in self.expanded:
            details = self._details_for(idx)
            pad = 6
            h += pad  # spacing below header
            kv = details.get('kv') or []
            if kv:
                h += len(kv) * (FONT.get_height() + 2)
            desc = details.get('desc') or ""
            if desc:
                wrapped = self._wrap(desc, max(0, width_px - 16))
                h += len(wrapped) * (FONT.get_height() + 2)
            h += pad
        return h

    def _content_height(self, width_px: int) -> int:
        total = 0
        for i in range(len(self.items)):
            total += self._row_height(i, width_px) + self.spacing
        if total > 0:
            total -= self.spacing  # no spacing after last
        return total

    def index_at_pos(self, pos: Tuple[int,int]) -> Optional[int]:
        x, y = pos
        if not self.rect.collidepoint((x, y)):
            return None
        y_cursor = self.rect.y - self.scroll
        inner_w = self.rect.w - 12
        for i in range(len(self.items)):
            h = self._row_height(i, inner_w)
            row_rect = pygame.Rect(self.rect.x+6, y_cursor, self.rect.w-12, self.item_h)
            if row_rect.collidepoint((x, y)):
                return i
            y_cursor += h + self.spacing
        return None

    def handle(self, event):
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(get_mouse_pos()):
                inner_w = self.rect.w - 12
                content_h = self._content_height(inner_w)
                max_scroll = max(0, content_h - self.rect.h)
                self.scroll = max(0, min(max_scroll, self.scroll - event.y * 24))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            x, y = event.pos
            if not self.rect.collidepoint((x, y)):
                return
            y_cursor = self.rect.y - self.scroll
            inner_w = self.rect.w - 12
            for i, it in enumerate(self.items):
                h_total = self._row_height(i, inner_w)
                header_rect = pygame.Rect(self.rect.x+6, y_cursor, self.rect.w-12, self.item_h)
                btn_rect = pygame.Rect(header_rect.right-70, header_rect.y, 64, self.item_h)
                if btn_rect.collidepoint((x, y)):
                    # on_remove is at index 1
                    try:
                        on_remove = it[1]
                        if callable(on_remove):
                            on_remove()
                    finally:
                        pass
                    break
                elif header_rect.collidepoint((x, y)):
                    # toggle expand/collapse
                    if i in self.expanded:
                        self.expanded.remove(i)
                    else:
                        self.expanded.add(i)
                    break
                y_cursor += h_total + self.spacing

    def draw(self, surf):
        pygame.draw.rect(surf, PANEL_BG_DARK, self.rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=8)
        clip = surf.get_clip()
        surf.set_clip(self.rect)
        y_cursor = self.rect.y - self.scroll
        try:
            mx, my = get_mouse_pos()
        except Exception:
            mx, my = pygame.mouse.get_pos()
        inner_w = self.rect.w - 12
        for i, it in enumerate(self.items):
            label = it[0]
            # Header row
            header_rect = pygame.Rect(self.rect.x+6, y_cursor, self.rect.w-12, self.item_h)
            hovered = header_rect.collidepoint((mx, my))
            pygame.draw.rect(surf, BTN_HOVER if hovered else PANEL_BG, header_rect, border_radius=6)
            draw_text(surf, label[:120], (header_rect.x+8, header_rect.y+4))
            btn_rect = pygame.Rect(header_rect.right-70, header_rect.y, 64, self.item_h)
            pygame.draw.rect(surf, DANGER, btn_rect, border_radius=6)
            draw_text(surf, "Remove", (btn_rect.x+6, btn_rect.y+4))

            # Expanded details
            y = header_rect.bottom + 6
            if i in self.expanded:
                details = self._details_for(i)
                kv = details.get('kv') or []
                for ln in kv:
                    surf.blit(FONT.render(ln, True, TEXT_DIM), (header_rect.x+10, y))
                    y += FONT.get_height() + 2
                desc = details.get('desc') or ""
                if desc:
                    for ln in self._wrap(desc, max(0, inner_w - 16)):
                        surf.blit(FONT.render(ln, True, TEXT_MAIN), (header_rect.x+10, y))
                        y += FONT.get_height() + 2
            # advance cursor by computed total height for this item
            y_cursor += self._row_height(i, inner_w) + self.spacing
        surf.set_clip(clip)

# -------------------- StartScreen --------------------
class StartScreen:
    def __init__(self, app):
        self.app = app
        # Initial positions; will be centered each frame
        self.btn_refresh = Button((60, 120, 140, 32), "Refresh", self.refresh)
        self.btn_open   = Button((210, 120, 160, 32), "Open Selected", self.open_selected)
        self.btn_create = Button((60, 410, 180, 36), "Create New Map", self.create_map)
        self.btn_world  = Button((250, 410, 180, 36), "World View", self.open_world_view)
        self.maps_list = ListBox((60, 160, 520, 230))
        self.refresh()
    def _apply_layout(self, surf):
        w, h = surf.get_size()
        list_w = 520
        left = max(0, (w - list_w) // 2)
        # Center list
        self.maps_list.rect.topleft = (left, 160)
        # Top row buttons
        self.btn_refresh.rect.topleft = (left, 120)
        self.btn_open.rect.topleft    = (left + 150, 120)
        # Bottom row buttons (center under list)
        self.btn_create.rect.topleft  = (left, 410)
        self.btn_world.rect.topleft   = (left + 190, 410)
    def refresh(self):
        obj = read_json_any(MANIFEST, {"maps": []})
        self.maps = obj.get("maps", [])
        items = [f"{m.get('name','(unnamed)')} - {m.get('file','?')}" for m in self.maps]
        self.maps_list.set_items(items)
    def draw(self, surf):
        surf.fill(PAPER_BG)
        self._apply_layout(surf)
        left = self.maps_list.rect.x
        # Header centered above list
        title = "RPGenesis - Maps"
        tip   = "Select a map or create a new one."
        draw_text(surf, title, (left, 10), TEXT_MAIN, FONT_BOLD)
        draw_text(surf, tip,   (left, 70), TEXT_DIM)
        # Controls
        self.btn_refresh.draw(surf); self.btn_open.draw(surf)
        self.maps_list.draw(surf)
        panel_rect = pygame.Rect(left, 400, self.maps_list.rect.w, 70)
        pygame.draw.rect(surf, PANEL_BG, panel_rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, panel_rect, 1, border_radius=8)
        self.btn_create.draw(surf)
        self.btn_world.draw(surf)
    def handle(self, event):
        # Ensure layout reflects current window size before hit testing
        try:
            self._apply_layout(self.app.screen)
        except Exception:
            pass
        self.btn_refresh.handle(event); self.btn_open.handle(event); self.maps_list.handle(event); self.btn_create.handle(event); self.btn_world.handle(event)
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
        md = MapData.new("Untitled", "", GRID_W_DEFAULT, GRID_H_DEFAULT)
        self.app.goto_editor(md)
    def open_world_view(self):
        self.app.goto_world()

# -------------------- EditorScreen --------------------
class EditorScreen:
    def __init__(self, app, mapdata: MapData):
        self.app = app
        self.map = mapdata
        # Initialize view scale from map's tile size
        self.tile_size = int(getattr(self.map, 'tile_size', TILE_SIZE_DEFAULT))
        self.offset_x = 60
        self.offset_y = 60
        self.selected: Optional[Tuple[int,int]] = None

        # History
        self.history = History()
        self.painting_batch_active = False
        self.painting_button = None  # 1=left (Impassable), 3=right (Passable))

        # top bar
        self.name_inp = TextInput((80, 12, 240, 28), self.map.name)
        self.btn_save = Button((340, 12, 100, 28), "Save", self.save)
        self.btn_back = Button((450, 12, 120, 28), "Back to Menu", self.app.goto_start)
        self.btn_undo = Button((580, 12, 80, 28), "Undo", self.history.undo)
        self.btn_redo = Button((665, 12, 80, 28), "Redo", self.history.redo)

        # resize
        self.resize_w_inp = TextInput((760, 12, 60, 28), str(self.map.width))
        self.resize_h_inp = TextInput((825, 12, 60, 28), str(self.map.height))
        self.btn_resize   = Button((890, 12, 110, 28), "Apply Size", self.apply_resize)

        # cursor mode: Select / Walls / Safety / Texture
        self.left_click_mode = "select"
        self.btn_cycle_left_mode = Button((1010, 12, 180, 28), "Mode: Select", self.cycle_left_mode)

        # right panel categories (adders)
        self.category = "NPCs"
        self.btn_cat_npcs  = Button((920, 60, 140, 30), "NPCs",  lambda: self._switch_category("NPCs"))
        self.btn_cat_items = Button((920, 95, 140, 30), "Items", lambda: self._switch_category("Items"))
        self.btn_cat_links = Button((920, 130, 140, 30), "Links", lambda: self._switch_category("Links"))

        # NPCs / Items lists
        self.dd_npc_sub  = Dropdown((920, 180, 140, 26), NPC_SUBCATS,  value=NPC_SUBCATS[0], on_change=lambda v: self._reload_npcs(), get_icon=self._get_npc_sub_icon)
        self.dd_item_sub = Dropdown((920, 180, 140, 26), ITEM_SUBCATS, value=ITEM_SUBCATS[0], on_change=lambda v: self._reload_items(), get_icon=self._get_item_sub_icon)
        self.list_box = ListBox((920, 214, 340, 160))
        self.btn_add_to_tile      = Button((920, 380, 160, 28), "Add to Selected", self.add_selected_to_tile)

        # Initialize entry caches to avoid AttributeError before first reload
        self.npc_entries: List[Dict[str, Any]] = []
        self.item_entries: List[Dict[str, Any]] = []

        # Links (no arming; add directly to selected tile) — enforce max 1
        self.maps_available = [f for f in os.listdir(MAP_DIR) if f.lower().endswith(".json")]
        link_default = self.maps_available[0] if self.maps_available else ""
        self.dd_link_map = Dropdown((920, 180, 220, 26), self.maps_available, value=link_default, on_change=None)
        self.link_entry_inp = TextInput((1150, 180, 110, 26), "")
        self.btn_add_link   = Button((920, 214, 180, 28), "Add Link to Tile", self.add_link_to_selected)

        # Texture painting: dropdown of PNGs in assets/images/map_tiles
        try:
            files = [f for f in os.listdir(TILE_IMG_DIR) if f.lower().endswith(".png")]
        except Exception:
            files = []
        self.texture_files: List[str] = sorted(files)
        default_tex = self.texture_files[0] if self.texture_files else ""
        # Place above inspector section
        self.dd_texture = Dropdown((920, 412, 260, 26), self.texture_files, value=default_tex, on_change=None, get_icon=self._get_texture_icon)
        # texture cache: original images and scaled per tile_size
        self._tex_images: Dict[str, pygame.Surface] = {}
        self._tex_scaled: Dict[Tuple[str, int], pygame.Surface] = {}
        for name in self.texture_files:
            try:
                surf = pygame.image.load(os.path.join(TILE_IMG_DIR, name)).convert_alpha()
                self._tex_images[name] = surf
            except Exception:
                pass

        # Tile Info (scrollable list)
        self.inspector_header_rect = pygame.Rect(900, 450, 380, 32)
        self.scroll_list = ScrollListWithButtons(pygame.Rect(900, 484, 380, 140))  # wheel scrollable
        self.btn_edit_note    = Button((900, 630, 120, 26), "Edit Note", self.open_note_modal)
      
        # Map description at bottom (taller by default)
        self.desc_area = TextArea((900, 622, 380, 120), self.map.description)

        # Default regions (updated each frame for responsive layout)
        self.canvas_rect = pygame.Rect(0, 50, 900, 670)
        self.sidebar_rect = pygame.Rect(900, 50, 380, 670)

        # note modal state
        self.note_modal_open = False
        self.note_modal_area = TextArea(pygame.Rect(340, 200, 600, 280), "")
        self.note_btn_save   = Button((340, 490, 100, 30), "Save", self.save_note_modal)
        self.note_btn_cancel = Button((460, 490, 100, 30), "Cancel", self.close_note_modal)

        # canvas state
        self.panning = False
        self.pan_start = (0,0)
        self.left_dragging = False

        # Initial loads so attributes & list contents exist immediately
        self._reload_npcs()
        self._reload_items()
        # Set list box contents to match starting category
        if self.category == "NPCs":
            self.list_box.set_items([self._display_label(e) for e in self.npc_entries])
        elif self.category == "Items":
            self.list_box.set_items([self._display_label(e) for e in self.item_entries])
        else:
            self.list_box.set_items([])

    # ---------- helpers ----------
    def _get_texture_icon(self, opt: str, size: int) -> Optional[pygame.Surface]:
        try:
            key = (opt, size)
            tex = self._tex_scaled.get(key)
            if tex is None:
                base = self._tex_images.get(opt)
                if base is None:
                    path = os.path.join(TILE_IMG_DIR, opt)
                    if os.path.exists(path):
                        base = pygame.image.load(path).convert_alpha()
                        self._tex_images[opt] = base
                if base is not None:
                    tex = pygame.transform.smoothscale(base, (size, size))
                    self._tex_scaled[key] = tex
            return tex
        except Exception:
            return None

    def _get_npc_sub_icon(self, opt: str, size: int) -> Optional[pygame.Surface]:
        try:
            sub = (opt or '').lower()
            color = None
            if sub == 'enemies': color = COL_RED
            elif sub == 'allies': color = COL_GREEN
            elif sub == 'citizens': color = COL_BLUE
            elif sub == 'monsters': color = COL_PURPLE
            elif sub == 'animals': color = COL_YELLOW
            if color is None: return None
            s = max(10, size)
            surf = pygame.Surface((s, s), pygame.SRCALPHA)
            r = s // 3
            cx = s // 2
            cy = s // 2
            pygame.draw.circle(surf, (10,10,12,255), (cx, cy), r+1)
            pygame.draw.circle(surf, color, (cx, cy), r)
            return surf
        except Exception:
            return None

    def _get_item_sub_icon(self, opt: str, size: int) -> Optional[pygame.Surface]:
        try:
            sub = (opt or '').lower()
            color = COL_ORANGE if sub == 'quest_items' else COL_WHITE
            s = max(10, size)
            surf = pygame.Surface((s, s), pygame.SRCALPHA)
            r = s // 3
            cx = s // 2
            cy = s // 2
            pygame.draw.circle(surf, (10,10,12,255), (cx, cy), r+1)
            pygame.draw.circle(surf, color, (cx, cy), r)
            return surf
        except Exception:
            return None

    def _apply_layout(self, surf):
        w, h = surf.get_size()
        top_h = 50
        sb_w = 380
        # Sidebar flush to right edge, canvas fills the rest from left edge
        self.sidebar_rect = pygame.Rect(max(0, w - sb_w), top_h, sb_w, max(0, h - top_h))
        self.canvas_rect = pygame.Rect(0, top_h, max(0, w - sb_w), max(0, h - top_h))

        # Top bar controls anchored to window edges (fixed sizes)
        self.name_inp.rect.topleft = (80, 12)
        self.btn_save.rect.topleft = (340, 12)
        self.btn_back.rect.topleft = (450, 12)
        self.btn_undo.rect.topleft = (580, 12)
        self.btn_redo.rect.topleft = (665, 12)
        self.resize_w_inp.rect.topleft = (760, 12)
        self.resize_h_inp.rect.topleft = (825, 12)
        self.btn_resize.rect.topleft   = (890, 12)
        self.btn_cycle_left_mode.rect.x = max(0, w - self.btn_cycle_left_mode.rect.w - 16)
        self.btn_cycle_left_mode.rect.y = 12

        # Sidebar widgets
        sx = self.sidebar_rect.x + 20
        sy = self.sidebar_rect.y
        self.btn_cat_npcs.rect.topleft  = (sx, sy + 10)
        self.btn_cat_items.rect.topleft = (sx, sy + 45)
        self.btn_cat_links.rect.topleft = (sx, sy + 80)
        self.dd_npc_sub.rect.topleft  = (sx, sy + 130)
        self.dd_item_sub.rect.topleft = (sx, sy + 130)
        self.list_box.rect.topleft = (sx, sy + 164)
        self.list_box.rect.size = (self.sidebar_rect.w - 40, self.list_box.rect.h)
        self.btn_add_to_tile.rect.topleft = (sx, sy + 330)
        # Links
        self.dd_link_map.rect.topleft = (sx, sy + 130)
        self.link_entry_inp.rect.topleft = (self.sidebar_rect.right - self.link_entry_inp.rect.w - 20, sy + 130)
        self.btn_add_link.rect.topleft = (sx, sy + 164)
        # Texture picker
        self.dd_texture.rect.topleft = (sx, sy + 362)
        # Inspector header and scroll list
        self.inspector_header_rect = pygame.Rect(self.sidebar_rect.x, sy + 400, self.sidebar_rect.w, 32)
        # Dynamic description size anchored to bottom
        desc_h = max(80, min(200, int(self.sidebar_rect.h * 0.22)))
        desc_y = self.sidebar_rect.bottom - (desc_h + 16)
        self.desc_area.rect = pygame.Rect(self.sidebar_rect.x, desc_y, self.sidebar_rect.w, desc_h)
        # Edit note button just above description
        self.btn_edit_note.rect.topleft = (self.sidebar_rect.x + 0, self.desc_area.rect.y - 36)
        # Scroll list fills space between inspector header and Edit Note button
        sl_top = self.inspector_header_rect.bottom + 4
        sl_bottom = self.btn_edit_note.rect.y - 12
        sl_h = max(80, sl_bottom - sl_top)
        self.scroll_list.rect = pygame.Rect(self.sidebar_rect.x, sl_top, self.sidebar_rect.w, sl_h)

    def any_dropdown_open(self) -> bool:
        return (
            self.dd_npc_sub.is_open() or self.dd_item_sub.is_open() or self.dd_link_map.is_open()
            or getattr(self.dd_texture, 'is_open', lambda: False)()
        )

    def cycle_left_mode(self):
        modes = ["select", "paint", "safety", "texture"]
        idx = modes.index(self.left_click_mode)
        self.left_click_mode = modes[(idx+1)%len(modes)]
        label = {
            "select":"Mode: Select",
            "paint":"Mode: Walls",
            "safety":"Mode: Safety",
            "texture":"Mode: Texture",
        }[self.left_click_mode]
        self.btn_cycle_left_mode.text = label

    def _switch_category(self, label: str):
        self.category = label
        if label == "NPCs":
            self._reload_npcs()
            self.list_box.set_items([self._display_label(e) for e in self.npc_entries])
        elif label == "Items":
            self._reload_items()
            self.list_box.set_items([self._display_label(e) for e in self.item_entries])
        else:
            self.list_box.set_items([])

    def _reload_npcs(self):
        sub = self.dd_npc_sub.value
        entries = read_json_list(os.path.join(NPC_DIR, f"{sub}.json"))
        self.npc_entries = entries
        if self.category == "NPCs":
            self.list_box.set_items([self._display_label(e) for e in entries])

    def _reload_items(self):
        sub = self.dd_item_sub.value
        entries = read_json_list(os.path.join(ITEM_DIR, f"{sub}.json"))
        self.item_entries = entries
        if self.category == "Items":
            self.list_box.set_items([self._display_label(e) for e in entries])

    def _display_label(self, e: Dict[str, Any]) -> str:
        name = e.get("name") or e.get("title") or "(unnamed)"
        ident = e.get("id") or e.get("code") or e.get("uid") or ""
        return f"{name} [{ident}]" if ident else name

    # ---------- history helpers ----------
    def _record_tile_walkable(self, x:int, y:int, new_val: bool, *, batch=False, label="paint"):
        t = self.map.tiles[y][x]
        old = t.walkable
        if old == new_val:
            return
        def do():  t.walkable = new_val
        def undo(): t.walkable = old
        if batch:
            self.history.add_to_batch(do, undo)
        else:
            self.history.push(do, undo, label)

    
    def _record_set_encounter(self, x:int, y:int, state: str, *, batch=False, label="enc"):
        t = self.map.tiles[y][x]
        old = t.encounter
        new = state
        if old == new:
            return
        def do():  setattr(t, "encounter", new)
        def undo(): setattr(t, "encounter", old)
        if batch:
            self.history.add_to_batch(do, undo)
        else:
            self.history.push(do, undo, label)

    def _record_set_texture(self, x:int, y:int, tex: str, *, batch=False, label="texture"):
        t = self.map.tiles[y][x]
        old = getattr(t, 'texture', "")
        new = tex
        if old == new:
            return
        def do():  setattr(t, 'texture', new)
        def undo(): setattr(t, 'texture', old)
        if batch:
            self.history.add_to_batch(do, undo)
        else:
            self.history.push(do, undo, label)

    def _record_add_list_entry(self, lst: List[Dict[str,Any]], entry: Dict[str,Any], label="add"):
        def do():  lst.append(entry)
        def undo():
            for i in range(len(lst)-1, -1, -1):
                if lst[i] is entry:
                    lst.pop(i); break
        self.history.push(do, undo, label)

    def _record_remove_list_entry(self, lst: List[Dict[str,Any]], index: int, label="remove"):
        if not (0 <= index < len(lst)):
            return
        entry = lst[index]
        def do():  lst.pop(index)
        def undo(): lst.insert(index, entry)
        self.history.push(do, undo, label)

    # ---------- adders ----------
    def add_selected_to_tile(self):
        if not self.selected: return
        x,y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height): return
        t = self.map.tiles[y][x]
        if self.category == "NPCs":
            idx = self.list_box.selected
            if idx < 0 or idx >= len(self.npc_entries): return
            e = self.npc_entries[idx]
            entry = {
                "subcategory": self.dd_npc_sub.value,
                "id": e.get("id") or e.get("code") or e.get("uid") or e.get("name"),
                "name": e.get("name") or e.get("title"),
                "description": e.get("description","")
            }
            self._record_add_list_entry(t.npcs, entry, "add_npc")
        elif self.category == "Items":
            idx = self.list_box.selected
            if idx < 0 or idx >= len(self.item_entries): return
            e = self.item_entries[idx]
            entry = {
                "subcategory": self.dd_item_sub.value,
                "id": e.get("id") or e.get("code") or e.get("uid") or e.get("name"),
                "name": e.get("name") or e.get("title"),
                "description": e.get("description","")
            }
            self._record_add_list_entry(t.items, entry, "add_item")

    def add_link_to_selected(self):
        if not self.selected: return
        x,y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height): return
        target_map = self.dd_link_map.value
        entry_id = self.link_entry_inp.text.strip()
        if not target_map:
            return
        t = self.map.tiles[y][x]
        new_entry = {"target_map": target_map, "target_entry": entry_id}
        # enforce only 1 link per tile: replace existing if any
        old_links = list(t.links)
        def do():
            t.links.clear()
            t.links.append(new_entry)
        def undo():
            t.links.clear()
            t.links.extend(old_links)
        self.history.push(do, undo, "set_link")

    def save(self):
        # Persist current UI values before writing
        self.map.name = self.name_inp.text.strip() or "Untitled"
        self.map.description = self.desc_area.text
        # Persist current tile size as part of the map schema
        try:
            self.map.tile_size = int(self.tile_size)
        except Exception:
            self.map.tile_size = int(TILE_SIZE_DEFAULT)

        # Write the map data to /data/maps/<name>.json
        file_name = f"{self.map.name}.json"
        path = os.path.join(MAP_DIR, file_name)
        obj = self.map.to_dict()
        write_json(path, obj)

        # Update the manifest so the start screen lists it
        manifest = read_json_any(MANIFEST, {"maps": []})
        maps = manifest.get("maps", [])

        entry = {
            "file": file_name,
            "name": self.map.name,
            "description": self.map.description,
            "width": self.map.width,
            "height": self.map.height,
        }

        # Replace if it already exists; otherwise append
        replaced = False
        for i, m in enumerate(maps):
            if m.get("file") == file_name:
                maps[i] = entry
                replaced = True
                break
        if not replaced:
            maps.append(entry)

        write_json(MANIFEST, {"maps": maps})

    def apply_resize(self):
        """Resize the map grid based on width/height inputs."""
        try:
            new_w = int(self.resize_w_inp.text)
            new_h = int(self.resize_h_inp.text)
        except ValueError:
            return  # invalid input, do nothing

        if new_w <= 0 or new_h <= 0:
            return

        old_tiles = self.map.tiles
        old_w = self.map.width
        old_h = self.map.height

        def do():
            self.map.width = new_w
            self.map.height = new_h
            new_tiles = [[TileData() for _ in range(new_w)] for __ in range(new_h)]
            for y in range(min(old_h, new_h)):
                for x in range(min(old_w, new_w)):
                    new_tiles[y][x] = old_tiles[y][x]
            self.map.tiles = new_tiles

        def undo():
            self.map.width = old_w
            self.map.height = old_h
            self.map.tiles = old_tiles

        self.history.push(do, undo, label="resize_map")

    # ---------- sidebar scroller data ----------
    
    def set_encounter(self, state: str):
        """Set encounter marker on the selected tile: 'safe', 'danger', or '' (none)."""
        if not self.selected:
            return
        x, y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            return
        t = self.map.tiles[y][x]
        old = t.encounter
        new = state
        if old == new:
            return
        def do():
            t.encounter = new
        def undo():
            t.encounter = old
        self.history.push(do, undo, label="set_encounter")

    def _rebuild_scroll_items(self):
        items: List[Tuple] = []
        if not self.selected:
            self.scroll_list.set_items([]); return
        x,y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            self.scroll_list.set_items([]); return
        t = self.map.tiles[y][x]
        # NPCs
        for i, e in enumerate(t.npcs):
            name = e.get('name','(unnamed)')
            sub  = e.get('subcategory','')
            ident = e.get('id','')
            label = name
            details = {
                'kv': [
                    'Type: NPC',
                    f"Subcategory: {sub}" if sub else "Subcategory: -",
                    f"ID: {ident}" if ident else "ID: -",
                ],
                'desc': e.get('description','') or '',
            }
            items.append((label, lambda i=i: self._record_remove_list_entry(t.npcs, i, 'rem_npc'), details))
        # Items
        for i, e in enumerate(t.items):
            name = e.get('name','(unnamed)')
            sub  = e.get('subcategory','')
            ident = e.get('id','')
            label = name
            details = {
                'kv': [
                    'Type: Item',
                    f"Subcategory: {sub}" if sub else "Subcategory: -",
                    f"ID: {ident}" if ident else "ID: -",
                ],
                'desc': e.get('description','') or '',
            }
            items.append((label, lambda i=i: self._record_remove_list_entry(t.items, i, 'rem_item'), details))
        # Link (max 1)
        for i, e in enumerate(t.links):
            label = f"Link → {e.get('target_map','?')} #{e.get('target_entry','')}"
            items.append((label, lambda i=i: self._record_remove_list_entry(t.links, i, 'rem_link')))
        self.scroll_list.set_items(items)

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

    # ---------- note modal ----------
    def open_note_modal(self):
        if not self.selected:
            return
        x,y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            return
        t = self.map.tiles[y][x]
        text = t.note if t.note else (self.map.description or "")
        self.note_modal_area.text = text
        self.note_modal_open = True

    def close_note_modal(self):
        self.note_modal_open = False

    def save_note_modal(self):
        if not self.selected:
            self.note_modal_open = False
            return
        x,y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            self.note_modal_open = False
            return
        t = self.map.tiles[y][x]
        new_text = self.note_modal_area.text
        old_text = t.note
        if new_text == old_text:
            self.note_modal_open = False
            return
        def do():
            t.note = new_text
        def undo():
            t.note = old_text
        self.history.push(do, undo, label="set_tile_note")
        self.note_modal_open = False

    # ---------- tooltip helpers ----------
    def _hovered_tile(self) -> Optional[Tuple[int,int]]:
        canvas_rect = self.canvas_rect
        mx, my = get_mouse_pos()
        if not canvas_rect.collidepoint((mx, my)):
            return None
        return self.screen_to_tile(mx, my)

    def _draw_link_tooltip(self, surf):
        # Hide while modal or dropdowns open, or while drawing/panning
        if self.note_modal_open or self.any_dropdown_open() or self.left_dragging or self.panning:
            return
        tpos = self._hovered_tile()
        if not tpos:
            return
        x, y = tpos
        t = self.map.tiles[y][x]
        if not t.links:
            return
        link = t.links[0]
        target_map = link.get("target_map", "?")
        target_entry = link.get("target_entry", "")
        lines = [f"Link: {target_map}"]
        if target_entry:
            lines.append(f"Entry: {target_entry}")

        pad = 8
        line_h = FONT.get_height()
        w = max(FONT.size(s)[0] for s in lines) + pad*2
        h = line_h * len(lines) + pad*2 + (len(lines)-1)*2

        mx, my = get_mouse_pos()
        x0 = mx + 16
        y0 = my + 16
        sw, sh = surf.get_size()
        if x0 + w > sw: x0 = sw - w - 4
        if y0 + h > sh: y0 = sh - h - 4

        tip = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(tip, TOOLTIP_BG_RGBA, tip.get_rect(), border_radius=8)
        pygame.draw.rect(tip, TOOLTIP_BORDER, tip.get_rect(), 1, border_radius=8)

        yy = pad
        for s in lines:
            tip.blit(FONT.render(s, True, TOOLTIP_TEXT), (pad, yy))
            yy += line_h + 2

        surf.blit(tip, (x0, y0))

    # ---------- render ----------
    def draw_canvas(self, surf):
        # Update layout and use current canvas rect
        self._apply_layout(surf)
        canvas_rect = self.canvas_rect
        pygame.draw.rect(surf, CANVAS_BG, canvas_rect)
        clip = surf.get_clip()
        surf.set_clip(canvas_rect)

        # grid + tiles
        for y in range(self.map.height):
            for x in range(self.map.width):
                r = self.tile_rect(x,y)
                color = (LIGHT_WALKABLE if (x+y)%2==0 else DARK_WALKABLE) if self.map.tiles[y][x].walkable else IMPASSABLE
                pygame.draw.rect(surf, color, r)
                # draw texture if present
                try:
                    tex_name = getattr(self.map.tiles[y][x], 'texture', "")
                    if tex_name:
                        key = (tex_name, self.tile_size)
                        tex = self._tex_scaled.get(key)
                        if tex is None:
                            base = self._tex_images.get(tex_name)
                            if base is None:
                                # lazy-load if missing from initial cache
                                path = os.path.join(TILE_IMG_DIR, tex_name)
                                if os.path.exists(path):
                                    base = pygame.image.load(path).convert_alpha()
                                    self._tex_images[tex_name] = base
                            if base is not None:
                                tex = pygame.transform.smoothscale(base, (r.w, r.h))
                                self._tex_scaled[key] = tex
                        if tex is not None:
                            surf.blit(tex, (r.x, r.y))
                except Exception:
                    pass
                pygame.draw.rect(surf, GRID_LINE, r, 1)
                # encounter tint overlay
                if self.map.tiles[y][x].encounter:
                    tint = SAFE_TINT_RGBA if self.map.tiles[y][x].encounter == 'safe' else DANGER_TINT_RGBA
                    tint_surf = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                    tint_surf.fill(tint)
                    surf.blit(tint_surf, (r.x, r.y))

        # overlays (centered colored dots)
        for y in range(self.map.height):
            for x in range(self.map.width):
                t = self.map.tiles[y][x]
                r = self.tile_rect(x,y)

                # collect dot categories
                has = set()
                for e in t.npcs:
                    sub = (e.get("subcategory") or "").lower()
                    if sub == "allies":   has.add("ally")
                    elif sub == "enemies":  has.add("enemy")
                    elif sub == "citizens": has.add("citizen")
                    elif sub == "monsters": has.add("monster")
                    elif sub == "animals":  has.add("animal")
                if any((it.get("subcategory","").lower()=="quest_items") for it in t.items):
                    has.add("quest_item")
                if any((it.get("subcategory","").lower()!="quest_items") for it in t.items):
                    has.add("item")
                if t.links:
                    has.add("link")

                order = ["enemy","ally","citizen","monster","animal","quest_item","item","link"]
                dots = [TYPE_DOT_COLORS[k] for k in order if k in has]

                if dots:
                    pad = max(2, self.tile_size // 16)
                    n = len(dots)
                    # Determine row distribution (centered), with special-cases
                    if n <= 2:
                        row_counts = [n]  # 1 or 2 side-by-side
                    else:
                        rows = math.ceil(math.sqrt(n))
                        base = n // rows
                        extra = n % rows
                        # Put smaller rows on top for triangle-like layouts (e.g., 3 => [1,2])
                        row_counts = [base] * (rows - extra) + [base + 1] * extra
                    rows_count = len(row_counts)
                    max_cols = max(row_counts)
                    # Compute radius to fit all rows/cols with padding, but cap to a friendly max
                    avail_w = self.tile_size - 2 * pad
                    avail_h = self.tile_size - 2 * pad
                    gap = max(2, self.tile_size // 16)
                    if max_cols > 0:
                        r_w = (avail_w - (max_cols - 1) * gap) / (2 * max_cols)
                    else:
                        r_w = self.tile_size // 8
                    if rows_count > 0:
                        r_h = (avail_h - (rows_count - 1) * gap) / (2 * rows_count)
                    else:
                        r_h = self.tile_size // 8
                    radius = int(max(2, min(r_w, r_h, self.tile_size // 8)))
                    gap_x = 2 * radius + gap
                    gap_y = 2 * radius + gap
                    # Vertical start so rows are centered
                    total_h = rows_count * (2 * radius) + (rows_count - 1) * gap
                    start_y = r.y + (r.h - total_h) // 2 + radius
                    idx = 0
                    for ri, count in enumerate(row_counts):
                        # Center columns within the row
                        total_w = count * (2 * radius) + (count - 1) * gap
                        start_x = r.x + (r.w - total_w) // 2 + radius
                        cy = start_y + ri * gap_y
                        for cj in range(count):
                            if idx >= n: break
                            cx = start_x + cj * gap_x
                            col = dots[idx]
                            pygame.draw.circle(surf, (10,10,12), (int(cx), int(cy)), radius+1)
                            pygame.draw.circle(surf, col,        (int(cx), int(cy)), radius)
                            idx += 1

        # selection outline
        if self.selected and (0 <= self.selected[0] < self.map.width) and (0 <= self.selected[1] < self.map.height):
            r = self.tile_rect(*self.selected)
            pygame.draw.rect(surf, ACCENT, r, 2)

        surf.set_clip(clip)

    def draw_top_bar(self, surf):
        w, _h = surf.get_size()
        pygame.draw.rect(surf, PANEL_BG, (0,0,w,50))
        draw_text(surf, "Name:", (14, 18), TEXT_DIM)
        draw_text(surf, "Size W×H:", (520, 18), TEXT_DIM)
        self.name_inp.draw(surf)
        self.btn_save.draw(surf); self.btn_back.draw(surf)
        self.btn_undo.draw(surf); self.btn_redo.draw(surf)
        self.resize_w_inp.draw(surf); self.resize_h_inp.draw(surf); self.btn_resize.draw(surf)
        self.btn_cycle_left_mode.draw(surf)

    def draw_right_panel(self, surf):
        # Ensure layout up to date and use anchored sidebar rect
        self._apply_layout(surf)
        sidebar = self.sidebar_rect
        pygame.draw.rect(surf, PANEL_BG, sidebar); pygame.draw.rect(surf, GRID_LINE, sidebar, 1)

        # categories area (adders)
        self.btn_cat_npcs.draw(surf); self.btn_cat_items.draw(surf); self.btn_cat_links.draw(surf)
        label_x = self.sidebar_rect.x + 20
        label_y = self.sidebar_rect.y + 110
        if self.category == "NPCs":
            draw_text(surf, "Subcategory", (label_x, label_y), TEXT_DIM)
            self.dd_npc_sub.draw_base(surf)
            self.list_box.draw(surf)
            self.btn_add_to_tile.draw(surf)
        elif self.category == "Items":
            draw_text(surf, "Subcategory", (label_x, label_y), TEXT_DIM)
            self.dd_item_sub.draw_base(surf)
            self.list_box.draw(surf)
            self.btn_add_to_tile.draw(surf)
        else:
            draw_text(surf, "Target Map", (label_x, label_y), TEXT_DIM)
            self.dd_link_map.draw_base(surf)
            draw_text(surf, "Target Entry (opt)", (self.link_entry_inp.rect.x, label_y), TEXT_DIM)
            self.link_entry_inp.draw(surf)
            self.btn_add_link.draw(surf)

        # texture selector (visible for texture mode)
        if self.left_click_mode == "texture":
            draw_text(surf, "Texture", (label_x, self.dd_texture.rect.y - 20), TEXT_DIM)
            self.dd_texture.draw_base(surf)
            # Mini preview box next to dropdown
            prev_rect = pygame.Rect(self.dd_texture.rect.right + 8, self.dd_texture.rect.y, self.dd_texture.rect.h, self.dd_texture.rect.h)
            pygame.draw.rect(surf, PANEL_BG_DARK, prev_rect, border_radius=6)
            pygame.draw.rect(surf, GRID_LINE, prev_rect, 1, border_radius=6)
            tex_name = getattr(self.dd_texture, 'value', "")
            if tex_name:
                try:
                    key = (tex_name, prev_rect.h)
                    tex = self._tex_scaled.get(key)
                    if tex is None:
                        base = self._tex_images.get(tex_name)
                        if base is None:
                            path = os.path.join(TILE_IMG_DIR, tex_name)
                            if os.path.exists(path):
                                base = pygame.image.load(path).convert_alpha()
                                self._tex_images[tex_name] = base
                        if base is not None:
                            tex = pygame.transform.smoothscale(base, (prev_rect.w, prev_rect.h))
                            self._tex_scaled[key] = tex
                    if tex is not None:
                        surf.blit(tex, (prev_rect.x, prev_rect.y))
                except Exception:
                    pass

        # inspector header & scroll list (Tile Info)
        pygame.draw.rect(surf, PANEL_BG_DARK, self.inspector_header_rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.inspector_header_rect, 1, border_radius=8)
        x0 = self.inspector_header_rect.x + 8
        y0 = self.inspector_header_rect.y + 8
        draw_text(surf, "Tile Info", (x0, y0), TEXT_MAIN, FONT_BOLD)
        # encounter buttons removed
        if self.selected and (0 <= self.selected[0] < self.map.width) and (0 <= self.selected[1] < self.map.height):
            x,y = self.selected
            t = self.map.tiles[y][x]
            note_preview = (t.note[:24] + "…") if (t.note and len(t.note) > 24) else (t.note or "")
            enc = (" • Safe" if t.encounter=='safe' else (" • Danger" if t.encounter=='danger' else ""))
            draw_text(surf, f"({x},{y}) — {'Passable' if t.walkable else 'Impassable'}{enc}  {(' • ' + note_preview) if note_preview else ''}", (x0+110, y0), TEXT_DIM)

        self._rebuild_scroll_items()
        self.scroll_list.draw(surf)

        # Note button
        self.btn_edit_note.draw(surf)

        # description (placed at bottom; no overlaps)
        draw_text(surf, "Map Description", (self.desc_area.rect.x, self.desc_area.rect.y - 18), TEXT_DIM)
        self.desc_area.draw(surf)

        # dropdown popups last so they overlay
        if self.category == "NPCs":
            self.dd_npc_sub.draw_popup(surf)
        elif self.category == "Items":
            self.dd_item_sub.draw_popup(surf)
        else:
            self.dd_link_map.draw_popup(surf)
        # texture dropdown popup
        if self.left_click_mode == "texture":
            self.dd_texture.draw_popup(surf)

    def draw(self, surf):
        self._apply_layout(surf)
        surf.fill(PAPER_BG)
        # draw in order: canvas, right panel, top bar
        self.draw_canvas(surf)
        self.draw_right_panel(surf)
        self.draw_top_bar(surf)

        # hover tooltip for link (after panels, before modal)
        self._draw_link_tooltip(surf)

        # NOTE MODAL on top of everything
        if self.note_modal_open:
            overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
            overlay.fill((0,0,0,160))
            surf.blit(overlay, (0,0))
            panel = pygame.Rect(320, 180, 640, 360)
            pygame.draw.rect(surf, PANEL_BG, panel, border_radius=8)
            pygame.draw.rect(surf, GRID_LINE, panel, 1, border_radius=8)
            draw_text(surf, "Tile Note (saved per tile)", (panel.x+16, panel.y+12), TEXT_MAIN, FONT_BOLD)
            self.note_modal_area.draw(surf)
            self.note_btn_save.draw(surf)
            self.note_btn_cancel.draw(surf)

    def handle(self, event):
        # if modal is open, only it handles input
        if self.note_modal_open:
            self.note_modal_area.handle(event)
            self.note_btn_save.handle(event)
            self.note_btn_cancel.handle(event)
            return

        # Ensure layout is up-to-date for hit testing
        self._apply_layout(self.app.screen)

        # hotkeys
        if event.type == pygame.KEYDOWN:
            if (event.key == pygame.K_z) and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.history.undo()
            elif (event.key == pygame.K_y) and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                self.history.redo()
            elif event.key == pygame.K_s:
                self.cycle_left_mode()
            elif event.key == pygame.K_ESCAPE:
                # cancel painting batch if stuck
                if self.painting_batch_active:
                    self.history.end_batch()
                    self.painting_batch_active = False
                    self.painting_button = None
                self.left_dragging = False

        # top
        self.name_inp.handle(event)
        self.btn_save.handle(event); self.btn_back.handle(event)
        self.btn_undo.handle(event); self.btn_redo.handle(event)
        self.resize_w_inp.handle(event); self.resize_h_inp.handle(event); self.btn_resize.handle(event)
        self.btn_cycle_left_mode.handle(event)

        # right panel (adders)
        self.btn_cat_npcs.handle(event); self.btn_cat_items.handle(event); self.btn_cat_links.handle(event)

        # dropdowns first; when any is open, swallow other clicks under them
        if self.category == "NPCs":
            self.dd_npc_sub.handle(event)
        elif self.category == "Items":
            self.dd_item_sub.handle(event)
        else:
            self.dd_link_map.handle(event)
        # texture dropdown input
        if self.left_click_mode == "texture":
            self.dd_texture.handle(event)

        dropdown_open = self.any_dropdown_open()

        # If dropdown open, don't let other widgets under receive clicks
        if not dropdown_open:
            if self.category in ("NPCs","Items"):
                self.list_box.handle(event); self.btn_add_to_tile.handle(event)
            else:
                self.link_entry_inp.handle(event); self.btn_add_link.handle(event)

        # inspector / scroll list
        if not dropdown_open:
            self.scroll_list.handle(event)
            self.btn_edit_note.handle(event)

        # description
        if not dropdown_open:
            self.desc_area.handle(event)

        # canvas interactions
        self._apply_layout(self.app.screen)
        canvas_rect = self.canvas_rect

        # Middle mouse panning
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2 and canvas_rect.collidepoint(event.pos):
            self.panning = True
            self.pan_start = event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self.panning = False
        elif event.type == pygame.MOUSEMOTION and self.panning:
            mx, my = event.pos
            dx = mx - self.pan_start[0]
            dy = my - self.pan_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.pan_start = (mx, my)

        # Select/Paint modes
        if event.type == pygame.MOUSEBUTTONDOWN and canvas_rect.collidepoint(event.pos):
            if self.left_click_mode == "select":
                if event.button == 1:
                    t = self.screen_to_tile(*event.pos)
                    if t:
                        self.selected = t            
            elif self.left_click_mode == "safety":
                if event.button in (1, 3):
                    self.left_dragging = True
                    self.painting_button = event.button
                if not self.painting_batch_active:
                    self.painting_batch_active = True
                    self.history.begin_batch("safety_drag")
                t = self.screen_to_tile(*event.pos)
                if t:
                    state = 'danger' if event.button == 3 else 'safe'
                    self._record_set_encounter(*t, state, batch=True)
                    self.selected = t
            elif self.left_click_mode == "paint":
# Walls mode
                if event.button in (1,3):
                    self.left_dragging = True
                    self.painting_button = event.button
                    if not self.painting_batch_active:
                        self.painting_batch_active = True
                        self.history.begin_batch("paint_drag")
                    to_walk = False if event.button == 3 else True
                    t = self.screen_to_tile(*event.pos)
                    if t:
                        self._record_tile_walkable(*t, to_walk, batch=True)
                        self.selected = t
            elif self.left_click_mode == "texture":
                if event.button in (1,3):
                    self.left_dragging = True
                    self.painting_button = event.button
                    if not self.painting_batch_active:
                        self.painting_batch_active = True
                        self.history.begin_batch("texture_drag")
                    t = self.screen_to_tile(*event.pos)
                    if t:
                        if event.button == 3:
                            self._record_set_texture(*t, "", batch=True)
                        else:
                            tex = getattr(self.dd_texture, 'value', "")
                            if tex:
                                self._record_set_texture(*t, tex, batch=True)
                        self.selected = t

        elif event.type == pygame.MOUSEMOTION and self.left_dragging and self.left_click_mode == "paint":
            t = self.screen_to_tile(*event.pos)
            if t:
                to_walk = False if self.painting_button == 3 else True
                self._record_tile_walkable(*t, to_walk, batch=True)
                self.selected = t

        elif event.type == pygame.MOUSEMOTION and self.left_dragging and self.left_click_mode == "safety":
                t = self.screen_to_tile(*event.pos)
                if t:
                    state = 'danger' if getattr(self, 'painting_button', 1) == 3 else 'safe'
                    self._record_set_encounter(*t, state, batch=True)
                    self.selected = t

        elif event.type == pygame.MOUSEMOTION and self.left_dragging and self.left_click_mode == "texture":
                t = self.screen_to_tile(*event.pos)
                if t:
                    if getattr(self, 'painting_button', 1) == 3:
                        self._record_set_texture(*t, "", batch=True)
                    else:
                        tex = getattr(self.dd_texture, 'value', "")
                        if tex:
                            self._record_set_texture(*t, tex, batch=True)
                    self.selected = t



        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1,3):
            if self.painting_batch_active:
                self.history.end_batch()
                self.painting_batch_active = False
                self.painting_button = None
            self.left_dragging = False

        elif event.type == pygame.MOUSEWHEEL:
            mouse_x, mouse_y = get_mouse_pos()
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
        if self.note_modal_open:
            self.note_modal_area.update(dt)

# -------------------- ListBox --------------------
class ListBox:
    def __init__(self, rect):
        self.rect = pygame.Rect(rect)
        self.items: List[str] = []
        self.selected = -1
        self.scroll = 0
        self.item_h = 24
        self.spacing = 6
    def set_items(self, items: List[str]):
        self.items = items
        self.selected = -1 if not items else 0
        self.scroll = 0
    def get_selected(self):
        if 0 <= self.selected < len(self.items):
            return self.items[self.selected]
        return None
    def index_at_pos(self, pos: Tuple[int,int]) -> Optional[int]:
        x,y = pos
        if not self.rect.collidepoint((x,y)):
            return None
        y0 = self.rect.y - self.scroll
        for i, _ in enumerate(self.items):
            row_y = y0 + i * (self.item_h + self.spacing)
            row_rect = pygame.Rect(self.rect.x+6, row_y, self.rect.w-12, self.item_h)
            if row_rect.collidepoint((x,y)):
                return i
        return None
    def handle(self, event):
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(get_mouse_pos()):
                # Clamp scroll so it stops at the end of the list
                content_h = len(self.items) * (self.item_h + self.spacing)
                max_scroll = max(0, content_h - self.rect.h)
                self.scroll = max(0, min(max_scroll, self.scroll - event.y * 24))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.rect.collidepoint(event.pos):
                return
            x, y = event.pos
            y0 = self.rect.y - self.scroll
            for i, _ in enumerate(self.items):
                row_y = y0 + i * (self.item_h + self.spacing)
                row_rect = pygame.Rect(self.rect.x+6, row_y, self.rect.w-12, self.item_h)
                if row_rect.collidepoint((x,y)):
                    self.selected = i
                    break
    def draw(self, surf):
        pygame.draw.rect(surf, PANEL_BG_DARK, self.rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=8)
        clip = surf.get_clip()
        surf.set_clip(self.rect)
        y0 = self.rect.y - self.scroll
        try:
            mx, my = get_mouse_pos()
        except Exception:
            mx, my = pygame.mouse.get_pos()
        for i, label in enumerate(self.items):
            row_y = y0 + i * (self.item_h + self.spacing)
            row_rect = pygame.Rect(self.rect.x+6, row_y, self.rect.w-12, self.item_h)
            hovered = row_rect.collidepoint((mx, my))
            base = BTN_HOVER if (hovered or i == self.selected) else PANEL_BG
            pygame.draw.rect(surf, base, row_rect, border_radius=6)
            draw_text(surf, label[:60], (row_rect.x+8, row_rect.y+4))
        surf.set_clip(clip)

# -------------------- WorldScreen (world layout viewer) --------------------
class WorldScreen:
    def __init__(self, app):
        self.app = app
        self.screen = app.screen
        self.cell = 128
        self.margin = 60
        self.dragging = None  # map name being dragged
        self.drag_offset = (0, 0)
        self.selected_idx = 0

        # Load maps from manifest
        manifest = read_json_any(MANIFEST, {"maps": []})
        self.maps = [m.get("name") or m.get("file") for m in manifest.get("maps", [])]
        # Fallback: empty
        if not self.maps:
            self.maps = []

        # Load world layout
        self.world_path = os.path.join(DATA_DIR, "world_map.json")
        wm = read_json_any(self.world_path, {"layout": {}, "start": {"map":"","entry": None, "pos": [0,0]}})
        layout = wm.get("layout", {})
        # Build layout dict of map -> (x,y)
        self.layout: Dict[str, Tuple[int,int]] = {}
        # Default positions if missing: arrange in a row
        for i, name in enumerate(self.maps):
            pos = layout.get(name)
            if isinstance(pos, dict):
                self.layout[name] = (int(pos.get("x", i)), int(pos.get("y", 0)))
            else:
                self.layout[name] = (i, 0)

    def save(self):
        data = {
            "schema": "rpgen.world@1",
            "version": "0.2",
            "layout": { name: {"x": x, "y": y} for name, (x,y) in self.layout.items() },
            "start": {"map": self.maps[self.selected_idx] if self.maps else "", "entry": None, "pos": [0,0]},
        }
        write_json(self.world_path, data)

    def handle(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.goto_start()
            elif event.key == pygame.K_s:
                self.save()
            elif event.key == pygame.K_TAB and self.maps:
                self.selected_idx = (self.selected_idx + 1) % len(self.maps)
            elif self.maps:
                name = self.maps[self.selected_idx]
                x, y = self.layout.get(name, (0,0))
                moved = False
                if event.key == pygame.K_LEFT:
                    x -= 1; moved = True
                elif event.key == pygame.K_RIGHT:
                    x += 1; moved = True
                elif event.key == pygame.K_UP:
                    y -= 1; moved = True
                elif event.key == pygame.K_DOWN:
                    y += 1; moved = True
                if moved:
                    self.layout[name] = (x, y)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for i, name in enumerate(self.maps):
                x, y = self.layout.get(name, (0,0))
                rect = pygame.Rect(self.margin + x*self.cell, self.margin + y*self.cell, self.cell-8, self.cell-8)
                if rect.collidepoint((mx, my)):
                    self.selected_idx = i
                    self.dragging = name
                    self.drag_offset = (mx - rect.x, my - rect.y)
                    break
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging is not None:
                # snap to grid
                mx, my = event.pos
                gx = int(round((mx - self.margin - self.drag_offset[0]) / self.cell))
                gy = int(round((my - self.margin - self.drag_offset[1]) / self.cell))
                self.layout[self.dragging] = (gx, gy)
            self.dragging = None
        elif event.type == pygame.MOUSEMOTION and self.dragging is not None:
            # live preview is drawn in draw()
            pass

    def draw(self, surf):
        surf.fill(PAPER_BG)
        draw_text(surf, "World Layout (S=Save, Tab=Next, Esc=Back)", (20, 10), TEXT_MAIN, FONT_BOLD)
        # draw grid
        w, h = surf.get_size()
        for gx in range(self.margin, w, self.cell):
            pygame.draw.line(surf, GRID_LINE, (gx, self.margin), (gx, h-20))
        for gy in range(self.margin, h, self.cell):
            pygame.draw.line(surf, GRID_LINE, (self.margin, gy), (w-20, gy))

        # draw maps
        for i, name in enumerate(self.maps):
            x, y = self.layout.get(name, (0,0))
            rx = self.margin + x*self.cell
            ry = self.margin + y*self.cell
            rect = pygame.Rect(rx, ry, self.cell-8, self.cell-8)
            col = ACCENT if i == self.selected_idx else BTN_BG
            pygame.draw.rect(surf, col, rect, border_radius=12)
            pygame.draw.rect(surf, GRID_LINE, rect, 1, border_radius=12)
            draw_text(surf, name, (rect.x+8, rect.y+8))

# -------------------- App --------------------
class App:
    def __init__(self):
        # Window surface (draw directly; keep UI pixel size constant)
        # Create a normal resizable window, then maximize via OS (Windows)
        self.screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        try:
            import ctypes
            hwnd = pygame.display.get_wm_info().get('window')
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        except Exception:
            pass
        pygame.display.set_caption("RPGenesis - Map Editor (Pygame)")
        self.clock = pygame.time.Clock()
        self.running = True
        self.start_screen = StartScreen(self)
        self.editor_screen: Optional[EditorScreen] = None
        self.world_screen: Optional[WorldScreen] = None
    def goto_start(self):
        self.editor_screen = None
        self.world_screen = None
    def goto_editor(self, mapdata: MapData):
        self.editor_screen = EditorScreen(self, mapdata)
        self.world_screen = None
    def goto_world(self):
        self.world_screen = WorldScreen(self)
        self.editor_screen = None
    def run(self):
        while self.running:
            dt = self.clock.tick(60)
            # Use raw mouse/window coordinates (no global scaling); UI remains constant pixel size
            set_mouse_pos_provider(None)

            for event in pygame.event.get():
                # Handle window close / resize
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                else:
                    if self.editor_screen:
                        self.editor_screen.handle(event)
                    elif self.world_screen:
                        self.world_screen.handle(event)
                    else:
                        self.start_screen.handle(event)

            # Draw directly to the window surface (no global scaling)
            if self.editor_screen:
                self.editor_screen.update(dt)
                self.editor_screen.draw(self.screen)
            elif self.world_screen:
                self.world_screen.draw(self.screen)
            else:
                self.start_screen.update(dt)
                self.start_screen.draw(self.screen)
            pygame.display.flip()

# ---------- main ----------
if __name__ == "__main__":
    App().run()
