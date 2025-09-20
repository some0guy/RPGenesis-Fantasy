
#!/usr/bin/env python3
# RPGenesis Entity Editor — Fixed build (has set_object, components filter, roll preview, derived slot)
import json, os, re, sys, time, random
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Dict, Tuple
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import tkinter.font as tkfont
def apply_ui_styling(root: tk.Tk, scale: float = 1.15):
    try:
        root.tk.call('tk', 'scaling', scale)
    except Exception: pass
    style = ttk.Style(root)
    try:
        for theme in ("vista","clam","default"):
            if theme in style.theme_names():
                style.theme_use(theme); break
    except Exception: pass
    base = tkfont.nametofont("TkDefaultFont"); base.configure(family="Segoe UI", size=10)
    mono = tkfont.nametofont("TkFixedFont");  mono.configure(family="Consolas", size=10)
    style.configure("TLabel", font=("Segoe UI", 10))
    style.configure("TButton", font=("Segoe UI", 10), padding=(8,5))
    style.configure("TEntry", padding=4)
    style.configure("TCombobox", padding=4)
    style.configure("TNotebook.Tab", padding=(14,10))


BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
ITEMS_DIR  = os.path.join(BASE_DIR, "data", "items")
NPCS_DIR   = os.path.join(BASE_DIR, "data", "npcs")

RE_ID_ITEM = re.compile(r"^IT\d{8}$")
RE_ID_NPC  = re.compile(r"^(?:NP|NPC)\d{8}$")

SLOT_OPTIONS = [
    "head","chest","legs","feet","hands","ring","amulet","cloak","belt",
    "weapon","offhand","two_handed","consumable","material","misc"
]
CATEGORY_OPTIONS = [
    "weapons","weapon","armour","armor","clothing","accessories","accessory",
    "consumables","materials","quest","misc"
]

BONUS_KEYS = [
    "PHY","TEC","ARC","VIT","INS","SOC","KNO","FTH",
    "hp","mp","initiative","speed",
    "crit_chance","crit_damage",
    "armor","evasion","block",
    "attack_rating","spell_power","penetration",
    "attack","defense","stamina","strength","intelligence","dexterity","health","mana"
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
    "id": "IT00000000",
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
    "id": "NP00000000",
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
    "notes": ""
}

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
        with open(path, "r", encoding="utf-8") as f:
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

def ensure_item_id(item, existing_ids):
    _id = item.get("id","").strip()
    if RE_ID_ITEM.match(_id) and _id not in existing_ids:
        return _id
    base = 1
    if existing_ids:
        nums = []
        for s in existing_ids:
            m = re.match(r"IT(\d{8})", (s or ""))
            if m: nums.append(int(m.group(1)))
        base = (max(nums) + 1) if nums else 1
    return f"IT{base:08d}"

def ensure_npc_id(npc, existing_ids):
    _id = (npc.get("id","") or "").strip().upper()
    if RE_ID_NPC.match(_id) and _id not in existing_ids:
        return _id
    prefix = "NP"
    nums = []
    for s in existing_ids:
        if not s: continue
        m = re.match(r"^(NP|NPC)(\d{8})$", s.strip().upper())
        if m:
            nums.append(int(m.group(2)))
            if m.group(1) == "NPC":
                prefix = "NPC"
    next_num = (max(nums) + 1) if nums else 1
    if RE_ID_NPC.match(_id):
        prefix = re.match(r"^(NP|NPC)", _id).group(1)
    return f"{prefix}{next_num:08d}"

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

# ---- Slot inference ----
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

class ComboField(ttk.Frame):
    def __init__(self, master, values: List[str], initial: str = "", allow_custom=True):
        super().__init__(master)
        self.values = list(values)
        self.var = tk.StringVar(value=initial)
        self.combo = ttk.Combobox(self, values=self.values, textvariable=self.var, state="readonly")
        self.combo.pack(side="left", fill="x", expand=True)
        if allow_custom:
            ttk.Button(self, text="Custom…", command=self.add_custom).pack(side="left", padx=4)
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

