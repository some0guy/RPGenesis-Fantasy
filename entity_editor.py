#!/usr/bin/env python3
# RPGenesis Entity Editor — PRO(7) PATCHED — FIXED
# - Items & NPC editor
# - New stat system (PHY, TEC, ARC, VIT, KNO, INS, SOC, FTH)
# - Components picker (dual-list)
# - Rarity/type dropdowns (scoped by category)
# - Derived slot (readonly)
# - Weighted roll preview (loot_rolls.json)
# - JSON containers: bare list or {"items":[]}/{"npcs":[]}
# - Auto IDs (IT###### / NP######)
# - Clean Tk UI, raw JSON toggle

import json, os, re, time, random, sys
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Dict, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ---------- Constants ----------

TYPE_OPTIONS = {
    "weapons": ["shortsword","longsword","dagger","axe","mace","spear","bow","crossbow","staff","wand","warhammer","halberd","glaive","greatsword","shield"],
    "armour":  ["head","chest","legs","feet","hands","cloak","belt","shield"],
    "clothing":["hat","hood","mask","robe","tunic","vest","pants","boots","gloves","cloak","belt"],
    "accessories":["ring","amulet","necklace","bracelet","bracer","circlet"],
    "consumables":["potion","elixir","oil","bomb","ration","phial","tincture","tea","brew"],
    "materials":["ore","ingot","leather","cloth","hide","plank","pane","crystal","thread","powder"],
    "trinkets":["pendant","figurine","vase","goblet","mirror","fan","brooch","box","bead","tin"],
    "misc":["misc"]
}

RARITY_OPTIONS = ["common","uncommon","rare","epic","legendary","relic"]

BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
ITEMS_DIR  = os.path.join(BASE_DIR, "data", "items")
NPCS_DIR   = os.path.join(BASE_DIR, "data", "npcs")

RE_ID_ITEM = re.compile(r"^IT\d{6}$")
RE_ID_NPC  = re.compile(r"^(?:NP|NPC)\d{6}$")

BONUS_KEYS = [
    "PHY","TEC","ARC","VIT","KNO","INS","SOC","FTH",
    "hp","mp","initiative","speed",
    "crit_chance","crit_damage",
    "armor","evasion","block",
    "attack_rating","spell_power","penetration"
]

RESIST_KEYS = [
    "physical","fire","cold","lightning","poison","holy","arcane","shadow",
    "bleed","disease","stagger","charmed","slowed","burnt","distracted"
]

TRAIT_OPTIONS = [
    "unique","set_piece","cursed","blessed",
    "fragile","heavy","lightweight",
    "flammable","waterproof","conductive","insulated",
    "lifedrink","soulbound","chronal_burst","aura_guard","echo_strike"
]

DEFAULT_ITEM = {
    "id": "IT000000",
    "name": "New Item",
    "category": "misc",
    "type": "",
    "slot": "",
    "rarity": "common",
    "value": 0,
    "weight": 0,
    "description": "",
    "components": [],
    "fixed_bonus": [], "possible_bonus": [],
    "fixed_resist": [], "possible_resist": [],
    "fixed_trait": [], "possible_trait": []
}

DEFAULT_NPC = {
    "id": "NP000000",
    "name": "New NPC",
    "race": "",
    "sex": "",
    "type": "",
    "faction": "Neutral",
    "level": 1,
    "appearance": {},
    "inventory": [],
    "clothing": [],
    "personality": [],
    "clothing_short": "",
    "clothing_long": "",
    "personality_short": "",
    "personality_long": "",
    "notes": ""
}

# ---------- UI helpers ----------

def apply_ui_styling(root: tk.Tk, scale: float = 1.15):
    try:
        root.tk.call('tk', 'scaling', scale)
    except Exception:
        pass
    style = ttk.Style(root)
    try:
        for theme in ("vista","clam","default"):
            if theme in style.theme_names():
                style.theme_use(theme); break
    except Exception:
        pass
    try:
        import tkinter.font as tkfont
        base = tkfont.nametofont("TkDefaultFont"); base.configure(family="Segoe UI", size=10)
        mono = tkfont.nametofont("TkFixedFont");  mono.configure(family="Consolas", size=10)
    except Exception:
        pass
    style.configure("TLabel", padding=(2,2))
    style.configure("TButton", padding=(8,5))
    style.configure("TEntry", padding=4)
    style.configure("TCombobox", padding=4)
    style.configure("TNotebook.Tab", padding=(14,10))

# ---------- JSON I/O ----------

@dataclass
class Dataset:
    file_name: str
    path: str
    root: Any
    list_key: Optional[str]
    data: List[Any]

