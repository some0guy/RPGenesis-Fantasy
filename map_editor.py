
import os
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable

import pygame

# Safe mouse position helper for wheel/hover hit-testing across modules
def get_mouse_pos() -> Tuple[int, int]:
    try:
        return pygame.mouse.get_pos()
    except Exception:
        return (0, 0)

# -------------------- Paths & constants --------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
MAP_DIR  = os.path.join(DATA_DIR, "maps")
NPC_DIR  = os.path.join(DATA_DIR, "npcs")
ITEM_DIR = os.path.join(DATA_DIR, "items")
MANIFEST = os.path.join(MAP_DIR, "maps.json")
TILE_IMG_DIR = os.path.join(ROOT_DIR, "assets", "images", "map_tiles")

os.makedirs(MAP_DIR, exist_ok=True)

NPC_SUBCATS   = ["allies", "enemies", "monsters", "animals", "citizens", "villains"]
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

# Edge outline colors for outer map boundary
EDGE_DARK  = DARK_WALKABLE  # inner dark stroke
EDGE_LIGHT = GRID_LINE      # thin light outline

# Encounter tint (RGBA)
SAFE_TINT_RGBA   = (50, 180, 90, 60)
DANGER_TINT_RGBA = (200, 70, 70, 60)

# Dot colors
COL_RED    = (220,70,70)     # enemies
COL_GREEN  = (80,200,120)    # allies
COL_BLUE   = (80,150,240)    # citizens
COL_PURPLE = (170,110,240)   # monsters
COL_VIOLET = (190,120,255)   # villains
COL_YELLOW = (245,210,80)    # animals
COL_WHITE  = (240,240,240)   # items (non-quest)
COL_ORANGE = (255,160,70)    # quest items
COL_PINK   = (255,105,180)   # links (hot pink)

TYPE_DOT_COLORS = {
    "ally": COL_GREEN,
    "enemy": COL_RED,
    "villain": COL_VIOLET,
    "citizen": COL_BLUE,
    "monster": COL_PURPLE,
    "animal": COL_YELLOW,
    "item": COL_WHITE,
    "quest_item": COL_ORANGE,
    "link": COL_PINK,
}

# Rarity colors (match in-game RARITY_COLORS)
RARITY_COLORS = {
    'common':    (200, 200, 210),
    'uncommon':  (80, 200, 120),
    'rare':      (80, 150, 240),
    'exotic':    (170, 110, 240),
    'legendary': (255, 160, 70),
    'mythic':    (245, 210, 80),
}
CHEST_RARITIES = ["common","uncommon","rare","exotic","legendary","mythic"]

# Tooltip colors
TOOLTIP_BG_RGBA = (20, 22, 26, 220)  # dark with alpha
TOOLTIP_BORDER  = GRID_LINE
TOOLTIP_TEXT    = TEXT_MAIN

# -------------------- Isometric settings --------------------
# Angle of the diamond's side relative to the horizontal, in degrees.
# Match the in-game renderer projection so editor looks identical
# Game uses 35° tilt and -25° rotation (see RPGenesis-Fantasy.py)
ISO_ANGLE_DEG: float = 35.0
ISO_ROT_DEG: float = -25.0
# Extrusion depth for cube sides relative to tile size
CUBE_DEPTH_PCT: float = 0.35

# Dot layout tuning for editor view (should mirror game for consistency)
DOT_EDGE_INSET: float = 0.12  # fraction inset from tile edges
DOT_SPACING_SCALE: float = 0.88  # compact rows/cols toward center
DOT_SIZE_SCALE: float = 0.88    # visual size scale for dots

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
    chests: List[Dict[str, Any]] = field(default_factory=list)  # list of {'rarity': str}
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
                "chests": t.chests,
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
                    chests=list(cell.get("chests", [])),
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
        self.scroll_index = 0
        self.max_visible = 6
        self.popup_indices: List[int] = []
        self._popup_area: Optional[pygame.Rect] = None
        self._popup_has_scroll: bool = False
        self._scrollbar_w: int = 8
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
                if not self.opened:
                    self.scroll_index = 0
                self.opened = not self.opened
            elif self.opened:
                for idx, r in zip(self.popup_indices, self.popup_rects):
                    if r.collidepoint(event.pos):
                        self.value = self.options[idx]
                        if self.on_change:
                            self.on_change(self.value)
                        break
                self.opened = False
        elif event.type == pygame.MOUSEWHEEL and self.opened:
            try:
                mx, my = get_mouse_pos()
            except Exception:
                mx, my = pygame.mouse.get_pos()
            if self._popup_area and self._popup_area.collidepoint((mx, my)):
                if event.y > 0:
                    self.scroll_index = max(0, self.scroll_index - 1)
                elif event.y < 0:
                    max_start = max(0, len(self.options) - max(1, self.max_visible))
                    self.scroll_index = min(max_start, self.scroll_index + 1)
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
        self.popup_indices.clear()
        self._popup_area = None
        self._popup_has_scroll = False
        if not self.opened: return