class MultiSelectField(ttk.Frame):
    def __init__(self, master, options: List[str], initial: List[str] = None):
        super().__init__(master)
        self.options = list(options)
        self.lb = tk.Listbox(self, selectmode="multiple", height=8, exportselection=False)
        self.lb.pack(side="left", fill="both", expand=True)
        for opt in self.options:
            self.lb.insert("end", opt)
        btns = ttk.Frame(self); btns.pack(side="left", fill="y", padx=4)
        ttk.Button(btns, text="Add…", command=self.add_custom).pack(fill="x", pady=2)
        ttk.Button(btns, text="Remove", command=self.remove_selected).pack(fill="x", pady=2)
        self.set(initial or [])
    def add_custom(self):
        s = simpledialog.askstring("Add value", "Enter value:")
        if not s: return
        if s not in self.options:
            self.options.append(s); self.lb.insert("end", s)
        idx = self.options.index(s); self.lb.selection_set(idx)
    def remove_selected(self):
        for i in list(self.lb.curselection()):
            self.lb.selection_clear(i)
    def get(self) -> List[str]:
        return [self.options[i] for i in self.lb.curselection()]
    def set(self, values: List[str]):
        self.lb.selection_clear(0, "end")
        if not values: return
        for i, opt in enumerate(self.options):
            if opt in values:
                self.lb.selection_set(i)



class ComponentsField(ttk.Frame):
    """
    Components/materials picker with:
    - Single-select available list
    - Single-select selected list
    - Add ▶ / ◀ Remove buttons
    - Move Up / Move Down / Clear
    - Category filter + text filter
    - Click-outside deselect (does not interfere with buttons)
    """
    def __init__(self, master, labels):
        super().__init__(master)
        self.all_labels = list(sorted(set(labels)))
        self.selected = []

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # LEFT: filters + available
        left = ttk.Frame(self); left.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        top = ttk.Frame(left); top.pack(fill="x", pady=(0,6))
        ttk.Label(top, text="Filter").pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.filter_var, width=24).pack(side="left", padx=(6,6))

        self.cat_var = tk.StringVar(value="materials")
        self.cat_combo = ttk.Combobox(
            top, textvariable=self.cat_var, state="readonly", width=18,
            values=("materials","armour","weapons","clothing","accessories","trinkets","consumables","misc")
        )
        self.cat_combo.pack(side="left")

        self.lb = tk.Listbox(left, selectmode="browse", height=12, exportselection=False)
        self.lb.pack(fill="both", expand=True)
        btns = ttk.Frame(left); btns.pack(fill="x", pady=(6,0))
        ttk.Button(btns, text="Add ▶", command=self._add).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(btns, text="◀ Remove", command=self._remove).pack(side="left", expand=True, fill="x", padx=3)

        # RIGHT: selected
        right = ttk.Frame(self); right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Currently Selected").pack(anchor="w")
        self.sel = tk.Listbox(right, selectmode="browse", height=14, exportselection=False)
        self.sel.pack(fill="both", expand=True, pady=(4,0))
        rbtns = ttk.Frame(right); rbtns.pack(fill="x", pady=(6,0))
        ttk.Button(rbtns, text="Move Up", command=self._up).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(rbtns, text="Move Down", command=self._down).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(rbtns, text="Clear", command=self._clear).pack(side="left", expand=True, fill="x", padx=3)

        # Bindings
        self.filter_var.trace_add("write", lambda *_: self._refill())
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self._refill())

        # Click-outside clears selections (but not when clicking inside this widget)
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
        if cat == "materials":   return any(w in L for w in ["ingot","ore","leather","cloth","hide","wood","herb","glass","crystal","thread","plate","plank","pane","powder"])
        if cat == "armour":      return any(w in L for w in ["helm","hood","chest","cuirass","breast","greave","legging","boot","glove","gaunt","cloak","belt","shield","armor","armour"])
        if cat == "weapons":     return any(w in L for w in ["sword","dagger","axe","mace","hammer","spear","bow","crossbow","staff","wand","polearm","halberd","glaive"])
        if cat == "clothing":    return any(w in L for w in ["robe","tunic","vest","pants","trouser","skirt","kilt","hat","mask","glove","boot","shoe","belt","cloak"])
        if cat == "accessories": return any(w in L for w in ["ring","amulet","necklace","talisman","bracelet","bracer","circlet"])
        if cat == "trinkets":    return any(w in L for w in ["vase","figurine","goblet","pendant","mirror","fan","charm","bead","box","brooch","tin","mask","snow globe","paperweight","candleholder","kaleidoscope"])
        if cat == "consumables": return any(w in L for w in ["potion","elixir","tonic","draft","draught","oil","bomb","phial","tincture","ration","water","brew","tea"])
        return True

    def _refill(self):
        flt = (self.filter_var.get() or "").strip().lower()
        cat = (self.cat_var.get() or "misc").strip().lower()
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