def discover_json_files(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    return sorted([f for f in os.listdir(folder) if f.lower().endswith(".json")])

def load_dataset(path: str, preferred_keys: Sequence[str] = (), *, allow_first_list=True, fallback_key: Optional[str]=None):
    if not os.path.exists(path):
        return None
    if os.path.getsize(path) == 0:
        if fallback_key:
            root = {fallback_key: []}
            return root, root[fallback_key], fallback_key
        empty: List[Any] = []
        return empty, empty, None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        messagebox.showerror("Invalid JSON", f"{os.path.basename(path)} could not be parsed:\n{exc}")
        return None
    if isinstance(data, list):
        return data, data, None
    if isinstance(data, dict):
        for key in preferred_keys:
            val = data.get(key)
            if isinstance(val, list):
                return data, val, key
        if allow_first_list:
            for key, val in data.items():
                if isinstance(val, list):
                    return data, val, key
    return None

def save_json_file(path: str, root_obj: Any, list_ref: List[Any], list_key: Optional[str]) -> None:
    payload = root_obj if isinstance(root_obj, dict) else list_ref
    if isinstance(root_obj, dict) and list_key:
        root_obj[list_key] = list_ref
        payload = root_obj
    os.makedirs(os.path.dirname(path), exist_ok=True)
    backup_data = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as src:
                backup_data = src.read()
        except Exception:
            backup_data = None
    if backup_data:
        ts = time.strftime("%Y%m%d_%H%M%S")
        with open(path + f".{ts}.bak", "w", encoding="utf-8") as bf:
            bf.write(backup_data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

# ---------- IDs & categories ----------

def ensure_item_id(item, existing_ids):

    _id = (item.get("id","") or "").strip()
    # normalize legacy 8-digit to 6-digit if present
    m8 = re.match(r"^IT(\d{8})$", _id)
    if m8:
        _id = "IT" + m8.group(1)[-6:]
    if RE_ID_ITEM.match(_id) and _id not in existing_ids:
        return _id
    base = 1
    if existing_ids:
        nums = []
        for s in existing_ids:
            if not s: continue
            m6 = re.match(r"IT(\d{6})$", (s or "").strip())
            if m6: nums.append(int(m6.group(1)))
            else:
                m8 = re.match(r"IT(\d{8})$", (s or "").strip())
                if m8: nums.append(int(m8.group(1)[-6:]))
        base = (max(nums) + 1) if nums else 1
    return f"IT{base:06d}"

def ensure_npc_id(npc, existing_ids):

    _id = (npc.get("id","") or "").strip().upper()
    # normalize legacy 8-digit to 6-digit if present
    m8 = re.match(r"^(NP|NPC)(\d{8})$", _id)
    if m8:
        _id = m8.group(1) + m8.group(2)[-6:]
    if RE_ID_NPC.match(_id) and _id not in existing_ids:
        return _id
    prefix = "NP"
    nums = []
    for s in existing_ids:
        if not s: continue
        s = s.strip().upper()
        m6 = re.match(r"^(NP|NPC)(\d{6})$", s)
        if m6:
            nums.append(int(m6.group(2)))
            if m6.group(1) == "NPC":
                prefix = "NPC"
        else:
            m8 = re.match(r"^(NP|NPC)(\d{8})$", s)
            if m8:
                nums.append(int(m8.group(2)[-6:]))
                if m8.group(1) == "NPC":
                    prefix = "NPC"
    next_num = (max(nums) + 1) if nums else 1
    # keep original prefix if user typed one
    pm = re.match(r"^(NP|NPC)", _id)
    if pm:
        prefix = pm.group(1)
    return f"{prefix}{next_num:06d}"

def infer_category(item):
    for k in ("category","slot","type"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return f"{k}:{v}"
    return "uncategorized"

def get_all_categories(items):
    cats = {infer_category(it) for it in items}
    return ["(all)"] + sorted(cats)

# ---- Global items index for components
ALL_ITEMS_ID_TO_LABEL: Dict[str, str] = {}
ALL_ITEMS_LABEL_TO_ID: Dict[str, str] = {}

def build_item_label(it: dict) -> str:
    iid = str(it.get("id","?")).strip() or "?"
    name = str(it.get("name","?")).strip() or "?"
    cat  = infer_category(it)
    return f"{iid} — {name} [{cat}]"

def rebuild_items_index(all_item_lists: List[List[dict]]):
    global ALL_ITEMS_ID_TO_LABEL, ALL_ITEMS_LABEL_TO_ID
    id2label = {}
    for lst in all_item_lists:
        for it in lst:
            iid = str(it.get("id","")).strip()
            if not iid: continue
            id2label[iid] = build_item_label(it)
    ALL_ITEMS_ID_TO_LABEL = id2label
    ALL_ITEMS_LABEL_TO_ID = {label: iid for iid, label in id2label.items()}

# ---------- Slot inference ----------

def derive_slot(item: dict) -> str:
    t = str(item.get("type","") or "").strip().lower()
    cat = str(item.get("category","") or "").strip().lower()
    def has(*words):
        return any(w in t for w in words)
    if has("head","helm","helmet","circlet","hood","hat","cap","mask"):
        return "head"
    if has("chest","plate","cuirass","breast","robe","tunic","vest") and not has("helmet","helm","hood","hat"):
        return "chest"
    if has("leg","greave","pants","trouser","skirt","kilt","legging"):
        return "legs"
    if has("boot","shoe","sandal","sabatons","foot","feet"):
        return "feet"
    if has("glove","gauntlet","mitt","handwrap","hand"):
        return "hands"
    if has("ring","band","signet"):
        return "ring"
    if has("amulet","necklace","talisman","pendant"):
        return "amulet"
    if has("bracelet","bracer","wrist"):
        return "hands"
    if has("cloak","cape","mantle"):
        return "cloak"
    if has("belt","sash","girdle"):
        return "belt"
    if has("shield","buckler","parma"):
        return "offhand"
    if has("two hand","2h","zweihander","greatsword","greataxe","halberd","polearm","longbow","warhammer"):
        return "two_handed"
    if cat in ("weapons","weapon"):
        return "weapon"
    if cat in ("consumable","consumables"):
        return "consumable"
    if cat in ("materials","material"):
        return "material"
    return item.get("slot","") or "misc"

# ---------- Composite fields ----------

class ComboField(ttk.Frame):
    def __init__(self, master, values: List[str], initial: str = "", allow_custom=True):
        super().__init__(master)
        self.values = list(values)
        self.var = tk.StringVar(value=initial)
        self.combo = ttk.Combobox(self, values=self.values, textvariable=self.var, state="readonly")
        self.combo.pack(side="left", fill="x", expand=True)
        if allow_custom:
            ttk.Button(self, text="Custom...", command=self.add_custom).pack(side="left", padx=4)
    def add_custom(self):
        s = simpledialog.askstring("Custom value", "Enter custom value:")
        if not s: return
        if s not in self.values:
            self.values.append(s); self.combo["values"] = self.values
        self.var.set(s)
    def get(self) -> str:
        return self.var.get()
    def set(self, value: str):
        self.var.set(value or "")

class KeyPickerField(ttk.Frame):
    """Generic single-select picker with available list (left) and selected list (right)."""
    def __init__(self, master, all_keys, initial=None, title_left="Available", title_right="Selected"):
        super().__init__(master)
        self.all_keys = list(dict.fromkeys(all_keys))
        self.selected = []
        if initial:
            for k in initial:
                if isinstance(k, str) and k not in self.selected:
                    self.selected.append(k)

        self.columnconfigure(0, weight=1); self.columnconfigure(1, weight=1)

        left = ttk.Frame(self); left.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        ttk.Label(left, text=title_left).pack(anchor="w")
        self.lb = tk.Listbox(left, selectmode="browse", height=10, exportselection=False)
        self.lb.pack(fill="both", expand=True, pady=(4,0))

        btns = ttk.Frame(left); btns.pack(fill="x", pady=(6,0))
        ttk.Button(btns, text="Add ▶", command=self._add).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(btns, text="◀ Remove", command=self._remove).pack(side="left", expand=True, fill="x", padx=3)

        right = ttk.Frame(self); right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text=title_right).pack(anchor="w")
        self.sel = tk.Listbox(right, selectmode="browse", height=10, exportselection=False)
        self.sel.pack(fill="both", expand=True, pady=(4,0))

        self._refill_available()
        self._sync_selected()

        # Click-outside clears selections (without stealing button clicks)
        def _is_descendant(widget, container):
            try:
                w = widget
                while w is not None:
                    if w == container:
                        return True
                    w = getattr(w, "master", None)
            except Exception:
                pass
            return False

        def _global_click_clear(event, self=self):
            try:
                if not _is_descendant(event.widget, self):
                    self.lb.selection_clear(0, "end")
                    self.sel.selection_clear(0, "end")
            except Exception:
                pass
        self.winfo_toplevel().bind("<Button-1>", _global_click_clear, add="+")

    def _refill_available(self):
        self.lb.delete(0, "end")
        for k in self.all_keys:
            if k not in self.selected:
                self.lb.insert("end", k)

    def _sync_selected(self):
        self.sel.delete(0, "end")
        for k in self.selected:
            self.sel.insert("end", k)

    def _add(self):
        if self.lb.curselection():
            k = self.lb.get(self.lb.curselection()[0])
            if k not in self.selected:
                self.selected.append(k)
                self._refill_available()
                self._sync_selected()
        try:
            self.lb.selection_clear(0, "end"); self.sel.selection_clear(0, "end")
        except Exception:
            pass

    def _remove(self):
        pick = None
        if self.sel.curselection():
            pick = self.sel.get(self.sel.curselection()[0])
        elif self.lb.curselection():
            pick = self.lb.get(self.lb.curselection()[0])
        if pick is not None and pick in self.selected:
            self.selected = [x for x in self.selected if x != pick]
            self._refill_available()
            self._sync_selected()
        try:
            self.lb.selection_clear(0, "end"); self.sel.selection_clear(0, "end")
        except Exception:
            pass

    def set(self, keys):
        self.selected = []
        for k in keys or []:
            if isinstance(k, str) and k not in self.selected:
                self.selected.append(k)
        self._refill_available()
        self._sync_selected()

    def get(self):
        return list(self.selected)

class ComponentsField(ttk.Frame):
    """
    Components/materials picker with filters.
    - Add/Remove buttons
    - Text filter + category filter
    - Single-select both sides
    - Reorder up/down + Clear
    """
    def __init__(self, master, labels: List[str]):
        super().__init__(master)
        self.all_labels = list(sorted(set(labels)))
        self.selected: List[str] = []

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # Filters
        top = ttk.Frame(self); top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,6))
        ttk.Label(top, text="Filter").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.filter_var, width=24); ent.pack(side="left", padx=(6,10))
        ttk.Label(top, text="Category").pack(side="left")
        self.cat_var = tk.StringVar(value="(all)")
        self.cat_combo = ttk.Combobox(top, textvariable=self.cat_var, state="readonly", width=18,
                                      values=["(all)","materials","armour","weapons","clothing","accessories","trinkets","consumables","misc"])
        self.cat_combo.pack(side="left")

        left = ttk.Frame(self); left.grid(row=1, column=0, sticky="nsew", padx=(0,8))
        ttk.Label(left, text="Available").pack(anchor="w")
        self.lb = tk.Listbox(left, selectmode="browse", height=10, exportselection=False)
        self.lb.pack(fill="both", expand=True)

        ctr = ttk.Frame(self); ctr.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6,0))
        ttk.Button(ctr, text="Add ▶", command=self._add).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(ctr, text="◀ Remove", command=self._remove).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(ctr, text="↑ Up", command=self._up).pack(side="left", padx=3)
        ttk.Button(ctr, text="↓ Down", command=self._down).pack(side="left", padx=3)
        ttk.Button(ctr, text="Clear", command=self._clear).pack(side="left", padx=3)

        right = ttk.Frame(self); right.grid(row=1, column=1, sticky="nsew")
        ttk.Label(right, text="Selected").pack(anchor="w")
        self.sel = tk.Listbox(right, selectmode="browse", height=10, exportselection=False)
        self.sel.pack(fill="both", expand=True)

        # Bindings
        self.filter_var.trace_add("write", lambda *_: self._refill())
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self._refill())

        # Click-outside selection clear
        def _is_descendant(widget, container):
            try:
                w = widget
                while w is not None:
                    if w == container:
                        return True
                    w = getattr(w, "master", None)
            except Exception:
                pass
            return False

        def _global_click_clear(event, self=self):
            try:
                if not _is_descendant(event.widget, self):
                    self.lb.selection_clear(0, "end")
                    self.sel.selection_clear(0, "end")
            except Exception:
                pass
        self.winfo_toplevel().bind("<Button-1>", _global_click_clear, add="+")

        self._refill()

    def _match_cat(self, label, cat):
        L = label.lower()
        if cat in ("(all)","",None): return True
        if cat == "materials":   return any(w in L for w in ["ingot","ore","leather","cloth","hide","wood","herb","glass","crystal","thread","plate","plank","pane","powder"])
        if cat == "armour":      return any(w in L for w in ["helm","hood","chest","cuirass","breast","greave","legging","boot","glove","gaunt","cloak","belt","shield","armor","armour"])
        if cat == "weapons":     return any(w in L for w in ["sword","dagger","axe","mace","hammer","spear","bow","crossbow","staff","wand","polearm","halberd","glaive"])
        if cat == "clothing":    return any(w in L for w in ["robe","tunic","vest","pants","trouser","skirt","kilt","hat","mask","glove","boot","shoe","belt","cloak"])
        if cat == "accessories": return any(w in L for w in ["ring","amulet","necklace","talisman","bracelet","bracer","circlet"])
        if cat == "trinkets":    return any(w in L for w in ["vase","figurine","goblet","pendant","mirror","fan","charm","bead","box","brooch","tin","mask"])
        if cat == "consumables": return any(w in L for w in ["potion","elixir","tonic","draft","draught","oil","bomb","phial","tincture","ration","water","brew","tea"])
        if cat == "misc":        return True
        return True

    def _refill(self):
        flt = (self.filter_var.get() or "").strip().lower()
        cat = (self.cat_var.get() or "(all)").strip().lower()
        items = [lab for lab in self.all_labels if (flt in lab.lower()) and self._match_cat(lab, cat)]
        self.lb.delete(0, "end")
        for lab in items:
            self.lb.insert("end", lab)

    def _sync_sel(self):
        self.sel.delete(0, "end")
        for lab in self.selected:
            self.sel.insert("end", lab)

    def _add(self):
        if self.lb.curselection():
            p = self.lb.get(self.lb.curselection()[0])
            if p not in self.selected:
                self.selected.append(p)
                self._sync_sel()
        try:
            self.lb.selection_clear(0, "end"); self.sel.selection_clear(0, "end")
        except Exception:
            pass

    def _remove(self):
        pick = None
        if self.sel.curselection():
            pick = self.sel.get(self.sel.curselection()[0])
        elif self.lb.curselection():
            pick = self.lb.get(self.lb.curselection()[0])
        if pick is not None:
            self.selected = [s for s in self.selected if s != pick]
            self._sync_sel()
        try:
            self.lb.selection_clear(0, "end"); self.sel.selection_clear(0, "end")
        except Exception:
            pass

    def _up(self):
        sel = list(self.sel.curselection())
        if not sel:
            return
        i = sel[0]
        if i > 0:
            self.selected[i-1], self.selected[i] = self.selected[i], self.selected[i-1]
            self._sync_sel()
            self.sel.selection_set(i-1)

    def _down(self):
        sel = list(self.sel.curselection())
        if not sel:
            return
        i = sel[0]
        if i < len(self.selected)-1:
            self.selected[i+1], self.selected[i] = self.selected[i], self.selected[i+1]
            self._sync_sel()
            self.sel.selection_set(i+1)

    def _clear(self):
        self.selected = []
        self._sync_sel()

    def set(self, labels):
        self.selected = list(labels or [])
        self._sync_sel()

    def get(self):
        return list(self.selected)

