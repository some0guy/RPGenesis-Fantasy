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
WORLD_MAP = DATA / 'world_map.txt'  # stores JSON

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
    """Return world_map structure (maps, dungeons, start)."""
    wm = _jload(WORLD_MAP, {})
    wm.setdefault('maps', {})
    wm.setdefault('dungeons', {})
    wm.setdefault('start', {'map':'', 'entry': None, 'pos':[0,0]})
    return wm

def load_scene_by_name(kind: str, name: str) -> Dict[str, Any]:
    """Load a JSON scene by kind ('map'|'dungeon') and name."""
    base = MAPS if kind=='map' else DUNGEONS
    path = base / f'{name}.json'
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
    """Translate scene JSON to a runtime-friendly dict your game can use."""
    w = int(scene.get('width',5)); h = int(scene.get('height',5))
    walk = [[bool(v) for v in row] for row in scene.get('terrain', [[1]*w for _ in range(h)])]
    tiles = {}
    for key, payload in scene.get('tiles', {}).items():
        try:
            x_str,y_str = key.split(','); x=int(x_str); y=int(y_str)
        except ValueError:
            continue
        tiles[(x,y)] = {
            'npc': payload.get('npc'),
            'enemy': payload.get('enemy'),
            'item': payload.get('item')
        }
    return {
        'name': scene.get('name','noname'),
        'kind': scene.get('kind','map'),
        'biome': scene.get('biome','forest'),
        'safe': bool(scene.get('safe', False)),
        'width': w, 'height': h,
        'walkable': walk,
        'entries': [(e.get('name',''), int(e.get('x',0)), int(e.get('y',0))) for e in scene.get('entries',[])],
        'links': [(tuple(L.get('at',[0,0])), L.get('to',''), L.get('kind','map'), L.get('target_entry')) for L in scene.get('links',[])],
        'tiles': tiles,
    }

def get_game_start() -> Tuple[str, str|None, Tuple[int,int]]:
    """Return (map_name, entry_name|None, (x,y)) for the game start."""
    wm = load_world_map()
    s = wm.get('start', {})
    return s.get('map',''), s.get('entry'), tuple(s.get('pos',[0,0]))
