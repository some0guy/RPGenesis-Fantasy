# rpgen_map_loader.py — JSON map loader utilities for RPGenesis-Fantasy
# Drop this alongside RPGenesis-Fantasy.py and import functions below.

from __future__ import annotations
from pathlib import Path
import json
from typing import Dict, Any, Tuple

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
MAPS = DATA / 'maps'
DUNGEONS = DATA / 'dungeons'
WORLD_MAP = DATA / 'world_map.json'

# ---------- JSON helpers ----------
def _jload(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default
    except Exception:
        return default

# ---------- Public API ----------
def load_world_map() -> Dict[str, Any]:
    """Return world_map structure with a simple layout grid.

    Schema (minimal):
    {
      "schema": "rpgen.world@1",
      "version": "0.2",
      "layout": { "<map name>": {"x": int, "y": int}, ... },
      "start": {"map": str, "entry": str|None, "pos": [int,int]}
    }
    """
    wm = _jload(WORLD_MAP, {})
    wm.setdefault('schema', 'rpgen.world@1')
    wm.setdefault('version', '0.2')
    wm.setdefault('layout', {})
    wm.setdefault('start', {'map':'', 'entry': None, 'pos':[0,0]})
    return wm

def load_scene_by_name(kind: str, name: str) -> Dict[str, Any]:
    """Load a JSON scene by kind ('map'|'dungeon') and name."""
    # Accept either bare name or filename with .json
    base = MAPS if kind=='map' else DUNGEONS
    nm = name
    if isinstance(nm, str) and nm.lower().endswith('.json'):
        nm = nm[:-5]
    path = base / f'{nm}.json'
    return _jload(path, {
        'schema':'rpgen.map@1', 'name':name, 'kind':kind, 'biome':'forest', 'safe':False,
        'width':5, 'height':5, 'terrain':[[1]*5 for _ in range(5)],
        'entries':[], 'links':[], 'tiles':{}
    })

def find_entry_coords(scene: Dict[str, Any], entry_name: str|None) -> Tuple[int,int]:
    """Return coordinates for entry_name, or (0,0) fallback."""
    if entry_name:
        for e in scene.get('entries', []):
            if e.get('name') == entry_name:
                return int(e.get('x',0)), int(e.get('y',0))
    if scene.get('entries'):
        e = scene['entries'][0]
        return int(e.get('x',0)), int(e.get('y',0))
    return 0,0

def scene_to_runtime(scene: Dict[str, Any]) -> Dict[str, Any]:
    """Translate scene JSON to a runtime-friendly dict your game can use.

    Supports two schemas:
    1) Legacy scene schema with 'terrain' (2D ints), 'links' list, 'tiles' dict keyed by "x,y".
    2) Map editor schema with 'tiles' as a 2D list of objects containing
       walkable/items/npcs/links/note/encounter.
    """
    w = int(scene.get('width', 5))
    h = int(scene.get('height', 5))

    walk: list[list[bool]]
    # Prefer explicit terrain if present
    if isinstance(scene.get('terrain'), list):
        walk = [[bool(v) for v in row] for row in scene['terrain']]
    else:
        # Try map-editor schema
        tiles_2d = scene.get('tiles')
        if isinstance(tiles_2d, list) and tiles_2d and isinstance(tiles_2d[0], list):
            walk = [[bool((tiles_2d[y][x] or {}).get('walkable', False)) for x in range(w)] for y in range(h)]
        else:
            walk = [[True]*w for _ in range(h)]

    # Build runtime tiles mapping
    tiles: dict[tuple[int,int], dict] = {}
    if isinstance(scene.get('tiles'), dict):
        # legacy dict keyed by "x,y"
        for key, payload in scene['tiles'].items():
            try:
                x_str, y_str = key.split(','); x = int(x_str); y = int(y_str)
            except Exception:
                continue
            npc = payload.get('npc')
            item = payload.get('item')
            # Provide both singular and list forms for compatibility
            tiles[(x, y)] = {
                'npc': npc,
                'enemy': payload.get('enemy'),
                'item': item,
                'npcs': [npc] if npc else [],
                'items': [item] if item else [],
            }
    elif isinstance(scene.get('tiles'), list):
        # map-editor 2D grid
        grid = scene['tiles']
        for y in range(min(h, len(grid))):
            row = grid[y] or []
            for x in range(min(w, len(row))):
                cell = (row[x] or {})
                npcs = list(cell.get('npcs') or [])
                items = list(cell.get('items') or [])
                # Derive primary npc/enemy for simple game flows
                def _is_enemy(e: dict) -> bool:
                    sub = str((e.get('subcategory') or '')).lower()
                    return sub in ('enemies','monsters','villains','vilains') or bool(e.get('hostile'))
                npc_payload = None
                enemy_payload = None
                for e in npcs:
                    if _is_enemy(e):
                        enemy_payload = e; break
                for e in npcs:
                    if not _is_enemy(e):
                        npc_payload = e; break
                tiles[(x, y)] = {
                    'npc': npc_payload,
                    'enemy': enemy_payload,
                    'item': (items[0] if items else None),
                    'npcs': npcs,
                    'items': items,
                    # Carry through the editor's per-tile safety marker ('safe'|'danger'|'')
                    'encounter': (cell.get('encounter') or ''),
                }

    # Entries: pass through if present
    entries = [(e.get('name',''), int(e.get('x',0)), int(e.get('y',0))) for e in scene.get('entries', [])]

    # Links: pass through if scene.links exists, otherwise derive from map-editor cells
    links: list[tuple[tuple[int,int], str, str, str|None]] = []
    if isinstance(scene.get('links'), list) and scene['links']:
        links = [(tuple(L.get('at', [0, 0])), L.get('to', ''), L.get('kind', 'map'), L.get('target_entry')) for L in scene['links']]
    elif isinstance(scene.get('tiles'), list):
        grid = scene['tiles']
        for y in range(min(h, len(grid))):
            row = grid[y] or []
            for x in range(min(w, len(row))):
                cell = (row[x] or {})
                lks = cell.get('links') or []
                if isinstance(lks, list) and lks:
                    # Only one link supported by editor UI; keep first
                    L = lks[0] or {}
                    to = L.get('target_map', '') or ''
                    if isinstance(to, str) and to.lower().endswith('.json'):
                        to = to[:-5]
                    links.append(((x, y), to, 'map', L.get('target_entry')))

    return {
        'name': scene.get('name', 'noname'),
        'kind': scene.get('kind', 'map'),
        'biome': scene.get('biome', 'forest'),
        'safe': bool(scene.get('safe', False)),
        'tile_size': int(scene.get('tile_size', 32)),
        'width': w, 'height': h,
        'walkable': walk,
        'entries': entries,
        'links': links,
        'tiles': tiles,
    }

def get_game_start() -> Tuple[str, str|None, Tuple[int,int]]:
    """Return (map_name, entry_name|None, (x,y)) for the game start."""
    wm = load_world_map()
    s = wm.get('start', {})
    return s.get('map',''), s.get('entry'), tuple(s.get('pos',[0,0]))