# ---------- Form ----------

class KeyValueForm(ttk.Frame):
    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self.current_obj = {}
        self.inputs: Dict[str, Tuple[str, Any]] = {}
        self.raw_mode = False
        self.context_category = ""

        bar = ttk.Frame(self); bar.pack(fill="x", pady=(0,4))
        self.toggle_btn = ttk.Button(bar, text="Raw JSON", command=self.toggle_raw); self.toggle_btn.pack(side="right")

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True); self.scroll.pack(side="right", fill="y")

        self.raw_text = tk.Text(self, height=24)
        try:
            self.raw_text.configure(font=("Courier", 10))
        except Exception:
            pass

    # Context: items tab sets this so "type" combobox scopes correctly
    def set_category_context(self, cat: str):
        self.context_category = (cat or '').lower()

    def toggle_raw(self):
        self.raw_mode = not self.raw_mode
        if self.raw_mode:
            for w in (self.canvas, self.scroll): w.pack_forget()
            self.raw_text.pack(fill="both", expand=True)
            self.raw_text.delete("1.0","end")
            self.raw_text.insert("1.0", json.dumps(self.current_obj, ensure_ascii=False, indent=2))
            self.toggle_btn.config(text="Form View")
        else:
            try:
                obj = json.loads(self.raw_text.get("1.0","end"))
                self.set_object(obj)
            except Exception as e:
                messagebox.showerror("Invalid JSON", str(e)); return
            self.raw_text.pack_forget()
            self.canvas.pack(side="left", fill="both", expand=True); self.scroll.pack(side="right", fill="y")
            self.toggle_btn.config(text="Raw JSON")

    
    def _refresh_raw_if_visible(self):
        # If raw mode is showing, update its content to the current object
        try:
            if getattr(self, "raw_mode", False) and hasattr(self, "raw_text"):
                self.raw_text.delete("1.0","end")
                self.raw_text.insert("1.0", json.dumps(self.current_obj, ensure_ascii=False, indent=2))
        except Exception:
            pass


    def _make_widget_for(self, key: str, val: Any):
            # Hide category (comes from file context on items)
            if key == "category":
                return ("hidden", None)

            # Rarity dropdown
            if key == "rarity":
                w = ComboField(self.inner, RARITY_OPTIONS, str(val or ""))
                return ("rarity_combo", w)

            # Type dropdown scoped by current file category
            if key == "type":
                cat = (self.context_category or "").lower()
                if cat and cat in TYPE_OPTIONS:
                    options = TYPE_OPTIONS[cat]
                else:
                    # Fallback to union of all types
                    options = sorted({t for arr in TYPE_OPTIONS.values() for t in arr})
                w = ComboField(self.inner, options, str(val or ""))
                return ("type_combo", w)

            # Bonus/resist/trait pickers
            if key in ("fixed_bonus", "possible_bonus"):
                w = KeyPickerField(self.inner, BONUS_KEYS, [v for v in (val or []) if isinstance(v, str)], "Available Bonus", "Selected Bonus")
                return (f"{key}_keys", w)
            if key in ("fixed_resist", "possible_resist"):
                w = KeyPickerField(self.inner, RESIST_KEYS, [v for v in (val or []) if isinstance(v, str)], "Available Resist", "Selected Resist")
                return (f"{key}_keys", w)
            if key in ("fixed_trait", "possible_trait"):
                w = KeyPickerField(self.inner, TRAIT_OPTIONS, [v for v in (val or []) if isinstance(v, str)], "Available Trait", "Selected Trait")
                return (f"{key}_keys", w)

            # Slot is readonly (derived)
            if key == "slot":
                var = tk.StringVar(value=str(val or ""))
                entry = ttk.Entry(self.inner, textvariable=var, state="readonly")
                return ("slot_readonly", (entry, var))

            # Legacy arrays shown as readonly JSON (if present)
            if key in ("bonus", "resist", "trait"):
                text = tk.Text(self.inner, height=3, width=40)
                try:
                    text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
                except Exception:
                    text.insert("1.0", str(val))
                text.configure(state="disabled")
                return ("legacy_json", text)

            # Multiline text fields
            if key in ("description", "notes", "clothing_long", "personality_long"):
                text = tk.Text(self.inner, height=6, width=40)
                try:
                    text.insert("1.0", "" if val is None else str(val))
                except Exception:
                    text.insert("1.0", str(val))
                return ("multiline", text)

            # Dict/list -> JSON editor
            if isinstance(val, (dict, list)):
                text = tk.Text(self.inner, height=4, width=40)
                text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
                return ("json", text)

            # Default scalar
            entry = ttk.Entry(self.inner); entry.insert(0, "" if val is None else str(val))
            return ("scalar", entry)
    def set_object(self, obj: dict):
        self.current_obj = dict(obj) if obj else {}

        # Hide deprecated legacy
        if 'scale_with_level' in self.current_obj:
            self.current_obj.pop('scale_with_level', None)

        # Seed possible_* from legacy shapes once
        def keys_from_legacy(v):
            if isinstance(v, list):
                return [x for x in v if isinstance(x,str)]
            if isinstance(v, dict):
                return [k for k, vv in v.items() if vv]
            return []
        self.current_obj.setdefault("fixed_bonus", [])
        self.current_obj.setdefault("possible_bonus", keys_from_legacy(self.current_obj.get("bonus")))
        self.current_obj.setdefault("fixed_resist", [])
        self.current_obj.setdefault("possible_resist", keys_from_legacy(self.current_obj.get("resist")))
        self.current_obj.setdefault("fixed_trait", [])
        self.current_obj.setdefault("possible_trait", keys_from_legacy(self.current_obj.get("trait")))

        # If Raw JSON pane is visible, update it right away
        if hasattr(self, "_refresh_raw_if_visible"):
            self._refresh_raw_if_visible()

        # Rebuild UI
        for w in self.inner.winfo_children():
            w.destroy()
        self.inputs.clear()

        preferred = ["id","name","type","rarity","value","weight","description",
                     "slot","category","components",
                     "fixed_bonus","possible_bonus","fixed_resist","possible_resist","fixed_trait","possible_trait"]
        keys = list(self.current_obj.keys())
        keys_sorted = preferred + [k for k in keys if k not in preferred]

        # If components exist -> show as ComponentsField with labels from global index
        labels = None
        if "components" in self.current_obj and ALL_ITEMS_ID_TO_LABEL:
            raw_comps = self.current_obj.get("components", [])
            if not isinstance(raw_comps, list):
                raw_comps = []
            comp_ids = []
            for c in raw_comps:
                if isinstance(c, dict):
                    cid = c.get("id") or c.get("component_id") or ""
                else:
                    cid = str(c)
                if cid:
                    m8 = re.match(r"^([A-Z]{2,3})(\d{8})$", cid)
                    if m8:
                        cid = m8.group(1) + m8.group(2)[-6:]
                    comp_ids.append(cid)
            labels = [ALL_ITEMS_ID_TO_LABEL.get(cid, cid) for cid in comp_ids]

        row = 0
        for k in keys_sorted:
            if k == 'category':
                continue
            if k in ("fixed_bonus","possible_bonus","fixed_resist","possible_resist","fixed_trait","possible_trait"):
                # handled by the Affixes section below
                continue
            val = self.current_obj.get(k)
            ttk.Label(self.inner, text=k).grid(row=row, column=0, sticky="w", padx=6, pady=4)

            if k == "components" and ALL_ITEMS_ID_TO_LABEL:
                # Build a full label list for the available side
                all_labels = list(ALL_ITEMS_ID_TO_LABEL.values())
                widget = ComponentsField(self.inner, all_labels)
                widget.set(labels or [])
                self.inputs[k] = ("components_labels", widget)
                widget.grid(row=row, column=1, sticky="we", padx=6, pady=4)
                row += 1
                continue

            kind, widget = self._make_widget_for(k, val)
            if kind == 'hidden':
                continue
            self.inputs[k] = (kind, widget)
            if kind == "slot_readonly":
                widget[0].grid(row=row, column=1, sticky="we", padx=6, pady=4)
            else:
                widget.grid(row=row, column=1, sticky="we", padx=6, pady=4)
            row += 1

        # --- Vertical layout for (Bonus, Resist, Trait) ---
        trio = ttk.LabelFrame(self.inner, text="Affixes")
        trio.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=6, pady=8)
        trio.columnconfigure(0, weight=1)

        def _mk_section(r, title, fixed_key, possible_key, all_keys):
            section = ttk.Frame(trio)
            section.grid(row=r, column=0, sticky="nsew", padx=4, pady=8)
            ttk.Label(section, text=title, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0,4))

            # Fixed row
            ttk.Label(section, text="Fixed").pack(anchor="w")
            fixed_widget = KeyPickerField(section, all_keys,
                                          [v for v in (self.current_obj.get(fixed_key) or []) if isinstance(v, str)],
                                          "Available", "Selected")
            fixed_widget.pack(fill="both", expand=True, pady=(2,6))
            self.inputs[fixed_key] = (f"{fixed_key}_keys", fixed_widget)

            # Possible row
            ttk.Label(section, text="Possible").pack(anchor="w")
            poss_widget = KeyPickerField(section, all_keys,
                                         [v for v in (self.current_obj.get(possible_key) or []) if isinstance(v, str)],
                                         "Available", "Selected")
            poss_widget.pack(fill="both", expand=True, pady=(2,0))
            self.inputs[possible_key] = (f"{possible_key}_keys", poss_widget)

        _mk_section(0, "Bonus", "fixed_bonus", "possible_bonus", BONUS_KEYS)
        _mk_section(1, "Resist", "fixed_resist", "possible_resist", RESIST_KEYS)
        _mk_section(2, "Trait", "fixed_trait", "possible_trait", TRAIT_OPTIONS)

        row += 1

        # derive slot once after layout if possible
        try:
            snap = {
                "type": "",
                "category": self.context_category
            }
            t = self.inputs.get("type")
            if t:
                if t[0] in ("scalar","rarity_combo","type_combo"):
                    try: snap["type"] = t[1].get()
                    except Exception: pass
            inferred = derive_slot(snap)
            sl = self.inputs.get("slot")
            if sl and sl[0] == "slot_readonly":
                sl[1][1].set(inferred)
        except Exception:
            pass
        self.inner.columnconfigure(1, weight=1)

        # Final sync of raw view after layout
        if hasattr(self, "_refresh_raw_if_visible"):
            self._refresh_raw_if_visible()

    def get_object(self):
        if self.raw_mode:
            try:
                return json.loads(self.raw_text.get("1.0","end"))
            except Exception as e:
                messagebox.showerror("Invalid JSON", str(e))
                return None
        out = {}
        for k, (kind, widget) in self.inputs.items():
            if kind in ("legacy_json","hidden"):
                continue
            elif kind == "json":
                try:
                    out[k] = json.loads(widget.get("1.0","end"))
                except Exception:
                    # keep as string/raw
                    out[k] = widget.get("1.0","end")
            elif kind == "multiline":
                try:
                    out[k] = widget.get("1.0","end").strip()
                except Exception:
                    out[k] = ""
            elif kind == "components_labels":
                labels = widget.get()
                ids = []
                for lab in labels:
                    iid = ALL_ITEMS_LABEL_TO_ID.get(lab)
                    if iid: ids.append(iid)
                out[k] = ids
            elif kind.endswith("_keys"):
                out[k] = widget.get()
            elif kind == "slot_readonly":
                # re-derived later
                pass
            else:
                # scalar or combo
                try:
                    val = widget.get()
                except Exception:
                    val = ""
                if isinstance(val, str) and re.match(r"^-?\d+(\.\d+)?$", val.strip()):
                    out[k] = float(val) if "." in val else int(val)
                else:
                    out[k] = val
        # derive slot
        try:
            out["slot"] = derive_slot(out)
        except Exception:
            out['slot'] = out.get('slot','') or ''
        # category context on items tab
        if self.context_category:
            out['category'] = self.context_category
        # purge deprecated
        if 'scale_with_level' in out:
            out.pop('scale_with_level', None)

        # normalize IDs to 6-digit for id + components
        iid = str(out.get("id","")).strip()
        m8 = re.match(r"^([A-Z]{2,3})(\d{8})$", iid)
        if m8:
            out["id"] = m8.group(1) + m8.group(2)[-6:]
        comps = out.get("components", [])
        if isinstance(comps, list):
            cleaned = []
            for cid in comps:
                s = ""
                if isinstance(cid, dict):
                    s = cid.get("id") or cid.get("component_id") or ""
                else:
                    s = str(cid)
                if s:
                    m8 = re.match(r"^([A-Z]{2,3})(\d{8})$", s)
                    if m8:
                        s = m8.group(1) + m8.group(2)[-6:]
                    cleaned.append(s)
            out["components"] = cleaned

        return out