class KeyValueForm(ttk.Frame):
    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self.current_obj = {}
        self.inputs: Dict[str, Tuple[str, Any]] = {}
        self.raw_mode = False

        bar = ttk.Frame(self); bar.pack(fill="x", pady=(0,4))
        self.toggle_btn = ttk.Button(bar, text="Raw JSON", command=self.toggle_raw); self.toggle_btn.pack(side="right")

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True); self.scroll.pack(side="right", fill="y")

        self.raw_text = tk.Text(self, height=24); self.raw_text.configure(font=("Courier", 10))

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

    def _make_widget_for(self, key: str, val: Any):
        # Roll config toggles
        if key in ('randomise_on_pickup','randomize_on_pickup','randomise_on_pickup_enabled'):
            var = tk.BooleanVar(value=bool(val))
            cb = ttk.Checkbutton(self.inner, text='Randomise on pickup', variable=var)
            cb.var = var
            return ('bool_toggle', cb)
        if key in ('level_bind','bind_to_level','level_locked'):
            var = tk.BooleanVar(value=bool(val))
            cb = ttk.Checkbutton(self.inner, text='Bind to level on pickup', variable=var)
            cb.var = var
            return ('bool_toggle', cb)
        if key in ('scale_with_level','scales_with_level'):
            # Deprecated: hide from editor
            return ('hidden', None)

        if key in ("fixed_bonus","possible_bonus"):
            w = KeyPickerField(self.inner, BONUS_KEYS, [v for v in (val or []) if isinstance(v,str)], "Available Bonus", "Selected Bonus")
            return (f"{key}_keys", w)
        if key in ("fixed_resist","possible_resist"):
            w = KeyPickerField(self.inner, RESIST_KEYS, [v for v in (val or []) if isinstance(v,str)], "Available Resist", "Selected Resist")
            return (f"{key}_keys", w)
        if key in ("fixed_trait","possible_trait"):
            w = KeyPickerField(self.inner, TRAIT_OPTIONS, [v for v in (val or []) if isinstance(v,str)], "Available Trait", "Selected Trait")
            return (f"{key}_keys", w)
        if key == "slot":
            var = tk.StringVar(value=str(val or ""))
            entry = ttk.Entry(self.inner, textvariable=var, state="readonly")
            return ("slot_readonly", (entry, var))
        if key == "category":
            w = ComboField(self.inner, CATEGORY_OPTIONS, str(val or "")); return ("category_combo", w)
        if key == "type":
            var = tk.StringVar(value=str(val or ""))
            ent = ttk.Entry(self.inner, textvariable=var)
            def _on_type_change(*_):
                snap = {}
                cat_tuple = self.inputs.get("category")
                if cat_tuple and cat_tuple[0] == "category_combo":
                    snap["category"] = cat_tuple[1].get()
                snap["type"] = var.get()
                inferred = derive_slot(snap)
                sl_tuple = self.inputs.get("slot")
                if sl_tuple and sl_tuple[0] == "slot_readonly":
                    sl_tuple[1][1].set(inferred)
            var.trace_add("write", _on_type_change)
            return ("scalar", ent)
        if key == "components":
            labels = list(ALL_ITEMS_LABEL_TO_ID.keys())
            w = ComponentsField(self.inner, labels)
            init_labels = []
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        init_labels.append(ALL_ITEMS_ID_TO_LABEL.get(v, v))
            w.set(init_labels)
            return ("components_labels", w)
        if key in ("bonus","resist","trait"):
            text = tk.Text(self.inner, height=3, width=40)
            text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
            text.configure(state="disabled")
            return ("legacy_json", text)
        if isinstance(val, (dict, list)):
            text = tk.Text(self.inner, height=4, width=40); text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
            return ("json", text)
        entry = ttk.Entry(self.inner); entry.insert(0, "" if val is None else str(val))
        return ("scalar", entry)

    def set_object(self, obj: dict):
        self.current_obj = dict(obj) if obj else {}
        # Hide deprecated key entirely
        if 'scale_with_level' in self.current_obj:
            self.current_obj.pop('scale_with_level', None)

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

        for w in self.inner.winfo_children(): w.destroy()
        self.inputs.clear()

        preferred = ["id","name","type","rarity","value","weight","description",
                     "slot","category","components",
                     "fixed_bonus","possible_bonus","fixed_resist","possible_resist","fixed_trait","possible_trait"]
        keys = list(self.current_obj.keys())
        keys_sorted = preferred + [k for k in keys if k not in preferred]
        row = 0
        for k in keys_sorted:
            val = self.current_obj.get(k)
            ttk.Label(self.inner, text=k).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            kind, widget = self._make_widget_for(k, val)
            if kind == 'hidden':
                continue
            self.inputs[k] = (kind, widget)
            if kind == "slot_readonly":
                widget[0].grid(row=row, column=1, sticky="we", padx=6, pady=4)
            else:
                widget.grid(row=row, column=1, sticky="we", padx=6, pady=4)
            row += 1

        # derive slot once after layout
        try:
            snap = {}
            t = self.inputs.get("type")
            if t and t[0] == "scalar":
                snap["type"] = t[1].get()
            c = self.inputs.get("category")
            if c and c[0] == "category_combo":
                snap["category"] = c[1].get()
            inferred = derive_slot(snap)
            sl = self.inputs.get("slot")
            if sl and sl[0] == "slot_readonly":
                sl[1][1].set(inferred)
        except Exception:
            pass
        self.inner.columnconfigure(1, weight=1)

    def get_object(self):
        if self.raw_mode:
            try:
                return json.loads(self.raw_text.get("1.0","end"))
            except Exception as e:
                messagebox.showerror("Invalid JSON", str(e))
                return None
        out = {}
        for k, (kind, widget) in self.inputs.items():
            if kind in ("json","legacy_json","hidden"):
                continue
            elif kind in ("category_combo",):
                out[k] = widget.get()
            elif kind == 'bool_toggle':
                try:
                    out[k] = bool(widget.var.get())
                except Exception:
                    out[k] = bool(getattr(widget, 'get', lambda: False)())
            elif kind == "components_labels":
                labels = widget.get()
                ids = []
                for lab in labels:
                    iid = ALL_ITEMS_LABEL_TO_ID.get(lab)
                    if iid: ids.append(iid)
                out["components"] = ids
            elif kind.endswith("_keys"):
                out[k] = widget.get()
            elif kind == "slot_readonly":
                pass
            else:
                s = widget.get()
                if s.strip() == "":
                    out[k] = ""
                else:
                    if re.match(r"^-?\d+(\.\d+)?$", s.strip()):
                        out[k] = float(s) if "." in s else int(s)
                    else:
                        out[k] = s
        try:
            out["slot"] = derive_slot(out)
        except Exception:
            out["slot"] = out.get("slot","") or ""
        # Remove deprecated key
        if 'scale_with_level' in out:
            out.pop('scale_with_level', None)
        return out

