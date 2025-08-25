#!/usr/bin/env python3
# RPGenesis Map Editor — Strict Sources with Citizens fix

import pygame as pg, json, re
from pathlib import Path

WIN_W, WIN_H = 1360, 1000
PANEL_W = 620
DATA_DIR = Path("data")
MAP_DIR = DATA_DIR/"maps"
MAP_DIR.mkdir(parents=True, exist_ok=True)

def read_json(path: Path):
    try:
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    except: return None

def as_list(obj):
    if obj is None: return []
    if isinstance(obj,list): return [x for x in obj if isinstance(x,dict)]
    if isinstance(obj,dict):
        for k in ["records","entries","list","data","items","npcs","enemies"]:
            if k in obj and isinstance(obj[k],list): return [x for x in obj[k] if isinstance(x,dict)]
        out=[]
        for k,v in obj.items():
            if isinstance(v,dict): vv=dict(v); vv.setdefault("id",k); out.append(vv)
        return out
    return []

def slugify(s:str)->str:
    s=str(s).lower().strip()
    return re.sub(r"[^a-z0-9]+","_",s).strip("_") or "unknown"

def first_existing(*cands:Path):
    for p in cands:
        if p.exists(): return p
    return None

def load_category_file(path_candidates):
    p=first_existing(*path_candidates)
    if not p: return []
    arr=as_list(read_json(p))
    out=[]
    for e in arr:
        name=e.get("name") or e.get("id") or "Unknown"
        _id=e.get("id") or slugify(name)
        out.append({"id":_id,"name":name})
    return out

def load_strict_catalogs():
    base_caps=DATA_DIR/"NPCs"; base_low=DATA_DIR/"npcs"
    npc_paths={
        "citizens":[base_caps/"citizens.json",base_low/"citizens.json",base_caps/"citizen.json",base_low/"citizen.json"],
        "allies":[base_caps/"allies.json",base_low/"allies.json"],
        "animals":[base_caps/"animals.json",base_low/"animals.json"],
        "enemies":[base_caps/"enemies.json",base_low/"enemies.json"],
        "monsters":[base_caps/"monsters.json",base_low/"monsters.json"],
    }
    item_base=DATA_DIR/"items"
    item_paths={
        "weapons":[item_base/"weapons.json"],
        "accessories":[item_base/"accessories.json"],
        "armour":[item_base/"armour.json",item_base/"armor.json"],
        "materials":[item_base/"materials.json"],
        "clothing":[item_base/"clothing.json"],
        "trinkets":[item_base/"trinkets.json"],
        "quest items":[item_base/"quest_items.json"],
    }
    npcs_by_cat={k:load_category_file(v) for k,v in npc_paths.items()}
    items_by_cat={k:load_category_file(v) for k,v in item_paths.items()}
    return npcs_by_cat,items_by_cat

if __name__=="__main__":
    npcs,items=load_strict_catalogs()
    print("NPC categories loaded:",{k:len(v) for k,v in npcs.items()})
    print("Item categories loaded:",{k:len(v) for k,v in items.items()})