# ---------- Rolling / Weights ----------

def _load_loot_config():
    cfg_path = os.path.join(BASE_DIR, "data", "meta", "loot_rolls.json")
    default = {
        "rarity_slots": {
            "bonus":  {"common": [0, 1], "uncommon": [1, 1], "rare": [2, 2], "epic": [3, 3], "legendary": [4, 4], "relic": [5, 5]},
            "resist": {"common": [0, 0], "uncommon": [0, 1], "rare": [1, 1], "epic": [2, 2], "legendary": [2, 3], "relic": [3, 3]},
            "trait":  {"common": [0, 0], "uncommon": [0, 1], "rare": [1, 1], "epic": [1, 2], "legendary": [2, 2], "relic": [2, 3]}
        },
        "global_bonus_weights": {k: 1 for k in BONUS_KEYS},
        "global_resist_weights": {k: 1 for k in RESIST_KEYS},
        "category_bias": {}
    }
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                user = json.load(f)
            def merge(a, b):
                if isinstance(a, dict) and isinstance(b, dict):
                    out = dict(a)
                    for k, v in b.items():
                        out[k] = merge(a.get(k), v) if k in a else v
                    return out
                return b if b is not None else a
            return merge(default, user)
    except Exception:
        pass
    return default

def _category_tag_for(item: dict) -> str:
    cat = str(item.get("category","") or "").strip().lower()
    slot = str(item.get("slot","") or "").strip().lower()
    if cat in ("armour","armor","weapons","weapon","clothing","accessories","accessory"):
        return f"{cat}:{slot}" if slot else cat
    return cat or (slot or "misc")