# fmt: off
        screen_h = surf.get_height()
        needed_h = self.rect.h * len(self.options)
        below_space = screen_h - self.rect.bottom
        self.popup_upwards = below_space < needed_h
        visible_max = max(1, self.max_visible)
        available_h = below_space if not self.popup_upwards else self.rect.top
        if available_h <= 0:
            available_h = self.rect.h * visible_max
        max_rows_fit = max(1, min(visible_max, available_h // max(1, self.rect.h)))
        visible_count = min(len(self.options), max_rows_fit)
        max_start = max(0, len(self.options) - visible_count)
        self.scroll_index = max(0, min(self.scroll_index, max_start))
        start_idx = self.scroll_index
        end_idx = min(len(self.options), start_idx + visible_count)
        indices = list(range(start_idx, end_idx))

        needs_scroll = len(self.options) > visible_count
        self._popup_has_scroll = needs_scroll
        row_width = self.rect.w - (self._scrollbar_w if needs_scroll else 0)

        rect_pairs: List[Tuple[int, pygame.Rect]] = []
        if self.popup_upwards:
            y = self.rect.top - self.rect.h
            for idx in reversed(indices):
                rect_pairs.append((idx, pygame.Rect(self.rect.x, y, row_width, self.rect.h)))
                y -= self.rect.h
            rect_pairs.reverse()
        else:
            y = self.rect.bottom
            for idx in indices:
                rect_pairs.append((idx, pygame.Rect(self.rect.x, y, row_width, self.rect.h)))
                y += self.rect.h

        for idx, rect in rect_pairs:
            self.popup_indices.append(idx)
            self.popup_rects.append(rect)

        if self.popup_rects:
            top_y = min(r.top for r in self.popup_rects)
            bottom_y = max(r.bottom for r in self.popup_rects)
            area_width = row_width + (self._scrollbar_w if needs_scroll else 0)
            self._popup_area = pygame.Rect(self.rect.x, top_y, area_width, bottom_y - top_y)
# fmt: on
    def draw_popup(self, surf):
        if not self.opened: return
        # Compute hover based on current mouse position for immediate feedback
        try:
            mx, my = get_mouse_pos()
        except Exception:
            mx, my = pygame.mouse.get_pos()
        for r, idx in zip(self.popup_rects, self.popup_indices):
            hovered = r.collidepoint((mx, my))
            pygame.draw.rect(surf, BTN_HOVER if hovered else PANEL_BG, r)
            pygame.draw.rect(surf, GRID_LINE, r, 1)
            x = r.x + 8
            if self.get_icon:
                try:
                    size = max(12, r.h - 8)
                    ico = self.get_icon(self.options[idx], size)
                    if ico is not None:
                        y = r.y + (r.h - ico.get_height()) // 2
                        surf.blit(ico, (x, y))
                        x += ico.get_width() + 6
                except Exception:
                    pass
            draw_text(surf, self.options[idx], (x, r.y+6))

        if self._popup_has_scroll and self._popup_area:
            area = self._popup_area
            bar_rect = pygame.Rect(area.right - self._scrollbar_w + 1, area.top, self._scrollbar_w - 2, area.height)
            pygame.draw.rect(surf, PANEL_BG, bar_rect)
            pygame.draw.rect(surf, GRID_LINE, bar_rect.inflate(2, 0), 1)
            track_height = max(4, bar_rect.height - 4)
            total = max(1, len(self.options))
            visible = max(1, len(self.popup_indices))
            thumb_height = max(8, int(track_height * (visible / total)))
            max_start = max(1, total - visible)
            offset = 0 if max_start == 0 else int((track_height - thumb_height) * (self.scroll_index / max_start))
            thumb = pygame.Rect(bar_rect.x, bar_rect.y + 2 + offset, bar_rect.width, thumb_height)
            pygame.draw.rect(surf, BTN_BG, bar_rect)
            pygame.draw.rect(surf, ACCENT, thumb, border_radius=2)

class ScrollListWithButtons:
    """Scrollable list that renders labels with Remove buttons; provides wheel scrolling.
       Also exposes index_at_pos() to support right-click context menus."""
    def __init__(self, rect: pygame.Rect):
        self.rect = pygame.Rect(rect)
        # Each entry: (label, on_remove, color_opt)
        self.items: List[Tuple[str, Callable[[], None], Optional[Tuple[int,int,int]]]] = []
        self.scroll = 0
        self.item_h = 24
        self.spacing = 6
    def set_items(self, items):
        # Normalize items to (label, on_remove, color)
        norm: List[Tuple[str, Callable[[], None], Optional[Tuple[int,int,int]]]] = []
        for it in (items or []):
            if not isinstance(it, (list, tuple)):
                continue
            if len(it) == 2:
                label, on_remove = it
                color = None
            else:
                label, on_remove, color = it[0], it[1], it[2] if len(it) >= 3 else None
            norm.append((str(label), on_remove, color if (isinstance(color, (list, tuple)) and len(color)>=3) else None))
        self.items = norm
        self.scroll = 0
    def index_at_pos(self, pos: Tuple[int,int]) -> Optional[int]:
        x,y = pos
        if not self.rect.collidepoint((x,y)):
            return None
        y_start = self.rect.y - self.scroll
        for i in range(len(self.items)):
            row_y = y_start + i * (self.item_h + self.spacing)
            row_rect = pygame.Rect(self.rect.x+6, row_y, self.rect.w-12, self.item_h)
            if row_rect.collidepoint((x, y)):
                return i
        return None
    def handle(self, event):
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(get_mouse_pos()):
                self.scroll = max(0, self.scroll - event.y * 24)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            x, y = event.pos
            if not self.rect.collidepoint((x, y)):
                return
            y_start = self.rect.y - self.scroll
            for i, (label, on_remove, _color) in enumerate(self.items):
                row_y = y_start + i * (self.item_h + self.spacing)
                row_rect = pygame.Rect(self.rect.x+6, row_y, self.rect.w-12, self.item_h)
                btn_rect = pygame.Rect(row_rect.right-70, row_rect.y, 64, self.item_h)
                if btn_rect.collidepoint((x, y)):
                    on_remove()
                    break
    def draw(self, surf):
        pygame.draw.rect(surf, PANEL_BG_DARK, self.rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.rect, 1, border_radius=8)
        clip = surf.get_clip()
        surf.set_clip(self.rect)
        y_start = self.rect.y - self.scroll
        try:
            mx, my = get_mouse_pos()
        except Exception:
            mx, my = pygame.mouse.get_pos()
        for i, (label, _, color) in enumerate(self.items):
            row_y = y_start + i * (self.item_h + self.spacing)
            row_rect = pygame.Rect(self.rect.x+6, row_y, self.rect.w-12, self.item_h)
            hovered = row_rect.collidepoint((mx, my))
            pygame.draw.rect(surf, BTN_HOVER if hovered else PANEL_BG, row_rect, border_radius=6)
            draw_text(surf, label[:60], (row_rect.x+8, row_rect.y+4), color=color or TEXT_MAIN)
            btn_rect = pygame.Rect(row_rect.right-70, row_rect.y, 64, self.item_h)
            pygame.draw.rect(surf, DANGER, btn_rect, border_radius=6)
            draw_text(surf, "Remove", (btn_rect.x+6, btn_rect.y+4))
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
        def _scan_maps_dir() -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            try:
                if not os.path.isdir(MAP_DIR):
                    return out
                for fn in sorted(os.listdir(MAP_DIR)):
                    if not fn.lower().endswith('.json'):
                        continue
                    if fn.lower() == 'world_map.json':
                        # Do not include the world map in the selectable list
                        continue
                    path = os.path.join(MAP_DIR, fn)
                    doc = read_json_any(path, None)
                    if not isinstance(doc, dict):
                        continue
                    # Heuristic to detect a map document
                    is_world = bool(doc.get('layout')) and 'start' in doc
                    has_grid = isinstance(doc.get('tiles'), list) and isinstance(doc.get('width'), int) and isinstance(doc.get('height'), int)
                    if is_world or not has_grid:
                        # skip non-map or malformed documents
                        if is_world:
                            continue
                    entry = {
                        'file': fn,
                        'name': str(doc.get('name') or os.path.splitext(fn)[0] or 'Untitled'),
                        'description': str(doc.get('description') or ''),
                        'width': int(doc.get('width') or 0),
                        'height': int(doc.get('height') or 0),
                    }
                    out.append(entry)
            except Exception:
                pass
            return out

        # Prefer manifest when available, but fall back to directory scan
        manifest = read_json_any(MANIFEST, {"maps": []})
        maps = manifest.get("maps") if isinstance(manifest, dict) else []
        if not isinstance(maps, list) or not maps:
            maps = _scan_maps_dir()
        self.maps = maps or []
        labels = [f"{m.get('name','(unnamed)')} - {m.get('file','?')}" for m in self.maps]
        self.maps_list.set_items(labels)
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
        # Auto-fit is optional; default off so mouse wheel zoom works normally
        self.auto_fit: bool = False
        self.zoom_scale: float = 0.80  # used only when auto_fit is True
        # Default to top-down (face-down) view; no isometric projection
        self.view_iso: bool = False

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

        # cursor mode: Select / Walls / Safety (simplified)
        self.left_click_mode = "select"
        self.btn_cycle_left_mode = Button((1010, 12, 180, 28), "Mode: Select", self.cycle_left_mode)

        # Top bar label positions (computed during layout)
        self._label_name_pos: Tuple[int, int] = (14, 18)
        self._label_size_pos: Tuple[int, int] = (520, 18)

        # right panel categories (adders)
        self.category = "NPCs"
        self.btn_cat_npcs  = Button((920, 60, 140, 30), "NPCs",  lambda: self._switch_category("NPCs"))
        self.btn_cat_items = Button((920, 95, 140, 30), "Items", lambda: self._switch_category("Items"))
        self.btn_cat_chests= Button((920, 130, 140, 30), "Chests", lambda: self._switch_category("Chests"))
        self.btn_cat_links = Button((920, 165, 140, 30), "Links", lambda: self._switch_category("Links"))

        # NPCs / Items lists
        self.dd_npc_sub  = Dropdown((920, 215, 140, 26), NPC_SUBCATS,  value=NPC_SUBCATS[0], on_change=lambda v: self._reload_npcs())
        self.dd_item_sub = Dropdown((920, 215, 140, 26), ITEM_SUBCATS, value=ITEM_SUBCATS[0], on_change=lambda v: self._reload_items())
        # Chests controls: rarity dropdown + add button
        self.dd_chest_rarity = Dropdown((920, 215, 160, 26), CHEST_RARITIES, value=CHEST_RARITIES[0], on_change=None)
        self.btn_add_chest   = Button((920, 250, 160, 28), "Add Chest to Selected", self.add_chest_to_selected)
        self.list_box = ListBox((920, 248, 340, 160))
        self.btn_add_to_tile      = Button((920, 414, 160, 28), "Add to Selected", self.add_selected_to_tile)

        # Initialize entry caches to avoid AttributeError before first reload
        self.npc_entries: List[Dict[str, Any]] = []
        self.item_entries: List[Dict[str, Any]] = []

        # Links (no arming; add directly to selected tile) — enforce max 1
        self.maps_available = [f for f in os.listdir(MAP_DIR) if f.lower().endswith(".json")]
        link_default = self.maps_available[0] if self.maps_available else ""
        self.dd_link_map = Dropdown((920, 215, 220, 26), self.maps_available, value=link_default, on_change=None)
        self.link_entry_inp = TextInput((1150, 215, 110, 26), "")
        self.btn_add_link   = Button((920, 248, 180, 28), "Add Link to Tile", self.add_link_to_selected)

        # no diamond masks needed in simplified Top view

        # Tile Info (scrollable list)
        self.inspector_header_rect = pygame.Rect(900, 450, 380, 32)
        self.scroll_list = ScrollListWithButtons(pygame.Rect(900, 484, 380, 140))  # wheel scrollable
        self.btn_edit_note    = Button((900, 630, 120, 26), "Edit Note", self.open_note_modal)
        # Encounter marker controls
        self.btn_mark_safe    = Button((900, 454, 110, 26), "Mark Safe", lambda: self.set_encounter('safe'))
        self.btn_mark_danger  = Button((1016, 454, 130, 26), "Mark Danger", lambda: self.set_encounter('danger'))
        self.btn_clear_marker = Button((1152, 454, 128, 26), "Clear", lambda: self.set_encounter(''))

        # Map description at bottom
        self.desc_area = TextArea((900, 662, 380, 48), self.map.description)

        # Game start placement (world start)
        self.btn_set_start = Button((920, 448, 200, 28), "Set Game Start Here", self.set_game_start_here)
        self._world_start_info = None

        # Sidebar layout caches
        self._sidebar_inner_left: int = 0
        self._sidebar_inner_width: int = 0
        self._section_rect_npc = pygame.Rect(0,0,0,0)
        self._section_rect_items = pygame.Rect(0,0,0,0)
        self._section_rect_chests = pygame.Rect(0,0,0,0)
        self._section_rect_links = pygame.Rect(0,0,0,0)
        self._label_pos_npc: Tuple[int,int] = (0,0)
        self._label_pos_items: Tuple[int,int] = (0,0)
        self._label_pos_chests: Tuple[int,int] = (0,0)
        self._label_pos_links: Tuple[int,int] = (0,0)
        self._label_pos_link_entry: Tuple[int,int] = (0,0)
        self._game_start_label_pos: Tuple[int,int] = (0,0)
        self._game_start_status_pos: Tuple[int,int] = (0,0)

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
    # Iso/Top toggle removed for simplified editor
    # Texture icon helper removed in simplified Top view

    # diamond mask helper removed in simplified Top view

    def _apply_layout(self, surf):
        w, h = surf.get_size()
        top_h = 50
        sb_w = 380
        # Sidebar flush to right edge, canvas fills the rest from left edge
        self.sidebar_rect = pygame.Rect(max(0, w - sb_w), top_h, sb_w, max(0, h - top_h))
        self.canvas_rect = pygame.Rect(0, top_h, max(0, w - sb_w), max(0, h - top_h))

        # Top bar controls laid out sequentially from left to right
        top_y = 12
        btn_spacing = 10

        self.btn_cycle_left_mode.rect.topleft = (max(0, w - self.btn_cycle_left_mode.rect.w - 16), top_y)
        mode_left_edge = self.btn_cycle_left_mode.rect.x - 12

        label_name = "Name:"
        label_size = "Size W x H:"
        label_name_w = FONT.size(label_name)[0]
        label_size_w = FONT.size(label_size)[0]

        name_input_height = self.name_inp.rect.height
        label_name_x = 14
        label_name_y = top_y + max(0, (name_input_height - FONT.get_height()) // 2)
        self._label_name_pos = (label_name_x, label_name_y)

        button_sequence = (self.btn_save, self.btn_back, self.btn_undo, self.btn_redo)
        total_button_width = sum(btn.rect.width for btn in button_sequence)
        total_button_spacing = btn_spacing * len(button_sequence)
        total_size_controls = label_size_w + 8 + self.resize_w_inp.rect.width + 6 + self.resize_h_inp.rect.width + 10 + self.btn_resize.rect.width
        name_input_min = 140
        required_after_name = total_button_width + total_button_spacing + total_size_controls + btn_spacing
        max_name_width = mode_left_edge - (label_name_x + label_name_w + 8 + required_after_name)
        if max_name_width < name_input_min:
            max_name_width = name_input_min
        name_input_width = max(name_input_min, min(self.name_inp.rect.width, max_name_width))
        self.name_inp.rect.size = (name_input_width, name_input_height)
        self.name_inp.rect.topleft = (label_name_x + label_name_w + 8, top_y)

        x_cursor = self.name_inp.rect.right + btn_spacing
        for btn in button_sequence:
            if x_cursor + btn.rect.width > mode_left_edge:
                x_cursor = mode_left_edge - btn.rect.width
            btn.rect.topleft = (x_cursor, top_y)
            x_cursor = btn.rect.right + btn_spacing

        label_size_x = max(self.btn_redo.rect.right + btn_spacing, mode_left_edge - total_size_controls)
        if label_size_x < self.btn_redo.rect.right + btn_spacing:
            label_size_x = self.btn_redo.rect.right + btn_spacing
        label_size_y = top_y + max(0, (self.resize_w_inp.rect.height - FONT.get_height()) // 2)
        self._label_size_pos = (label_size_x, label_size_y)

        self.resize_w_inp.rect.topleft = (label_size_x + label_size_w + 8, top_y)
        self.resize_h_inp.rect.topleft = (self.resize_w_inp.rect.right + 6, top_y)
        self.btn_resize.rect.topleft = (self.resize_h_inp.rect.right + 10, top_y)

        apply_right = self.btn_resize.rect.right
        if apply_right > mode_left_edge:
            shift = apply_right - mode_left_edge
            self.resize_w_inp.rect.x -= shift
            self.resize_h_inp.rect.x -= shift
            self.btn_resize.rect.x -= shift
            label_size_x -= shift
            self._label_size_pos = (label_size_x, label_size_y)

        # Sidebar widgets (responsive vertical layout)
        inner_margin = 10
        inner_left = self.sidebar_rect.x + inner_margin
        inner_width = max(60, self.sidebar_rect.w - inner_margin * 2)
        self._sidebar_inner_left = inner_left
        self._sidebar_inner_width = inner_width
        y = self.sidebar_rect.y + 12

        cat_height = 30
        cat_spacing = 6
        for btn in (self.btn_cat_npcs, self.btn_cat_items, self.btn_cat_chests, self.btn_cat_links):
            btn.rect.topleft = (inner_left, y)
            btn.rect.size = (inner_width, cat_height)
            y += cat_height + cat_spacing
        y += 6
        categories_bottom = y

        dropdown_h = 26
        button_h = 28
        label_h = FONT_BOLD.get_linesize()

        # Category controls (all positioned; only the active category is drawn)
        panel_top = categories_bottom + 10

        dropdown_y = panel_top + label_h + 6
        self.dd_npc_sub.rect.topleft = (inner_left, dropdown_y)
        self.dd_npc_sub.rect.size = (inner_width, dropdown_h)

        self.dd_item_sub.rect.topleft = (inner_left, dropdown_y)
        self.dd_item_sub.rect.size = (inner_width, dropdown_h)

        self.dd_chest_rarity.rect.topleft = (inner_left, dropdown_y)
        self.dd_chest_rarity.rect.size = (inner_width, dropdown_h)
        self.btn_add_chest.rect.topleft = (inner_left, self.dd_chest_rarity.rect.bottom + 12)
        self.btn_add_chest.rect.size = (inner_width, button_h)

        self.dd_link_map.rect.topleft = (inner_left, dropdown_y)
        self.dd_link_map.rect.size = (inner_width, dropdown_h)
        link_entry_label_y = self.dd_link_map.rect.bottom + 10
        self.link_entry_inp.rect.topleft = (inner_left, link_entry_label_y + label_h + 4)
        self.link_entry_inp.rect.size = (inner_width, self.link_entry_inp.rect.height)
        self.btn_add_link.rect.topleft = (inner_left, self.link_entry_inp.rect.bottom + 10)
        self.btn_add_link.rect.size = (inner_width, button_h)

        # List section (NPCs/Items)
        list_top = self.dd_npc_sub.rect.bottom + 12
        self.list_box.rect.topleft = (inner_left, list_top)
        self.list_box.rect.size = (inner_width, 160)
        self.btn_add_to_tile.rect.size = (inner_width, button_h)

        # Bottom-aligned sections
        bottom_y = self.sidebar_rect.bottom - 16
        desc_height = max(60, min(140, int(self.sidebar_rect.height * 0.22)))
        self.desc_area.rect = pygame.Rect(inner_left, bottom_y - desc_height, inner_width, desc_height)
        bottom_y = self.desc_area.rect.top - 12

        note_h = self.btn_edit_note.rect.height
        self.btn_edit_note.rect.size = (inner_width, note_h)
        self.btn_edit_note.rect.topleft = (inner_left, bottom_y - note_h)
        bottom_y = self.btn_edit_note.rect.top - 16

        # Game start block
        game_start_height = self.btn_set_start.rect.height + 48
        game_start_top = bottom_y - game_start_height
        self._game_start_label_pos = (inner_left, game_start_top)
        self._game_start_status_pos = (inner_left, game_start_top + 18)
        self.btn_set_start.rect.size = (inner_width, self.btn_set_start.rect.height)
        self.btn_set_start.rect.topleft = (inner_left, game_start_top + 36)
        bottom_y = game_start_top - 16

        # Tile info block calculations
        tileinfo_bottom = bottom_y
        btn_row_h = self.btn_mark_safe.rect.height
        header_h = 32
        scroll_min = 60
        tileinfo_min_height = header_h + 6 + btn_row_h + 8 + scroll_min
        tileinfo_top = max(self.sidebar_rect.y + 140, tileinfo_bottom - tileinfo_min_height)

        list_max_height = max(100, int(self.sidebar_rect.height * 0.25))
        available_before_tileinfo = max(0, tileinfo_top - list_top)
        add_btn_h = self.btn_add_to_tile.rect.height
        list_height = max(0, available_before_tileinfo - (add_btn_h + 8))
        list_height = min(list_height, list_max_height)
        self.list_box.rect.size = (inner_width, list_height)
        add_btn_y = list_top + list_height + 8
        max_add_y = tileinfo_top - add_btn_h - 6
        if add_btn_y > max_add_y:
            add_btn_y = max(list_top, max_add_y)
            list_height = max(0, add_btn_y - list_top - 8)
            self.list_box.rect.height = list_height
        self.btn_add_to_tile.rect.topleft = (inner_left, add_btn_y)
        self.btn_add_to_tile.rect.size = (inner_width, add_btn_h)

        control_bottom = max(
            self.btn_add_to_tile.rect.bottom,
            self.btn_add_chest.rect.bottom,
            self.btn_add_link.rect.bottom,
            self.list_box.rect.bottom,
            self.link_entry_inp.rect.bottom,
        )
        tileinfo_top = max(tileinfo_top, control_bottom + 16)
        tileinfo_min_height = max(220, int(self.sidebar_rect.height * 0.36))
        tileinfo_top = min(tileinfo_top, tileinfo_bottom - tileinfo_min_height)
        tileinfo_height = max(tileinfo_min_height, tileinfo_bottom - tileinfo_top)

        self.inspector_header_rect = pygame.Rect(inner_left, tileinfo_top, inner_width, header_h)
        btn_row_y = self.inspector_header_rect.bottom + 6
        row_width = inner_width
        btn_spacing = 6
        btn_w = max(60, (row_width - 2 * btn_spacing) // 3)
        last_w = max(60, row_width - (btn_w * 2 + btn_spacing * 2))

        self.btn_mark_safe.rect.update(inner_left, btn_row_y, btn_w, btn_row_h)
        self.btn_mark_danger.rect.update(inner_left + btn_w + btn_spacing, btn_row_y, btn_w, btn_row_h)
        self.btn_clear_marker.rect.update(inner_left + (btn_w + btn_spacing) * 2, btn_row_y, last_w, btn_row_h)

        scroll_top = self.btn_mark_safe.rect.bottom + 8
        scroll_height = max(80, tileinfo_min_height - (header_h + 6 + btn_row_h + 8), tileinfo_bottom - scroll_top)
        self.scroll_list.rect = pygame.Rect(inner_left, scroll_top, inner_width, scroll_height)

        # Store label positions for each category section
        label_offset = 18
        self._label_pos_npc = (inner_left, panel_top)
        self._label_pos_items = (inner_left, panel_top)
        self._label_pos_chests = (inner_left, panel_top)
        self._label_pos_links = (inner_left, panel_top)
        self._label_pos_link_entry = (inner_left, link_entry_label_y)

        # Section rectangles for category panels
        section_pad = 8
        npc_top = min(panel_top, self.dd_npc_sub.rect.y - 12)
        npc_bottom = max(self.btn_add_to_tile.rect.bottom, self.list_box.rect.bottom) + 8
        height_npc = max(40, npc_bottom - npc_top)
        self._section_rect_npc = pygame.Rect(inner_left - section_pad//2, npc_top - section_pad//2,
                                             inner_width + section_pad, height_npc + section_pad)
        self._section_rect_items = self._section_rect_npc.copy()

        chest_top = min(panel_top, self.dd_chest_rarity.rect.y - 12)
        chest_bottom = self.btn_add_chest.rect.bottom + 8
        height_chest = max(36, chest_bottom - chest_top)
        self._section_rect_chests = pygame.Rect(inner_left - section_pad//2, chest_top - section_pad//2,
                                                inner_width + section_pad, height_chest + section_pad)

        link_top = min(panel_top, self.dd_link_map.rect.y - 12)
        link_bottom = self.btn_add_link.rect.bottom + 8
        height_link = max(36, link_bottom - link_top)
        self._section_rect_links = pygame.Rect(inner_left - section_pad//2, link_top - section_pad//2,
                                               inner_width + section_pad, height_link + section_pad)

    def any_dropdown_open(self) -> bool:
        return (
            self.dd_npc_sub.is_open() or self.dd_item_sub.is_open() or self.dd_link_map.is_open() or self.dd_chest_rarity.is_open()
        )

    def cycle_left_mode(self):
        modes = ["select", "paint", "safety"]
        idx = modes.index(self.left_click_mode)
        self.left_click_mode = modes[(idx+1)%len(modes)]
        label = {
            "select":"Mode: Select",
            "paint":"Mode: Walls",
            "safety":"Mode: Safety",
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
        elif label == "Chests":
            self.list_box.set_items([])
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

    # texture editing removed in simplified view

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

    def add_chest_to_selected(self):
        # Ensure we have a target tile: prefer selected; else try hovered
        if not self.selected:
            tpos = self._hovered_tile()
            if tpos:
                self.selected = tpos
        if not self.selected:
            return
        x, y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            return
        t = self.map.tiles[y][x]
        rarity = str(self.dd_chest_rarity.value or 'common').lower()
        entry = {"rarity": rarity}
        self._record_add_list_entry(t.chests, entry, "add_chest")
        # refresh sidebar list immediately
        self._rebuild_scroll_items()

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

    def set_game_start_here(self):
        if not self.selected:
            return
        x, y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            return
        wm_path = os.path.join(MAP_DIR, "world_map.json")
        wm = read_json_any(wm_path, {"schema":"rpgen.world@1","version":"0.2","layout": {}, "start": {"map":"","entry": None, "pos": [0,0]}})
        start = wm.get("start", {}) if isinstance(wm, dict) else {}
        smap = start.get("map") or ""
        # Only one start globally; prevent setting if another map already has it
        if smap and smap != self.map.name:
            return
        wm["start"] = {"map": self.map.name, "entry": None, "pos": [int(x), int(y)]}
        write_json(wm_path, wm)

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
        items: List[Tuple[str, Callable[[], None], Optional[Tuple[int,int,int]]]] = []
        if not self.selected:
            self.scroll_list.set_items([]); return
        x,y = self.selected
        if not (0 <= x < self.map.width and 0 <= y < self.map.height):
            self.scroll_list.set_items([]); return
        t = self.map.tiles[y][x]
        # NPCs
        for i, e in enumerate(t.npcs):
            label = f"{e.get('name','(unnamed)')} [{e.get('id','')}] <{e.get('subcategory','')}>"
            items.append((label, lambda i=i: self._record_remove_list_entry(t.npcs, i, 'rem_npc'), None))
        # Items
        for i, e in enumerate(t.items):
            label = f"{e.get('name','(unnamed)')} [{e.get('id','')}] <{e.get('subcategory','')}>"
            items.append((label, lambda i=i: self._record_remove_list_entry(t.items, i, 'rem_item'), None))
        # Chests
        try:
            for i, c in enumerate(getattr(t, 'chests', []) or []):
                rar = str((c.get('rarity') or 'common')).lower()
                clabel = f"Chest - {rar.capitalize()}"
                color = RARITY_COLORS.get(rar, TEXT_MAIN)
                items.append((clabel, lambda i=i: self._record_remove_list_entry(t.chests, i, 'rem_chest'), color))
        except Exception:
            pass
        # Link (max 1)
        for i, e in enumerate(t.links):
            label = f"Link → {e.get('target_map','?')} #{e.get('target_entry','')}"
            items.append((label, lambda i=i: self._record_remove_list_entry(t.links, i, 'rem_link'), None))
        self.scroll_list.set_items(items)

    # ---------- canvas geometry (isometric + rotation) ----------
    def _basis(self) -> Tuple[float, float, float, float]:
        """Return basis vectors (exx,exy,eyx,eyy) mapping tile steps to screen.

        Incorporates tilt via ISO_ANGLE_DEG and rotation via ISO_ROT_DEG.
        Without rotation, the top face diamond has width tile_w and height tile_h,
        where tile_h = tile_w * tan(angle). Basis at 0° rot: ex=(+w/2, +h/2), ey=(-w/2, +h/2).
        """
        tile_w = float(int(self.tile_size))
        # Face-down straight view: axis-aligned squares
        if not getattr(self, 'view_iso', True):
            return tile_w, 0.0, 0.0, tile_w
        # compute top diamond height from angle (guard against extreme small)
        ang_pitch = max(1e-3, math.radians(float(ISO_ANGLE_DEG)))
        tile_h = max(1.0, tile_w * math.tan(ang_pitch))
        hx, hy = tile_w * 0.5, tile_h * 0.5
        # base (no rotation)
        ex0x, ex0y = +hx, +hy
        ey0x, ey0y = -hx, +hy
        # apply rotation
        ang_rot = math.radians(float(ISO_ROT_DEG))
        ca, sa = math.cos(ang_rot), math.sin(ang_rot)
        exx = ca * ex0x - sa * ex0y
        exy = sa * ex0x + ca * ex0y
        eyx = ca * ey0x - sa * ey0y
        eyy = sa * ey0x + ca * ey0y
        return exx, exy, eyx, eyy

    def _iso_dims(self) -> Tuple[int, int, float, float]:
        """Return (tile_w, tile_h, half_w, half_h) for top diamond face.

        tile_h is derived from ISO_ANGLE_DEG as tile_h = tile_w * tan(angle).
        """
        tile_w = int(self.tile_size)
        if not getattr(self, 'view_iso', True):
            tile_h = tile_w
        else:
            ang_pitch = max(1e-3, math.radians(float(ISO_ANGLE_DEG)))
            tile_h = max(1, int(round(tile_w * math.tan(ang_pitch))))
        return tile_w, tile_h, tile_w * 0.5, tile_h * 0.5

    def _iso_center(self, x: float, y: float) -> Tuple[float, float]:
        exx, exy, eyx, eyy = self._basis()
        cx = self.offset_x + (x + 0.5) * exx + (y + 0.5) * eyx
        cy = self.offset_y + (x + 0.5) * exy + (y + 0.5) * eyy
        return cx, cy

    def tile_poly(self, x: int, y: int) -> List[Tuple[int,int]]:
        exx, exy, eyx, eyy = self._basis()
        cx, cy = self._iso_center(x, y)
        p0 = (int(cx - 0.5*exx - 0.5*eyx), int(cy - 0.5*exy - 0.5*eyy))
        p1 = (int(cx + 0.5*exx - 0.5*eyx), int(cy + 0.5*exy - 0.5*eyy))
        p2 = (int(cx + 0.5*exx + 0.5*eyx), int(cy + 0.5*exy + 0.5*eyy))
        p3 = (int(cx - 0.5*exx + 0.5*eyx), int(cy - 0.5*exy + 0.5*eyy))
        return [p0, p1, p2, p3]

    def tile_rect(self, x: int, y: int) -> pygame.Rect:
        """Axis-aligned tile rect in Top view."""
        tile_w = int(self.tile_size)
        return pygame.Rect(int(self.offset_x + x*tile_w), int(self.offset_y + y*tile_w), tile_w, tile_w)

    def _screen_to_world_float(self, sx: int, sy: int) -> Tuple[float, float]:
        """Fractional tile coords (x,y) relative to grid, Top view."""
        tile_w = float(int(self.tile_size))
        u = (sx - self.offset_x) / tile_w
        v = (sy - self.offset_y) / tile_w
        return (u - 0.5), (v - 0.5)

    def _point_in_tile(self, x: int, y: int, sx: int, sy: int) -> bool:
        return self.tile_rect(x, y).collidepoint((sx, sy))

    def screen_to_tile(self, sx: int, sy: int) -> Optional[Tuple[int,int]]:
        tile_w = int(self.tile_size)
        if tile_w <= 0:
            return None
        tx = int(math.floor((sx - self.offset_x) / float(tile_w)))
        ty = int(math.floor((sy - self.offset_y) / float(tile_w)))
        if 0 <= tx < self.map.width and 0 <= ty < self.map.height:
            return (tx, ty)
        return None

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
    def _auto_fit_view(self, surf):
        """Center and scale the canvas to mirror the game but more zoomed out.

        Uses (W+H) diamond extent heuristic like the in-game renderer and
        centers the grid within the canvas area. Disabled while panning.
        """
        if not self.auto_fit or self.panning:
            return
        # Fit full map within canvas with margins
        W, H = int(self.map.width), int(self.map.height)
        if W <= 0 or H <= 0:
            return
        canvas_rect = self.canvas_rect
        margin = 16
        avail_w = max(1, canvas_rect.w - 2*margin)
        avail_h = max(1, canvas_rect.h - 2*margin)

        # Match game: tile_h = tile_w * tan(angle); target extent ~= (W+H)
        ang_pitch = max(1e-3, math.radians(float(ISO_ANGLE_DEG)))
        target = max(1, W + H)
        tw_by_w = avail_w / float(target)
        tw_by_h = (2.0 * avail_h) / (float(target) * math.tan(ang_pitch))
        tw_raw = max(1.0, min(tw_by_w, tw_by_h))
        tw = int(max(TILE_MIN, min(TILE_MAX, tw_raw * float(self.zoom_scale))))
        # Only update if changed to avoid jitter
        if tw != int(self.tile_size):
            self.tile_size = tw

        # Center the grid by computing its bounding box at offset=(0,0)
        # and shifting so center matches canvas center.
        exx, exy, eyx, eyy = self._basis()
        def center_xy(ix:int, iy:int):
            cx = (ix + 0.5) * exx + (iy + 0.5) * eyx
            cy = (ix + 0.5) * exy + (iy + 0.5) * eyy
            return cx, cy
        corners = [
            center_xy(0, 0),
            center_xy(W-1, 0),
            center_xy(W-1, H-1),
            center_xy(0, H-1),
        ]
        # Each tile’s top diamond extends by 0.5*ex and 0.5*ey vectors
        half_ex = (0.5*exx, 0.5*exy)
        half_ey = (0.5*eyx, 0.5*eyy)
        pts = []
        for cx, cy in corners:
            p0 = (cx - half_ex[0] - half_ey[0], cy - half_ex[1] - half_ey[1])
            p1 = (cx + half_ex[0] - half_ey[0], cy + half_ex[1] - half_ey[1])
            p2 = (cx + half_ex[0] + half_ey[0], cy + half_ex[1] + half_ey[1])
            p3 = (cx - half_ex[0] + half_ey[0], cy - half_ex[1] + half_ey[1])
            pts.extend((p0,p1,p2,p3))
        if not pts:
            return
        minx = min(p[0] for p in pts); maxx = max(p[0] for p in pts)
        miny = min(p[1] for p in pts); maxy = max(p[1] for p in pts)
        grid_cx = (minx + maxx) * 0.5
        grid_cy = (miny + maxy) * 0.5
        canvas_cx = canvas_rect.x + canvas_rect.w * 0.5
        canvas_cy = canvas_rect.y + canvas_rect.h * 0.5
        self.offset_x = int(canvas_cx - grid_cx)
        self.offset_y = int(canvas_cy - grid_cy)

    def draw_canvas(self, surf):
        # Update layout and use current canvas rect
        self._apply_layout(surf)
        canvas_rect = self.canvas_rect
        pygame.draw.rect(surf, CANVAS_BG, canvas_rect)
        clip = surf.get_clip()
        surf.set_clip(canvas_rect)
        # Auto-fit view to mirror main game (optional)
        if getattr(self, 'auto_fit', False):
            self._auto_fit_view(surf)

        # Isometric tiles with rotation + 2.5D sides
        tile_w, tile_h, half_w, half_h = self._iso_dims()
        exx, exy, eyx, eyy = self._basis()
        is_iso = bool(getattr(self, 'view_iso', True))
        depth = 0 if not is_iso else max(4, int((tile_h) * CUBE_DEPTH_PCT))
        EDGE_DARK  = (16,18,22)
        EDGE_LIGHT = (92,98,120)

        # Depth-sort tiles by screen-space center Y so farther tiles draw first
        draw_order: List[Tuple[float, int, int]] = []
        for y in range(self.map.height):
            for x in range(self.map.width):
                _cx, cy = self._iso_center(x, y)
                # Use cy (and y as a tie-breaker) for stable sorting
                draw_order.append((cy, y, x))
        draw_order.sort()

        for _cy, y, x in draw_order:
            cx, cy = self._iso_center(x, y)
            # corners of the top square
            p0 = (cx - 0.5*exx - 0.5*eyx, cy - 0.5*exy - 0.5*eyy)
            p1 = (cx + 0.5*exx - 0.5*eyx, cy + 0.5*exy - 0.5*eyy)
            p2 = (cx + 0.5*exx + 0.5*eyx, cy + 0.5*exy + 0.5*eyy)
            p3 = (cx - 0.5*exx + 0.5*eyx, cy - 0.5*exy + 0.5*eyy)

            # Simpler, clearer top-down style: solid fill in Top view
            if not is_iso:
                base_col = LIGHT_WALKABLE if self.map.tiles[y][x].walkable else IMPASSABLE
            else:
                base_col = (LIGHT_WALKABLE if (x+y)%2==0 else DARK_WALKABLE) if self.map.tiles[y][x].walkable else IMPASSABLE

            # sides (extruded downward)
            p0d = (p0[0], p0[1] + depth)
            p1d = (p1[0], p1[1] + depth)
            p2d = (p2[0], p2[1] + depth)
            p3d = (p3[0], p3[1] + depth)
            if is_iso and depth > 0:
                face_r = [(int(p1[0]),int(p1[1])),(int(p2[0]),int(p2[1])),(int(p2d[0]),int(p2d[1])),(int(p1d[0]),int(p1d[1]))]
                face_f = [(int(p2[0]),int(p2[1])),(int(p3[0]),int(p3[1])),(int(p3d[0]),int(p3d[1])),(int(p2d[0]),int(p2d[1]))]
                col_r = (int(base_col[0]*0.85), int(base_col[1]*0.85), int(base_col[2]*0.85))
                col_f = (int(base_col[0]*0.70), int(base_col[1]*0.70), int(base_col[2]*0.70))
                pygame.draw.polygon(surf, col_r, face_r)
                pygame.draw.polygon(surf, col_f, face_f)
                pygame.draw.lines(surf, EDGE_DARK, False, face_r + [face_r[0]], 2)
                pygame.draw.lines(surf, EDGE_DARK, False, face_f + [face_f[0]], 2)

            if not is_iso:
                # Simple top-down fill: draw a solid square, with optional encounter tint
                rect = pygame.Rect(int(cx - half_w), int(cy - half_h), int(tile_w), int(tile_w))
                pygame.draw.rect(surf, base_col, rect)
                # Apply green/red encounter tint for 'safe'/'danger'
                enc = getattr(self.map.tiles[y][x], 'encounter', '')
                if enc:
                    tint = SAFE_TINT_RGBA if enc == 'safe' else DANGER_TINT_RGBA
                    overlay = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
                    overlay.fill(tint)
                    surf.blit(overlay, rect.topleft)
            else:
                # top surface with texture: rotate square then squash vertically to match tilt
                # prepare square top (unrotated)
                square = pygame.Surface((tile_w, tile_w), pygame.SRCALPHA)
                square.fill((0,0,0,0))
                pygame.draw.rect(square, base_col, (0,0,tile_w,tile_w))
                # textures removed in simplified view; use solid color only

                # encounter tint overlay on top surface (pre-rotation)
                enc = self.map.tiles[y][x].encounter
                if enc:
                    tint = SAFE_TINT_RGBA if enc == 'safe' else DANGER_TINT_RGBA
                    tint_surf = pygame.Surface((tile_w, tile_w), pygame.SRCALPHA)
                    tint_surf.fill(tint)
                    square.blit(tint_surf, (0,0))

                # rotate, then vertical squash to match tilt
                rot_deg = float(ISO_ROT_DEG if is_iso else 0.0)
                rotated = pygame.transform.rotate(square, rot_deg) if abs(rot_deg) > 1e-3 else square
                if is_iso and (tile_h != tile_w):
                    ratio = max(0.1, float(tile_h) / float(tile_w))
                    out_w, out_h = rotated.get_size()
                    out = pygame.transform.smoothscale(rotated, (out_w, max(1, int(out_h * ratio))))
                else:
                    out = rotated
                rect = out.get_rect(center=(int(cx), int(cy)))
                surf.blit(out, rect)

            # border + selection accent directly on main surface
            top_poly = [(int(p0[0]),int(p0[1])),(int(p1[0]),int(p1[1])),(int(p2[0]),int(p2[1])),(int(p3[0]),int(p3[1]))]
            if is_iso:
                # Keep a lighter double-stroke for iso
                pygame.draw.polygon(surf, EDGE_DARK, top_poly, 2)
                pygame.draw.polygon(surf, EDGE_LIGHT, top_poly, 1)
            # In Top view, grid is drawn separately after all tiles
            if is_iso and self.selected == (x, y):
                pygame.draw.polygon(surf, ACCENT, top_poly, 2)

        # Draw grid overlay in Top view for clear full borders
        if not is_iso and self.map.width > 0 and self.map.height > 0:
            left = self.tile_rect(0, 0).left
            top = self.tile_rect(0, 0).top
            right = self.tile_rect(self.map.width - 1, 0).right
            bottom = self.tile_rect(0, self.map.height - 1).bottom
            # vertical lines
            for gx in range(self.map.width + 1):
                r0 = self.tile_rect(min(gx, self.map.width - 1), 0)
                xpix = r0.left if gx < self.map.width else r0.right
                pygame.draw.line(surf, GRID_LINE, (xpix, top), (xpix, bottom), 1)
            # horizontal lines
            for gy in range(self.map.height + 1):
                r0 = self.tile_rect(0, min(gy, self.map.height - 1))
                ypix = r0.top if gy < self.map.height else r0.bottom
                pygame.draw.line(surf, GRID_LINE, (left, ypix), (right, ypix), 1)

        # overlays (centered colored dots)
        for y in range(self.map.height):
            for x in range(self.map.width):
                t = self.map.tiles[y][x]
                r = self.tile_rect(x,y)

                # collect dot categories
                has = set()
                for e in t.npcs:
                    sub = (e.get("subcategory") or "").lower()
                    if sub == "allies":      has.add("ally")
                    elif sub == "enemies":   has.add("enemy")
                    elif sub == "villains":  has.add("villain")
                    elif sub == "citizens":  has.add("citizen")
                    elif sub == "monsters":  has.add("monster")
                    elif sub == "animals":   has.add("animal")
                if any((it.get("subcategory","").lower()=="quest_items") for it in t.items):
                    has.add("quest_item")
                if any((it.get("subcategory","").lower()!="quest_items") for it in t.items):
                    has.add("item")
                if t.links:
                    has.add("link")

                order = ["enemy","villain","ally","citizen","monster","animal","quest_item","item","link"]
                # Build marker list with shapes so chest can integrate into grid
                markers: List[Tuple[str, Tuple[int,int,int]]] = []  # (shape, color)
                for k in order:
                    if k in has:
                        markers.append(("circle", TYPE_DOT_COLORS[k]))
                # Include one square marker if any chest present on tile
                try:
                    if len(getattr(t, 'chests', []) or []) > 0:
                        markers.append(("square", COL_WHITE))
                except Exception:
                    pass

                if markers:
                    # Simple markers in rows inside the tile rect
                    pad = max(2, self.tile_size // 16)
                    n = len(markers)
                    max_cols = 3
                    cols = min(max_cols, n)
                    rows = int(math.ceil(n / cols))
                    avail_w = r.w - 2 * pad
                    avail_h = r.h - 2 * pad
                    radius = max(2, int(min(avail_w / (cols * 2.5), avail_h / (rows * 2.5), self.tile_size // 8) * float(DOT_SIZE_SCALE)))
                    gap_x = max(2, int((avail_w - cols * 2 * radius) / max(1, cols - 1))) if cols > 1 else 0
                    gap_y = max(2, int((avail_h - rows * 2 * radius) / max(1, rows - 1))) if rows > 1 else 0
                    start_x = r.x + (r.w - (cols * (2 * radius) + (cols - 1) * gap_x)) // 2 + radius
                    start_y = r.y + (r.h - (rows * (2 * radius) + (rows - 1) * gap_y)) // 2 + radius
                    for i, mk in enumerate(markers):
                        row_i = i // cols
                        col_i = i % cols
                        cx_d = start_x + col_i * (2 * radius + gap_x)
                        cy_d = start_y + row_i * (2 * radius + gap_y)
                        shape, colr = mk
                        if shape == "square":
                            side = max(4, 2 * radius - 2)
                            rx = int(cx_d - side // 2)
                            ry = int(cy_d - side // 2)
                            pygame.draw.rect(surf, colr, (rx, ry, side, side))
                            pygame.draw.rect(surf, (10,10,12), (rx, ry, side, side), 1)
                        else:
                            pygame.draw.circle(surf, colr, (int(cx_d), int(cy_d)), radius)
                            pygame.draw.circle(surf, (10,10,12), (int(cx_d), int(cy_d)), radius, 1)

        # Selection highlight on top in Top view (clear and obvious)
        # Highlight Game Start tile (blue outline)
        try:
            wm_path = os.path.join(MAP_DIR, "world_map.json")
            wm = read_json_any(wm_path, {"start": {"map":"","entry": None, "pos": [0,0]}})
            start = wm.get("start", {}) if isinstance(wm, dict) else {}
            smap = start.get("map") or ""
            spos = start.get("pos") or [0,0]
            if smap == self.map.name and isinstance(spos, (list, tuple)) and len(spos) >= 2:
                sx, sy = int(spos[0]), int(spos[1])
                if 0 <= sx < self.map.width and 0 <= sy < self.map.height:
                    exx, exy, eyx, eyy = self._basis()
                    cx, cy = self._iso_center(sx, sy)
                    p0 = (cx - 0.5*exx - 0.5*eyx, cy - 0.5*exy - 0.5*eyy)
                    p1 = (cx + 0.5*exx - 0.5*eyx, cy + 0.5*exy - 0.5*eyy)
                    p2 = (cx + 0.5*exx + 0.5*eyx, cy + 0.5*exy + 0.5*eyy)
                    p3 = (cx - 0.5*exx + 0.5*eyx, cy - 0.5*exy + 0.5*eyy)
                    poly = [(int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (int(p3[0]), int(p3[1]))]
                    BLUE = (80, 150, 240)
                    pygame.draw.polygon(surf, BLUE, poly, 3)
        except Exception:
            pass

        if (not is_iso) and self.selected and (0 <= self.selected[0] < self.map.width) and (0 <= self.selected[1] < self.map.height):
            rx, ry = self.selected
            r = self.tile_rect(rx, ry)
            hl = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            hl.fill((ACCENT[0], ACCENT[1], ACCENT[2], 60))
            surf.blit(hl, (r.x, r.y))
            pygame.draw.rect(surf, ACCENT, r, 2)

        surf.set_clip(clip)

    def draw_top_bar(self, surf):
        w, _h = surf.get_size()
        pygame.draw.rect(surf, PANEL_BG, (0,0,w,50))
        draw_text(surf, "Name:", self._label_name_pos, TEXT_DIM)
        draw_text(surf, "Size W x H:", self._label_size_pos, TEXT_DIM)
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
        self.btn_cat_npcs.draw(surf); self.btn_cat_items.draw(surf); self.btn_cat_chests.draw(surf); self.btn_cat_links.draw(surf)
        inner_left = self._sidebar_inner_left
        if self.category == "NPCs":
            pygame.draw.rect(surf, PANEL_BG_DARK, self._section_rect_npc, border_radius=8)
            pygame.draw.rect(surf, GRID_LINE, self._section_rect_npc, 1, border_radius=8)
            self.dd_npc_sub.draw_base(surf)
            self.list_box.draw(surf)
            self.btn_add_to_tile.draw(surf)
            draw_text(surf, "NPC Subcategory", self._label_pos_npc, TEXT_DIM, FONT_BOLD)
        elif self.category == "Items":
            pygame.draw.rect(surf, PANEL_BG_DARK, self._section_rect_items, border_radius=8)
            pygame.draw.rect(surf, GRID_LINE, self._section_rect_items, 1, border_radius=8)
            self.dd_item_sub.draw_base(surf)
            self.list_box.draw(surf)
            self.btn_add_to_tile.draw(surf)
            draw_text(surf, "Item Subcategory", self._label_pos_items, TEXT_DIM, FONT_BOLD)
        elif self.category == "Chests":
            pygame.draw.rect(surf, PANEL_BG_DARK, self._section_rect_chests, border_radius=8)
            pygame.draw.rect(surf, GRID_LINE, self._section_rect_chests, 1, border_radius=8)
            self.dd_chest_rarity.draw_base(surf)
            self.btn_add_chest.draw(surf)
            draw_text(surf, "Chest Rarity", self._label_pos_chests, TEXT_DIM, FONT_BOLD)
        else:
            pygame.draw.rect(surf, PANEL_BG_DARK, self._section_rect_links, border_radius=8)
            pygame.draw.rect(surf, GRID_LINE, self._section_rect_links, 1, border_radius=8)
            self.dd_link_map.draw_base(surf)
            self.link_entry_inp.draw(surf)
            self.btn_add_link.draw(surf)
            draw_text(surf, "Target Map", self._label_pos_links, TEXT_DIM, FONT_BOLD)
            draw_text(surf, "Target Entry (optional)", self._label_pos_link_entry, TEXT_DIM)

        # texture selector removed in simplified Top view

        # inspector header & scroll list (Tile Info)
        pygame.draw.rect(surf, PANEL_BG_DARK, self.inspector_header_rect, border_radius=8)
        pygame.draw.rect(surf, GRID_LINE, self.inspector_header_rect, 1, border_radius=8)
        x0 = self.inspector_header_rect.x + 8
        y0 = self.inspector_header_rect.y + 8
        draw_text(surf, "Tile Info", (x0, y0), TEXT_MAIN, FONT_BOLD)
        # encounter buttons row between header and list
        self.btn_mark_safe.draw(surf)
        self.btn_mark_danger.draw(surf)
        self.btn_clear_marker.draw(surf)
        if self.selected and (0 <= self.selected[0] < self.map.width) and (0 <= self.selected[1] < self.map.height):
            x,y = self.selected
            t = self.map.tiles[y][x]
            note_preview = (t.note[:24] + "…") if (t.note and len(t.note) > 24) else (t.note or "")
            enc = (" • Safe" if t.encounter=='safe' else (" • Danger" if t.encounter=='danger' else ""))
            draw_text(surf, f"({x},{y}) — {'Passable' if t.walkable else 'Impassable'}{enc}  {(' • ' + note_preview) if note_preview else ''}", (x0+110, y0), TEXT_DIM)

        self._rebuild_scroll_items()
        self.scroll_list.draw(surf)

        # Draw outer map boundary (simplified in Top view)
        if self.map.width > 0 and self.map.height > 0:
            exx, exy, eyx, eyy = self._basis()
            def center_xy(ix:int, iy:int):
                cx, cy = self._iso_center(ix, iy)
                return cx, cy
            c00x, c00y = center_xy(0, 0)
            c10x, c10y = center_xy(self.map.width-1, 0)
            c11x, c11y = center_xy(self.map.width-1, self.map.height-1)
            c01x, c01y = center_xy(0, self.map.height-1)
            p_top    = (c00x - 0.5*exx - 0.5*eyx, c00y - 0.5*exy - 0.5*eyy)
            p_right  = (c10x + 0.5*exx - 0.5*eyx, c10y + 0.5*exy - 0.5*eyy)
            p_bottom = (c11x + 0.5*exx + 0.5*eyx, c11y + 0.5*exy + 0.5*eyy)
            p_left   = (c01x - 0.5*exx + 0.5*eyx, c01y - 0.5*exy + 0.5*eyy)
            map_poly = [(int(p_top[0]), int(p_top[1])), (int(p_right[0]), int(p_right[1])), (int(p_bottom[0]), int(p_bottom[1])), (int(p_left[0]), int(p_left[1]))]
            if getattr(self, 'view_iso', True):
                pygame.draw.polygon(surf, (8,9,12), map_poly, 4)
                pygame.draw.polygon(surf, EDGE_DARK, map_poly, 2)
                pygame.draw.polygon(surf, EDGE_LIGHT, map_poly, 1)
            else:
                pygame.draw.polygon(surf, EDGE_LIGHT, map_poly, 1)

        # Note button
        self.btn_edit_note.draw(surf)

        # Game start UI (info + button) anchored in sidebar above Tile Info
        wm_path = os.path.join(MAP_DIR, "world_map.json")
        wm = read_json_any(wm_path, {"start": {"map":"","entry": None, "pos": [0,0]}})
        start = wm.get("start", {}) if isinstance(wm, dict) else {}
        smap = start.get("map") or ""
        spos = start.get("pos") or [0,0]
        gs_label_x, gs_label_y = self._game_start_label_pos
        draw_text(surf, "Game Start", (gs_label_x, gs_label_y), TEXT_DIM, FONT_BOLD)
        status = f"Placed on: {smap} at ({int(spos[0])},{int(spos[1])})" if smap else "Not set"
        status_x, status_y = self._game_start_status_pos
        draw_text(surf, status, (status_x, status_y), TEXT_MAIN)
        can_set = bool(self.selected) and (not smap or smap == self.map.name)
        if can_set:
            self.btn_set_start.draw(surf)
        else:
            r = self.btn_set_start.rect
            pygame.draw.rect(surf, (38,40,52), r, border_radius=6)
            pygame.draw.rect(surf, GRID_LINE, r, 1, border_radius=6)
            draw_text(surf, "Set Game Start Here", (r.x+10, r.y+6), TEXT_DIM)

        # description (placed at bottom; no overlaps)
        draw_text(surf, "Map Description", (self.desc_area.rect.x, self.desc_area.rect.y - 18), TEXT_DIM)
        self.desc_area.draw(surf)

        # dropdown popups last so they overlay
        if self.category == "NPCs":
            self.dd_npc_sub.draw_popup(surf)
        elif self.category == "Items":
            self.dd_item_sub.draw_popup(surf)
        elif self.category == "Chests":
            self.dd_chest_rarity.draw_popup(surf)
        else:
            self.dd_link_map.draw_popup(surf)
        # no texture dropdown popup in simplified view

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
        self.btn_cat_npcs.handle(event); self.btn_cat_items.handle(event); self.btn_cat_chests.handle(event); self.btn_cat_links.handle(event)

        # dropdowns first; when any is open, swallow other clicks under them
        if self.category == "NPCs":
            self.dd_npc_sub.handle(event)
        elif self.category == "Items":
            self.dd_item_sub.handle(event)
        elif self.category == "Chests":
            self.dd_chest_rarity.handle(event)
        else:
            self.dd_link_map.handle(event)
        # no texture dropdown input in simplified view

        dropdown_open = self.any_dropdown_open()

        # If dropdown open, don't let other widgets under receive clicks
        if not dropdown_open:
            if self.category in ("NPCs","Items"):
                self.list_box.handle(event); self.btn_add_to_tile.handle(event)
            elif self.category == "Chests":
                self.btn_add_chest.handle(event)
            else:
                self.link_entry_inp.handle(event); self.btn_add_link.handle(event)

        # inspector / scroll list
        if event.type == pygame.MOUSEWHEEL or not dropdown_open:
            self.scroll_list.handle(event)
            self.btn_edit_note.handle(event)
            self.btn_mark_safe.handle(event)
            self.btn_mark_danger.handle(event)
            self.btn_clear_marker.handle(event)
            self.btn_set_start.handle(event)

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
            # texture mode removed

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

        # no texture drag handling



        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1,3):
            if self.painting_batch_active:
                self.history.end_batch()
                self.painting_batch_active = False
                self.painting_button = None
            self.left_dragging = False

        elif event.type == pygame.MOUSEWHEEL:
            mouse_x, mouse_y = get_mouse_pos()
            if canvas_rect.collidepoint((mouse_x, mouse_y)):
                # keep the tile under cursor fixed while zooming (top-down)
                old_ts = float(self.tile_size)
                u_old = (mouse_x - self.offset_x) / max(1.0, old_ts)
                v_old = (mouse_y - self.offset_y) / max(1.0, old_ts)
                zoom_factor = 1.1 if event.y > 0 else (1/1.1)
                new_ts = int(max(TILE_MIN, min(TILE_MAX, int(old_ts * zoom_factor))))
                if new_ts != int(old_ts):
                    self.tile_size = new_ts
                    self.offset_x = int(mouse_x - u_old * float(new_ts))
                    self.offset_y = int(mouse_y - v_old * float(new_ts))

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
                self.scroll = max(0, self.scroll - event.y * 24)
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
        self.world_path = os.path.join(MAP_DIR, "world_map.json")
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