# ---- Roll preview helpers ----
def _load_loot_config():
    cfg_path = os.path.join(BASE_DIR, "data", "meta", "loot_rolls.json")
    default = {
        "rarity_slots": {
            "bonus":    {"common":[0,1],"uncommon":[1,1],"rare":[2,2],"epic":[3,3],"legendary":[4,4],"relic":[5,5]},
            "resist":   {"common":[0,0],"uncommon":[0,1],"rare":[1,1],"epic":[2,2],"legendary":[2,3],"relic":[3,3]},
            "trait":    {"common":[0,0],"uncommon":[0,1],"rare":[1,1],"epic":[1,2],"legendary":[2,2],"relic":[2,3]}
        },
        "global_bonus_weights": {k:1 for k in BONUS_KEYS},
        "global_resist_weights": {k:1 for k in RESIST_KEYS},
        "category_bias": {}
    }
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                user = json.load(f)
            def merge(a,b):
                if isinstance(a, dict) and isinstance(b, dict):
                    out = dict(a)
                    for k,v in b.items():
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
        self.out.configure(font=("Courier", 10))
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

        ttk.Label(left, text="Search").pack(anchor="w")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search_var); ent.pack(fill="x", pady=(0,6))
        ent.bind("<KeyRelease>", lambda e: self.refresh_list())

        ttk.Label(left, text="Category Filter").pack(anchor="w")
        self.cat_combo = ttk.Combobox(left, state="readonly")
        self.cat_combo.pack(fill="x", pady=(0,6))
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

        self.listbox = tk.Listbox(left, height=24); self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        btns = ttk.Frame(left); btns.pack(fill="x", pady=6)
        ttk.Button(btns, text="New", command=self.on_new).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Duplicate", command=self.on_dup).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Delete", command=self.on_del).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns, text="Save File", command=self.on_save).pack(side="left", expand=True, fill="x", padx=2)
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
        self.file_combo["values"] = files_found; self.file_combo.current(0)
        self.on_file_change()

    def on_file_change(self, *_):
        fname = self.file_combo.get()
        dataset = self.datasets.get(fname)
        if not dataset:
            self.active_dataset = None; self.active_file = None; self.active_list = []
            self.listbox.delete(0,"end"); self.form.set_object({}); return
        self.active_dataset = dataset; self.active_file = fname; self.active_list = dataset.data
        cats = get_all_categories(self.active_list) if self.active_list else ["(all)"]
        self.cat_combo["values"] = cats; self.cat_combo.set("(all)")
        self.search_var.set("")
        self.rebuild_global_items_index()
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0,"end"); self.filtered_indices = []
        if not self.active_list: self.form.set_object({}); return
        q = self.search_var.get().lower().strip(); cat = self.cat_combo.get()
        for i, it in enumerate(self.active_list):
            name = str(it.get("name",""))
            show = True
            if q and q not in name.lower(): show = False
            if show and cat and cat != "(all)":
                if infer_category(it) != cat: show = False
            if show:
                self.filtered_indices.append(i)
                self.listbox.insert("end", f"{it.get('id','?')}  {name}")
        self.selected_index = None; self.form.set_object({})

    def on_select(self, *_):
        if not self.active_list: return
        sel = self.listbox.curselection()
        if not sel: return
        idx = self.filtered_indices[sel[0]]
        self.selected_index = idx
        self.form.set_object(self.active_list[idx])

    def on_new(self):
        if not self.active_dataset: return
        existing_ids = {it.get("id","") for it in self.active_list}
        item = dict(DEFAULT_ITEM); item["id"] = ensure_item_id(item, existing_ids)
        self.active_list.append(item); self.refresh_list(); self.listbox.select_set("end"); self.on_select()

    def on_dup(self):
        if self.selected_index is None or not self.active_dataset: return
        src = dict(self.active_list[self.selected_index])
        existing_ids = {it.get("id","") for it in self.active_list}
        src["id"] = ensure_item_id(src, existing_ids)
        self.active_list.append(src); self.refresh_list(); self.listbox.select_set("end"); self.on_select()

    def on_del(self):
        if self.selected_index is None or not self.active_dataset: return
        if not messagebox.askyesno("Delete item", "Delete the selected item?"): return
        del self.active_list[self.selected_index]
        self.rebuild_global_items_index(); self.refresh_list()

    def on_save(self):
        dataset = self.active_dataset
        if not dataset: return
        if self.selected_index is not None and self.selected_index < len(self.active_list):
            obj = self.form.get_object()
            if obj is None: return
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
        self.datasets = {}
        self.active_dataset = None
        self.active_file = None
        self.npcs = []
        self.filtered_indices = []
        self.selected_index = None

        left = ttk.Frame(self); left.pack(side="left", fill="y", padx=6, pady=6)
        right = ttk.Frame(self); right.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        ttk.Label(left, text="NPC File").pack(anchor="w")
        self.file_combo = ttk.Combobox(left, state="readonly", width=28)
        self.file_combo.pack(fill="x", pady=(0,6)); self.file_combo.bind("<<ComboboxSelected>>", self.on_file_change)

        ttk.Label(left, text="Search").pack(anchor="w")
        self.search_var = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search_var); ent.pack(fill="x", pady=(0,6))
        ent.bind("<KeyRelease>", lambda e: self.refresh_list())

        ttk.Label(left, text="Faction").pack(anchor="w")
        self.faction_combo = ttk.Combobox(left, state="readonly")
        self.faction_combo.pack(fill="x", pady=(0,6))
        self.faction_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())

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
        self.file_combo["values"] = files_found; self.file_combo.current(0)
        self.on_file_change()

    def on_file_change(self, *_):
        fname = self.file_combo.get()
        dataset = self.datasets.get(fname)
        if not dataset:
            self.active_dataset = None; self.active_file = None; self.npcs = []
            self.listbox.delete(0,"end"); self.form.set_object({}); self.faction_combo["values"] = []; return
        self.active_dataset = dataset; self.active_file = fname; self.npcs = dataset.data
        self.refresh_filters(); self.refresh_list()

    def refresh_filters(self):
        factions = set()
        for n in self.npcs:
            faction = (n.get("faction","") or "Neutral").strip() or "Neutral"
            factions.add(faction)
        values = ["(all)"] + sorted(factions)
        self.faction_combo["values"] = values; self.faction_combo.set("(all)")

    def refresh_list(self):
        self.listbox.delete(0,"end"); self.filtered_indices.clear()
        if not self.npcs: self.form.set_object({}); return
        q = self.search_var.get().lower().strip(); fac = self.faction_combo.get()
        for i, npc in enumerate(self.npcs):
            name = npc.get("name","?"); fid = npc.get("id","?"); faction = npc.get("faction","Neutral")
            show = True
            if q and q not in name.lower(): show = False
            if show and fac and fac != "(all)" and faction != fac: show = False
            if show:
                self.filtered_indices.append(i)
                self.listbox.insert("end", f"{fid}  {name}  [{faction}]")
        self.selected_index = None; self.form.set_object({})

    def on_select(self, *_):
        if not self.npcs: return
        sel = self.listbox.curselection()
        if not sel: return
        idx = self.filtered_indices[sel[0]]
        self.selected_index = idx
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
            ids = {n.get("id","") for idx, n in enumerate(self.npcs) if idx != self.selected_index}
            obj["id"] = ensure_npc_id(obj, ids)
            self.npcs[self.selected_index] = obj
        dataset.data = self.npcs
        save_json_file(dataset.path, dataset.root, dataset.data, dataset.list_key)
        messagebox.showinfo("Saved", f"Saved {dataset.file_name}")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RPGenesis Entity Editor")
        self.geometry("1160x760"); self.minsize(980, 640)

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.items_tab = ItemsTab(nb); self.npcs_tab = NPCsTab(nb)
        nb.add(self.items_tab, text="Items"); nb.add(self.npcs_tab, text="NPCs")

if __name__ == "__main__":
    App().mainloop()