def _weighted_sample_without_replacement(candidates, weights_map, n, rng):
    pool = [(c, max(0.000001, float(weights_map.get(c, 1)))) for c in candidates]
    chosen = []
    n = min(n, len(pool))
    for _ in range(n):
        total = sum(w for _, w in pool)
        if total <= 0: break
        r = rng.random() * total
        upto = 0.0
        pick_idx = None
        for i,(c,w) in enumerate(pool):
            upto += w
            if r <= upto:
                pick_idx = i; break
        if pick_idx is None:
            pick_idx = len(pool)-1
        chosen.append(pool[pick_idx][0])
        pool.pop(pick_idx)
    return chosen

def _rarity_count(cfg, kind, rarity, rng):
    rr = cfg.get("rarity_slots",{}).get(kind,{}).get(str(rarity).lower())
    if not rr or not isinstance(rr, list) or len(rr) != 2:
        return 0
    lo, hi = int(rr[0]), int(rr[1])
    if hi < lo: lo, hi = hi, lo
    return rng.randint(lo, hi)

class RollPreviewDialog(tk.Toplevel):
    def __init__(self, master, item_obj: dict):
        super().__init__(master)
        self.title("Roll Preview")
        self.item = item_obj or {}
        self.cfg = _load_loot_config()

        frm = ttk.Frame(self); frm.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(frm, text="Rarity").grid(row=0, column=0, sticky="w")
        self.rarity_var = tk.StringVar(value=str(self.item.get("rarity","common")).lower())
        rarities = ["common","uncommon","rare","epic","legendary","relic"]
        self.rarity_combo = ttk.Combobox(frm, values=rarities, textvariable=self.rarity_var, state="readonly")
        self.rarity_combo.grid(row=0, column=1, sticky="we", padx=(6,0))

        ttk.Label(frm, text="Seed").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.seed_var).grid(row=1, column=1, sticky="we", padx=(6,0), pady=(6,0))

        self.roll_btn = ttk.Button(frm, text="Roll", command=self.roll_now)
        self.roll_btn.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10,8))

        self.out = tk.Text(frm, height=16, width=64)
        self.out.grid(row=3, column=0, columnspan=2, sticky="nsew")
        try:
            self.out.configure(font=("Courier", 10))
        except Exception:
            pass
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)

        self.roll_now()

    def roll_now(self):
        rarity = self.rarity_var.get().lower()
        seed_txt = self.seed_var.get().strip()
        rng = random.Random()
        if seed_txt:
            try: rng.seed(int(seed_txt))
            except ValueError: rng.seed(seed_txt)

        fixed_bonus    = list(self.item.get("fixed_bonus") or [])
        possible_bonus = [k for k in (self.item.get("possible_bonus") or []) if k not in fixed_bonus]
        fixed_resist   = list(self.item.get("fixed_resist") or [])
        possible_resist= [k for k in (self.item.get("possible_resist") or []) if k not in fixed_resist]
        fixed_trait    = list(self.item.get("fixed_trait") or [])
        possible_trait = [k for k in (self.item.get("possible_trait") or []) if k not in fixed_trait]

        tag = _category_tag_for(self.item)
        bias = (self.cfg.get("category_bias") or {}).get(tag, {})
        bw = dict(self.cfg.get("global_bonus_weights") or {})
        for k,v in (bias.get("bonus_weights") or {}).items():
            if k in bw: bw[k] = bw[k]*float(v)
        rw = dict(self.cfg.get("global_resist_weights") or {})
        for k,v in (bias.get("resist_weights") or {}).items():
            if k in rw: rw[k] = rw[k]*float(v)

        need_b = _rarity_count(self.cfg, "bonus", rarity, rng)
        need_r = _rarity_count(self.cfg, "resist", rarity, rng)
        need_t = _rarity_count(self.cfg, "trait", rarity, rng)

        roll_b = _weighted_sample_without_replacement(possible_bonus, bw, max(0, need_b), rng)
        roll_r = _weighted_sample_without_replacement(possible_resist, rw, max(0, need_r), rng)
        tw = {k:1 for k in possible_trait}
        roll_t = _weighted_sample_without_replacement(possible_trait, tw, max(0, need_t), rng)

        final_bonus  = fixed_bonus  + roll_b
        final_resist = fixed_resist + roll_r
        final_trait  = fixed_trait  + roll_t

        bt = self.item.get("bonus_template") or {}
        rt = self.item.get("resist_template") or self.item.get("defense_template") or {}

        def fmt_template_line(k, tpl):
            v = tpl.get(k)
            if isinstance(v, dict):
                lo = v.get("min", v.get("lo", ""))
                hi = v.get("max", v.get("hi", ""))
                return f"{k:16} ~ {lo}-{hi}"
            elif isinstance(v, (int,float)):
                return f"{k:16} ~ {v}"
            return f"{k:16}"

        lines = []
        lines.append(f"Item: {self.item.get('id','?')} — {self.item.get('name','?')} [{tag}]")
        lines.append(f"Rarity: {rarity}")
        lines.append("")
        lines.append("BONUS")
        for k in final_bonus:
            lines.append("  " + fmt_template_line(k, bt))
        if not final_bonus: lines.append("  (none)")
        lines.append("")
        lines.append("RESIST")
        for k in final_resist:
            lines.append("  " + fmt_template_line(k, rt))
        if not final_resist: lines.append("  (none)")
        lines.append("")
        lines.append("TRAIT")
        for k in final_trait:
            lines.append("  " + k)
        if not final_trait: lines.append("  (none)")

        self.out.configure(state="normal")
        self.out.delete("1.0","end")
        self.out.insert("1.0", "\n".join(lines))
        self.out.configure(state="disabled")

# ---------- Tabs ----------

class ItemsTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.datasets: Dict[str, Dataset] = {}
        self.active_dataset: Optional[Dataset] = None
        self.active_file = None
        self.active_list: List[dict] = []
        self.filtered_indices: List[int] = []
        self.selected_index: Optional[int] = None

        left = ttk.Frame(self); right = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=6, pady=6)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        ttk.Label(left, text="Items File").pack(anchor="w")
        self.file_combo = ttk.Combobox(left, state="readonly", width=28)
        self.file_combo.pack(fill="x", pady=(0,6)); self.file_combo.bind("<<ComboboxSelected>>", self.on_file_change)
        self.count_var = tk.StringVar(value="Entries: 0")
        ttk.Label(left, textvariable=self.count_var).pack(anchor="w")
        self.count_var = tk.StringVar(value="Entries: 0")
        ttk.Label(left, textvariable=self.count_var).pack(anchor="w")

        ttk.Label(left, text="Search").pack(anchor="w")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search_var); ent.pack(fill="x", pady=(0,6))
        ent.bind("<KeyRelease>", lambda e: self.refresh_list())

        ttk.Label(left, text="Category Filter").pack(anchor="w")
        self.cat_combo = ttk.Combobox(left, state="readonly")
        self.cat_combo.pack(fill="x", pady=(0,6))
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        # --- NEW: Type Filter ---
        ttk.Label(left, text="Type Filter").pack(anchor="w")
        self.type_combo = ttk.Combobox(left, state="readonly")
        self.type_combo.pack(fill="x", pady=(0,6))
        self.type_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        self.listbox = tk.Listbox(left, height=24); self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        btns = ttk.Frame(left); btns.pack(fill="x", pady=6)
        self.btn_new = ttk.Button(btns, text="New", command=self.on_new); self.btn_new.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_dup = ttk.Button(btns, text="Duplicate", command=self.on_dup); self.btn_dup.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_del = ttk.Button(btns, text="Delete", command=self.on_del); self.btn_del.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_save = ttk.Button(btns, text="Save File", command=self.on_save); self.btn_save.pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Roll Preview", command=self.on_roll_preview).pack(side="left", expand=True, fill="x", padx=2)

        self.form = KeyValueForm(right); self.form.pack(fill="both", expand=True)
        self.load_datasets()

    def rebuild_global_items_index(self):
        all_lists = [ds.data for ds in self.datasets.values()]
        rebuild_items_index(all_lists)

    def load_datasets(self):
        self.datasets.clear()
        if not os.path.isdir(ITEMS_DIR):
            messagebox.showwarning("Missing folder", f"Items directory not found: {ITEMS_DIR}")
            return
        files_found = []
        for fname in discover_json_files(ITEMS_DIR):
            path = os.path.join(ITEMS_DIR, fname)
            loaded = load_dataset(path, preferred_keys=("items","entries","records"), allow_first_list=True)
            if not loaded: continue
            root, lst, list_key = loaded
            if not isinstance(lst, list): continue
            self.datasets[fname] = Dataset(fname, path, root, list_key, lst)
            files_found.append(fname)
        if not files_found:
            self.file_combo.set(""); self.cat_combo["values"] = []
            self.listbox.delete(0,"end"); self.form.set_object({}); return
        self.rebuild_global_items_index()
        self.file_combo["values"] = ["(All Item files)"] + files_found; self.file_combo.current(0)
        self.file_combo.set("(All Item files)")
        self.on_file_change()

    def on_file_change(self, *_):
        fname = self.file_combo.get()
        dataset = self.datasets.get(fname)

        # Handle aggregate mode first
        if fname == "(All Item files)":
            self.active_dataset = None
            self.active_file = None
            all_items = []
            for ds in self.datasets.values():
                try:
                    lst = ds.data if hasattr(ds, "data") else None
                except Exception:
                    lst = None
                if isinstance(lst, list):
                    all_items.extend(lst)
            self.active_list = all_items
            # Disable mutating actions
            for btn_name in ("btn_new","btn_dup","btn_del","btn_save"):
                if hasattr(self, btn_name):
                    getattr(self, btn_name).state(["disabled"])
            # Filters
            cats = get_all_categories(self.active_list) if self.active_list else ["(all)"]
            try:
                self.cat_combo["values"] = cats; self.cat_combo.set("(all)")
            except Exception:
                pass
            try:
                types = sorted({(it.get("type") or "").strip() for it in self.active_list if (it.get("type") or "").strip()})
                if hasattr(self, "type_combo"):
                    self.type_combo["values"] = ["(all)"] + types; self.type_combo.set("(all)")
            except Exception:
                pass
            self.search_var.set("")
            # No category context in All mode
            try:
                self.form.set_category_context("")
            except Exception:
                pass
            self.refresh_list()
            return

        # Single-file mode
        if not dataset:
            # Unknown file selection; clear view
            self.active_dataset = None; self.active_file = None; self.active_list = []
            self.listbox.delete(0,"end")
            try:
                self.count_var.set("Entries: 0")
            except Exception:
                pass
            return

        self.active_dataset = dataset
        self.active_file = fname
        try:
            self.active_list = list(dataset.data or [])
        except Exception:
            self.active_list = []

        # Enable actions
        for btn_name in ("btn_new","btn_dup","btn_del","btn_save"):
            if hasattr(self, btn_name):
                getattr(self, btn_name).state(["!disabled"])

        # Filters
        cats = get_all_categories(self.active_list) if self.active_list else ["(all)"]
        try:
            self.cat_combo["values"] = cats; self.cat_combo.set("(all)")
        except Exception:
            pass
        try:
            types = sorted({(it.get("type") or "").strip() for it in self.active_list if (it.get("type") or "").strip()})
            if hasattr(self, "type_combo"):
                self.type_combo["values"] = ["(all)"] + types; self.type_combo.set("(all)")
        except Exception:
            pass

        self.search_var.set("")
        # Attempt to set category context based on filter if present
        context_cat = ""
        val = getattr(self, "cat_combo", None).get() if hasattr(self, "cat_combo") else ""
        if val and val != "(all)" and ":" in val:
            k, v = val.split(":", 1)
            if k == "category":
                context_cat = v.strip().lower()
        try:
            self.form.set_category_context(context_cat)
        except Exception:
            pass
        self.refresh_list()



    def refresh_list(self):
        # Robust refresh that works in single-file and "(All Item files)" mode
        q = (self.search_var.get() or "").lower().strip()
        cat = (self.cat_combo.get() or "(all)")
        try:
            itype = (self.type_combo.get() or "(all)")
        except Exception:
            itype = "(all)"

        items = list(self.active_list or [])
        self.listbox.delete(0, "end")
        self.filtered_indices = []

        for i, it in enumerate(items):
            show = True
            name = str(it.get("name","") or "")
            iid  = str(it.get("id","") or "")
            if q and (q not in name.lower()) and (q not in iid.lower()):
                show = False
            if show and cat and cat != "(all)":
                try:
                    from_category = infer_category(it)
                except Exception:
                    from_category = ""
                if from_category != cat:
                    show = False
            if show and itype and itype != "(all)":
                if (it.get("type","") or "") != itype:
                    show = False
            if show:
                self.filtered_indices.append(i)
                label = f"{iid} — {name} [{infer_category(it)}]"
                self.listbox.insert("end", label)

        # Count label
        try:
            total = len(items)
            shown = len(self.filtered_indices)
            if q or (cat and cat != "(all)") or (itype and itype != "(all)"):
                self.count_var.set(f"Entries: {total} • showing {shown}")
            else:
                self.count_var.set(f"Entries: {total}")
        except Exception:
            pass



    def on_select(self, *_):
        if not self.active_list: return
        sel = self.listbox.curselection()
        if not sel: return
        idx = self.filtered_indices[sel[0]]
        self.selected_index = idx
        # Update form category context from selected item
        cat = (self.active_list[idx].get("category") or "").lower()
        self.form.set_category_context(cat)
        self.form.set_object(self.active_list[idx])

    def on_new(self):
        if not self.active_dataset:
            messagebox.showinfo("All NPC files", "Select a single NPC file to add a new NPC.")
            return
        existing_ids = {it.get("id","") for it in self.active_list}
        item = dict(DEFAULT_ITEM); item["id"] = ensure_item_id(item, existing_ids)
        # If current filter is on a category: seed it
        cur = self.cat_combo.get()
        if cur and cur != "(all)":
            # extract "category:xyz" to "xyz"
            if ":" in cur:
                k, v = cur.split(":",1)
                if k == "category":
                    item["category"] = v
        self.active_list.append(item); self.refresh_list(); self.listbox.select_set("end"); self.on_select()

    def on_dup(self):
        if self.selected_index is None or not self.active_dataset:
            messagebox.showinfo("All NPC files", "Select a single NPC file to duplicate into.")
            return
        src = dict(self.active_list[self.selected_index])
        existing_ids = {it.get("id","") for it in self.active_list}
        src["id"] = ensure_item_id(src, existing_ids)
        self.active_list.append(src); self.refresh_list(); self.listbox.select_set("end"); self.on_select()

    def on_del(self):
        if self.selected_index is None or not self.active_dataset:
            messagebox.showinfo("All NPC files", "Select a single NPC file to delete from.")
            return
        if not messagebox.askyesno("Delete item", "Delete the selected item?"): return
        del self.active_list[self.selected_index]
        self.rebuild_global_items_index(); self.refresh_list()

    def on_save(self):
        dataset = self.active_dataset
        if not dataset:
            messagebox.showinfo("All NPC files", "Aggregate view cannot be saved. Select a single file.")
            return
        if self.selected_index is not None and self.selected_index < len(self.active_list):
            obj = self.form.get_object()
            if obj is None: return
            # normalize any legacy 8-digit IDs to 6-digit
            if isinstance(obj.get("id"), str):
                m8 = re.match(r"^([A-Z]{2,3})(\d{8})$", obj["id"])
                if m8:
                    obj["id"] = m8.group(1) + m8.group(2)[-6:]
            ids = {it.get("id","") for idx, it in enumerate(self.active_list) if idx != self.selected_index}
            obj["id"] = ensure_item_id(obj, ids)
            try: obj["slot"] = derive_slot(obj)
            except Exception: pass
            for legacy in ("bonus","resist","trait"):
                if legacy in obj: del obj[legacy]
            self.active_list[self.selected_index] = obj
        dataset.data = self.active_list
        save_json_file(dataset.path, dataset.root, dataset.data, dataset.list_key)
        self.rebuild_global_items_index()
        messagebox.showinfo("Saved", f"Saved {dataset.file_name}")

    def on_roll_preview(self):
        if self.selected_index is None or not self.active_list:
            messagebox.showinfo("Roll Preview", "Select an item first."); return
        item = self.active_list[self.selected_index]
        for fld in ["fixed_bonus","possible_bonus","fixed_resist","possible_resist","fixed_trait","possible_trait"]:
            item.setdefault(fld, [])
        RollPreviewDialog(self, item)

class NPCsTab(ttk.Frame):

    def __init__(self, master):
        super().__init__(master)
        self.datasets: Dict[str, Dataset] = {}
        self.active_dataset: Optional[Dataset] = None
        self.active_file = None
        self.npcs: List[dict] = []
        self.filtered_indices: List[int] = []
        self.selected_index: Optional[int] = None

        left = ttk.Frame(self); left.pack(side="left", fill="y", padx=6, pady=6)
        right = ttk.Frame(self); right.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        ttk.Label(left, text="NPC File").pack(anchor="w")
        self.file_combo = ttk.Combobox(left, state="readonly", width=28)
        self.file_combo.pack(fill="x", pady=(0,6)); self.file_combo.bind("<<ComboboxSelected>>", self.on_file_change)

        self.count_var = tk.StringVar(value="Entries: 0")
        ttk.Label(left, textvariable=self.count_var).pack(anchor="w", pady=(0,6))

        ttk.Label(left, text="Search").pack(anchor="w")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search_var); ent.pack(fill="x", pady=(0,6))
        ent.bind("<KeyRelease>", lambda e: self.refresh_list())

        ttk.Label(left, text="Faction").pack(anchor="w")
        self.faction_combo = ttk.Combobox(left, state="readonly")
        self.faction_combo.pack(fill="x", pady=(0,6))
        self.faction_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        # --- NEW: Sex, Race, Class, Type filters ---
        ttk.Label(left, text="Sex").pack(anchor="w")
        self.sex_combo = ttk.Combobox(left, state="readonly")
        self.sex_combo.pack(fill="x", pady=(0,6))
        self.sex_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        ttk.Label(left, text="Race").pack(anchor="w")
        self.race_combo = ttk.Combobox(left, state="readonly")
        self.race_combo.pack(fill="x", pady=(0,6))
        self.race_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        ttk.Label(left, text="Class").pack(anchor="w")
        self.class_combo = ttk.Combobox(left, state="readonly")
        self.class_combo.pack(fill="x", pady=(0,6))
        self.class_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        ttk.Label(left, text="Type").pack(anchor="w")
        self.type_combo = ttk.Combobox(left, state="readonly")
        self.type_combo.pack(fill="x", pady=(0,6))
        self.type_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        self.listbox = tk.Listbox(left, height=24); self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        btns = ttk.Frame(left); btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="New", command=self.on_new).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Duplicate", command=self.on_dup).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Delete", command=self.on_del).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Save File", command=self.on_save).pack(side="left", expand=True, fill="x", padx=2)

        self.form = KeyValueForm(right); self.form.pack(fill="both", expand=True)
        self.load_datasets()

    def load_datasets(self):
        self.datasets.clear()
        if not os.path.isdir(NPCS_DIR):
            messagebox.showwarning("Missing folder", f"NPC directory not found: {NPCS_DIR}")
            return
        files_found = []
        for fname in discover_json_files(NPCS_DIR):
            path = os.path.join(NPCS_DIR, fname)
            loaded = load_dataset(path, preferred_keys=("npcs",), allow_first_list=False, fallback_key="npcs")
            if not loaded: continue
            root, lst, list_key = loaded
            if isinstance(root, dict) and list_key != "npcs": continue
            if not isinstance(lst, list): continue
            self.datasets[fname] = Dataset(fname, path, root, list_key, lst)
            files_found.append(fname)
        if not files_found:
            self.file_combo.set(""); self.faction_combo["values"] = []
            self.listbox.delete(0,"end"); self.form.set_object({}); return
        self.file_combo["values"] = ["(All NPC files)"] + files_found
        self.file_combo.set("(All Item files)")
        self.file_combo.set("(All NPC files)")
        self.on_file_change()

    def on_file_change(self, *_):
        fname = self.file_combo.get()
        dataset = self.datasets.get(fname)

        # Handle aggregate mode BEFORE any early returns
        if fname == "(All NPC files)":
            self.active_dataset = None
            self.active_file = None
            alln = []
            for ds in self.datasets.values():
                if isinstance(ds.data, list):
                    alln.extend(ds.data)
            self.npcs = alln
            try:
                self.count_var.set(f"Entries: {len(self.npcs)}")
            except Exception:
                pass
            # Disable mutating actions in aggregate mode
            for btn_name in ("btn_new","btn_dup","btn_del","btn_save"):
                if hasattr(self, btn_name):
                    getattr(self, btn_name).state(["disabled"])
            self.refresh_filters()
            self.refresh_list()
            return

        # If no dataset for a specific file, clear and bail
        if not dataset:
            self.active_dataset = None; self.active_file = None; self.npcs = []
            self.listbox.delete(0,"end"); self.form.set_object({})
            try:
                self.faction_combo["values"] = []
                self.count_var.set("Entries: 0")
            except Exception:
                pass
            return

        # Single-file mode
        self.active_dataset = dataset
        self.active_file = fname
        self.npcs = dataset.data
        try:
            self.count_var.set(f"Entries: {len(self.npcs)}")
        except Exception:
            pass
        # Enable actions in single-file mode
        for btn_name in ("btn_new","btn_dup","btn_del","btn_save"):
            if hasattr(self, btn_name):
                getattr(self, btn_name).state(["!disabled"])
        self.refresh_filters(); self.refresh_list()


    def refresh_filters(self):
        factions, sexes, races, classes, types = set(), set(), set(), set(), set()
        for n in self.npcs:
            factions.add((n.get("faction","") or "Neutral").strip() or "Neutral")
            s = (n.get("sex","") or "").strip()
            r = (n.get("race","") or "").strip()
            c = (n.get("class","") or "").strip()
            t = (n.get("type","") or "").strip()
            if s: sexes.add(s)
            if r: races.add(r)
            if c: classes.add(c)
            if t: types.add(t)
        self.faction_combo["values"] = ["(all)"] + sorted(factions); self.faction_combo.set(self.faction_combo.get() or "(all)")
        if hasattr(self, 'sex_combo'):
            self.sex_combo["values"]   = ["(all)"] + sorted(sexes);   self.sex_combo.set(self.sex_combo.get() or "(all)")
        if hasattr(self, 'race_combo'):
            self.race_combo["values"]  = ["(all)"] + sorted(races);   self.race_combo.set(self.race_combo.get() or "(all)")
        if hasattr(self, 'class_combo'):
            self.class_combo["values"] = ["(all)"] + sorted(classes); self.class_combo.set(self.class_combo.get() or "(all)")
        if hasattr(self, 'type_combo'):
            self.type_combo["values"]  = ["(all)"] + sorted(types);   self.type_combo.set(self.type_combo.get() or "(all)")

    def refresh_list(self):
        self.listbox.delete(0,"end"); self.filtered_indices = []
        if not self.npcs:
            self.form.set_object({})
            try:
                self.count_var.set("Entries: 0")
            except Exception:
                pass
            return
        q = (self.search_var.get() or "").lower().strip()
        fac = (self.faction_combo.get() or "(all)").strip()
        sex = (self.sex_combo.get() or "").strip() if hasattr(self, 'sex_combo') else ""
        race = (self.race_combo.get() or "").strip() if hasattr(self, 'race_combo') else ""
        clazz = (self.class_combo.get() or "").strip() if hasattr(self, 'class_combo') else ""
        ntype = (self.type_combo.get() or "").strip() if hasattr(self, 'type_combo') else ""
        for i, n in enumerate(self.npcs):
            name = str(n.get("name",""))
            show = True
            if q and q not in name.lower(): show = False
            if show and fac and fac != "(all)":
                faction = (n.get("faction","") or "Neutral").strip() or "Neutral"
                if faction != fac: show = False
            if show and sex and sex != "(all)":
                if (n.get("sex","") or "").strip() != sex: show = False
            if show and race and race != "(all)":
                if (n.get("race","") or "").strip() != race: show = False
            if show and clazz and clazz != "(all)":
                if (n.get("class","") or "").strip() != clazz: show = False
            if show and ntype and ntype != "(all)":
                if (n.get("type","") or "").strip() != ntype: show = False
            if show:
                self.filtered_indices.append(i)
                self.listbox.insert("end", f"{n.get('id','?')}  {name}")
        self.selected_index = None; self.form.set_object({})
        try:
            total = len(self.npcs)
            shown = len(self.filtered_indices)
            if q or (fac and fac != "(all)") or (sex and sex != "(all)") or (race and race != "(all)") or (clazz and clazz != "(all)") or (ntype and ntype != "(all)"):
                self.count_var.set(f"Entries: {total} • showing {shown}")
            else:
                self.count_var.set(f"Entries: {total}")
        except Exception:
            pass

    def on_select(self, *_):
        if not self.npcs: return
        sel = self.listbox.curselection()
        if not sel: return
        idx = self.filtered_indices[sel[0]]
        self.selected_index = idx
        # Ensure new text fields are present for editing
        try:
            npc = self.npcs[idx]
            if isinstance(npc, dict):
                npc.setdefault("clothing_short", "")
                npc.setdefault("clothing_long", "")
                npc.setdefault("personality_short", "")
                npc.setdefault("personality_long", "")
        except Exception:
            pass
        self.form.set_object(self.npcs[idx])

    def on_new(self):
        if not self.active_dataset: return
        existing_ids = {n.get("id","") for n in self.npcs}
        npc = dict(DEFAULT_NPC); npc["id"] = ensure_npc_id(npc, existing_ids)
        self.npcs.append(npc); self.refresh_filters(); self.refresh_list(); self.listbox.select_set("end"); self.on_select()

    def on_dup(self):
        if self.selected_index is None or not self.active_dataset: return
        src = dict(self.npcs[self.selected_index])
        existing_ids = {n.get("id","") for n in self.npcs}
        src["id"] = ensure_npc_id(src, existing_ids)
        self.npcs.append(src); self.refresh_list(); self.listbox.select_set("end"); self.on_select()

    def on_del(self):
        if self.selected_index is None or not self.active_dataset: return
        if not messagebox.askyesno("Delete NPC", "Delete the selected NPC?"): return
        del self.npcs[self.selected_index]; self.refresh_filters(); self.refresh_list()

    def on_save(self):
        dataset = self.active_dataset
        if not dataset: return
        if self.selected_index is not None and self.selected_index < len(self.npcs):
            obj = self.form.get_object()
            if obj is None: return
            # normalize any legacy 8-digit IDs to 6-digit
            if isinstance(obj.get("id"), str):
                m8 = re.match(r"^([A-Z]{2,3})(\d{8})$", obj["id"])
                if m8:
                    obj["id"] = m8.group(1) + m8.group(2)[-6:]
            ids = {n.get("id","") for idx, n in enumerate(self.npcs) if idx != self.selected_index}
            obj["id"] = ensure_npc_id(obj, ids)
            self.npcs[self.selected_index] = obj
        dataset.data = self.npcs
        save_json_file(dataset.path, dataset.root, dataset.data, dataset.list_key)
        messagebox.showinfo("Saved", f"Saved {dataset.file_name}")

# ---------- App ----------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RPGenesis Entity Editor — PRO(7) — ID=6 — Affixes Vertical")
        self.geometry("1160x760"); self.minsize(980, 640)
        apply_ui_styling(self)

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.items_tab = ItemsTab(nb); self.npcs_tab = NPCsTab(nb)
        nb.add(self.items_tab, text="Items"); nb.add(self.npcs_tab, text="NPCs")

if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception as e:
        print("Error:", e, file=sys.stderr)
