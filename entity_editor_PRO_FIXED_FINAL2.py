
import os, json, re, tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# --------- Constants ---------
RARITY_OPTIONS = ["common","uncommon","rare","epic","legendary","relic"]
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
BONUS_KEYS  = ["HP","PHY","MAG","VIT","TEC","AGI","LUK"]
RESIST_KEYS = ["fire","frost","shock","poison","holy","shadow","arcane","bleed"]
TRAIT_OPTIONS = ["thorns","lifesteal","mana_regen","swift","sturdy","berserker","siphon","warded"]

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
ITEMS_DIR = DATA_DIR  # assumes jsons live in ./data/

# Helpers for item-slot derivation
def derive_slot(obj: dict) -> str:
    cat = (obj.get("category","") or "").lower()
    typ = (obj.get("type","") or "").lower()
    if cat == "armour":
        mapping = {
            "head":"head","helm":"head","hood":"head",
            "chest":"chest","cuirass":"chest","breast":"chest",
            "legs":"legs","greaves":"legs","legging":"legs",
            "feet":"feet","boots":"feet",
            "hands":"hands","gloves":"hands","gauntlets":"hands",
            "cloak":"cloak","belt":"belt","shield":"offhand"
        }
        for k,v in mapping.items():
            if k in typ: return v
        return typ or ""
    if cat == "weapons":
        if "shield" in typ: return "offhand"
        return "mainhand"
    if cat == "clothing":
        return "body"
    if cat == "accessories":
        if "ring" in typ: return "ring"
        if "amulet" in typ or "necklace" in typ: return "neck"
        return "accessory"
    return obj.get("slot","") or ""

# Global cache of all items by id->label and label->id for Components picker
ALL_ITEMS = {}
ALL_ITEMS_LABEL_TO_ID = {}

def _normalize_items_container(data):
    """Accept list, single dict, or dict with 'items'; return a list of dicts."""
    if isinstance(data, dict):
        if "items" in data:
            data = data["items"]
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]

def load_all_item_labels(base_dir: str):
    global ALL_ITEMS, ALL_ITEMS_LABEL_TO_ID
    ALL_ITEMS, ALL_ITEMS_LABEL_TO_ID = {}, {}
    if not os.path.isdir(base_dir):
        return
    for name in os.listdir(base_dir):
        if not name.endswith(".json"): 
            continue
        path = os.path.join(base_dir, name)
        try:
            raw = json.load(open(path, "r", encoding="utf-8"))
            data = _normalize_items_container(raw)
            for it in data:
                label = f"{it.get('name','(no name)')} [{it.get('id','??')}]"
                iid = it.get("id","")
                ALL_ITEMS[iid] = label
                ALL_ITEMS_LABEL_TO_ID[label] = iid
        except Exception:
            continue

# --------- Widgets ---------
class ComboField(ttk.Frame):
    def __init__(self, master, values, initial=""):
        super().__init__(master)
        self.var = tk.StringVar(value=str(initial or ""))
        self.combo = ttk.Combobox(self, values=list(values), textvariable=self.var, state="readonly")
        self.combo.pack(fill="x", expand=True)
    def get(self):
        return self.var.get()
    def set(self, v):
        self.var.set(v)

class ComponentsField(ttk.Frame):
    """
    Components/materials picker with:
    - Single-select available and selected lists
    - Add ▶ / ◀ Remove, Move Up/Down, Clear
    - Text filter
    - Click-outside deselect that doesn't conflict with buttons
    """
    def __init__(self, master, labels):
        super().__init__(master)
        self.all_labels = sorted(set(labels))
        self.selected = []

        self.columnconfigure(0, weight=1); self.columnconfigure(1, weight=1)

        left = ttk.Frame(self); left.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        top = ttk.Frame(left); top.pack(fill="x", pady=(0,6))
        ttk.Label(top, text="Filter").pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.filter_var, width=24).pack(side="left", padx=(6,0))

        self.lb = tk.Listbox(left, selectmode="browse", height=12, exportselection=False)
        self.lb.pack(fill="both", expand=True)
        btns = ttk.Frame(left); btns.pack(fill="x", pady=(6,0))
        ttk.Button(btns, text="Add ▶", command=self._add).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(btns, text="◀ Remove", command=self._remove).pack(side="left", expand=True, fill="x", padx=3)

        right = ttk.Frame(self); right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Currently Selected").pack(anchor="w")
        self.sel = tk.Listbox(right, selectmode="browse", height=14, exportselection=False)
        self.sel.pack(fill="both", expand=True, pady=(4,0))
        rbtns = ttk.Frame(right); rbtns.pack(fill="x", pady=(6,0))
        ttk.Button(rbtns, text="Move Up", command=self._up).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(rbtns, text="Move Down", command=self._down).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(rbtns, text="Clear", command=self._clear).pack(side="left", expand=True, fill="x", padx=3)

        self.filter_var.trace_add("write", lambda *_: self._refill())

        def _is_desc(widget, container):
            try:
                w = widget
                while w is not None:
                    if w == container: return True
                    w = getattr(w, "master", None)
            except Exception:
                pass
            return False
        def _global_click_clear(event, self=self):
            try:
                if not _is_desc(event.widget, self):
                    self.lb.selection_clear(0, "end")
                    self.sel.selection_clear(0, "end")
            except Exception:
                pass
        self.winfo_toplevel().bind("<Button-1>", _global_click_clear, add="+")

        self._refill()

    def _refill(self):
        flt = (self.filter_var.get() or "").strip().lower()
        self.lb.delete(0,"end")
        for lab in self.all_labels:
            if flt in lab.lower():
                self.lb.insert("end", lab)

    def _sync_sel(self):
        self.sel.delete(0,"end")
        for lab in self.selected:
            self.sel.insert("end", lab)

    def _add(self):
        if self.lb.curselection():
            lab = self.lb.get(self.lb.curselection()[0])
            if lab not in self.selected:
                self.selected.append(lab)
                self._sync_sel()
        self.lb.selection_clear(0,"end"); self.sel.selection_clear(0,"end")

    def _remove(self):
        pick = None
        if self.sel.curselection():
            pick = self.sel.get(self.sel.curselection()[0])
        elif self.lb.curselection():
            pick = self.lb.get(self.lb.curselection()[0])
        if pick is not None:
            self.selected = [s for s in self.selected if s != pick]
            self._sync_sel()
        self.lb.selection_clear(0,"end"); self.sel.selection_clear(0,"end")

    def _up(self):
        if not self.sel.curselection(): return
        i = self.sel.curselection()[0]
        if i>0:
            self.selected[i-1], self.selected[i] = self.selected[i], self.selected[i-1]
            self._sync_sel(); self.sel.selection_set(i-1)

    def _down(self):
        if not self.sel.curselection(): return
        i = self.sel.curselection()[0]
        if i < len(self.selected)-1:
            self.selected[i+1], self.selected[i] = self.selected[i], self.selected[i+1]
            self._sync_sel(); self.sel.selection_set(i+1)

    def _clear(self):
        self.selected = []; self._sync_sel()

    def set(self, labels):
        self.selected = list(labels or []); self._sync_sel()

    def get(self):
        return list(self.selected)

class KeyPickerField(ttk.Frame):
    """Generic single-select picker for bonus/resist/trait keys."""
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

        self._refill_available(); self._sync_selected()

        def _is_desc(widget, container):
            try:
                w = widget
                while w is not None:
                    if w == container: return True
                    w = getattr(w, "master", None)
            except Exception:
                pass
            return False
        def _global_click_clear(event, self=self):
            try:
                if not _is_desc(event.widget, self):
                    self.lb.selection_clear(0,"end"); self.sel.selection_clear(0,"end")
            except Exception:
                pass
        self.winfo_toplevel().bind("<Button-1>", _global_click_clear, add="+")

    def _refill_available(self):
        self.lb.delete(0,"end")
        for k in self.all_keys:
            if k not in self.selected:
                self.lb.insert("end", k)

    def _sync_selected(self):
        self.sel.delete(0,"end")
        for k in self.selected:
            self.sel.insert("end", k)

    def _add(self):
        if self.lb.curselection():
            k = self.lb.get(self.lb.curselection()[0])
            if k not in self.selected:
                self.selected.append(k)
                self._refill_available(); self._sync_selected()
        self.lb.selection_clear(0,"end"); self.sel.selection_clear(0,"end")

    def _remove(self):
        pick = None
        if self.sel.curselection():
            pick = self.sel.get(self.sel.curselection()[0])
        elif self.lb.curselection():
            pick = self.lb.get(self.lb.curselection()[0])
        if pick is not None and pick in self.selected:
            self.selected = [x for x in self.selected if x != pick]
            self._refill_available(); self._sync_selected()
        self.lb.selection_clear(0,"end"); self.sel.selection_clear(0,"end")

    def set(self, keys):
        self.selected = []
        for k in keys or []:
            if isinstance(k, str) and k not in self.selected:
                self.selected.append(k)
        self._refill_available(); self._sync_selected()

    def get(self):
        return list(self.selected)

# --------- Form ---------
class KeyValueForm(ttk.Frame):
    def __init__(self, master, mode='item'):
        super().__init__(master)
        self.mode = mode
        self.context_category = None
        self.inputs = {}
        # Scrollable canvas
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def set_category_context(self, cat: str):
        self.context_category = (cat or '').lower()

    def toggle_raw(self, state: bool):
        self.raw_mode = bool(state)

    def _make_widget_for(self, key: str, val):
        # Hide category; it's inferred from Items File
        if key == "category":
            return ("hidden", None)

        # Rarity dropdown
        if key == "rarity":
            w = ComboField(self.inner, RARITY_OPTIONS, str(val or ""))
            return ("rarity_combo", w)

        # Type dropdown scoped by file category
        if key == "type":
            cat = (self.context_category or "").lower()
            options = TYPE_OPTIONS.get(cat, sorted({t for arr in TYPE_OPTIONS.values() for t in arr}))
            w = ComboField(self.inner, options, str(val or ""))
            return ("type_combo", w)

        # Modern pickers
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

        # Legacy views (read-only pretty JSON for old fields)
        if key in ("bonus","resist","trait"):
            text = tk.Text(self.inner, height=3, width=40)
            try: text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
            except Exception: text.insert("1.0", str(val))
            text.configure(state="disabled")
            return ("legacy_json", text)

        if isinstance(val, (dict, list)):
            text = tk.Text(self.inner, height=4, width=40)
            text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
            return ("json", text)

        entry = ttk.Entry(self.inner); entry.insert(0, "" if val is None else str(val))
        return ("scalar", entry)

    def set_object(self, obj: dict):
        """Build the form for the given object dict."""
        self.current_obj = dict(obj) if obj else {}

        # Hide deprecated key entirely
        if 'scale_with_level' in self.current_obj:
            self.current_obj.pop('scale_with_level', None)

        def keys_from_legacy(v):
            if isinstance(v, list): return [x for x in v if isinstance(x, str)]
            if isinstance(v, dict): return [k for k,vv in v.items() if vv]
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
                     "slot","components","fixed_bonus","possible_bonus","fixed_resist","possible_resist","fixed_trait","possible_trait"]
        keys = list(self.current_obj.keys())
        keys_sorted = preferred + [k for k in keys if k not in preferred]

        self.inner.columnconfigure(1, weight=1); self.inner.columnconfigure(3, weight=1)
        WIDE_KEYS = {"description","components","fixed_bonus","possible_bonus","fixed_resist","possible_resist","fixed_trait","possible_trait"}
        row, col_slot = 0, 0

        for k in keys_sorted:
            if k == 'category':  # hidden; inferred from file
                continue
            val = self.current_obj.get(k)
            is_wide = k in WIDE_KEYS
            label_col = 0 if col_slot == 0 else 2
            ttk.Label(self.inner, text=k).grid(row=row, column=(0 if is_wide else label_col), sticky="w", padx=6, pady=4)
            if k == "components":
                labels = [ALL_ITEMS.get(cid, f"(missing) [{cid}]") for cid in (val or [])]
                w = ComponentsField(self.inner, list(ALL_ITEMS_LABEL_TO_ID.keys()))
                w.set(labels)
                kind, widget = ("components_labels", w)
            else:
                kind, widget = self._make_widget_for(k, val)

            if kind == 'hidden':
                continue
            self.inputs[k] = (kind, widget)
            target_col = 1 if col_slot == 0 else 3
            if is_wide:
                target_col = 1
            if kind == "slot_readonly":
                widget[0].grid(row=row, column=target_col, sticky="we", padx=6, pady=4)
            else:
                try:
                    widget.grid(row=row, column=target_col, sticky="we", padx=6, pady=4)
                except Exception:
                    pass
            if is_wide:
                try:
                    (widget if hasattr(widget,'grid_configure') else widget[0]).grid_configure(columnspan=3)
                except Exception:
                    pass
                row += 1; col_slot = 0
            else:
                if col_slot == 0: col_slot = 1
                else: col_slot = 0; row += 1

        # Derive slot from type/category context
        try:
            snap = {}
            t = self.inputs.get("type")
            if t and (t[0] in ("scalar","type_combo")):
                snap["type"] = t[1].get()
            if getattr(self, 'context_category', None):
                snap["category"] = self.context_category
            inferred = derive_slot(snap)
            sl = self.inputs.get("slot")
            if sl and sl[0] == "slot_readonly":
                sl[1][1].set(inferred)
        except Exception:
            pass

    def get_object(self):
        out = {}
        for k, (kind, widget) in self.inputs.items():
            if kind in ("json","legacy_json","hidden"):
                continue
            elif kind in ("rarity_combo","type_combo"):
                out[k] = widget.get()
            elif kind == "slot_readonly":
                pass
            elif kind == "components_labels":
                labels = widget.get()
                ids = []
                for lab in labels:
                    iid = ALL_ITEMS_LABEL_TO_ID.get(lab)
                    if iid: ids.append(iid)
                out["components"] = ids
            elif kind.endswith("_keys"):
                out[k] = widget.get()
            elif kind == "bool_toggle":
                try:
                    out[k] = bool(widget.var.get())
                except Exception:
                    out[k] = bool(getattr(widget, 'get', lambda: False)())
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
        if getattr(self, 'context_category', None):
            out["category"] = self.context_category
        if 'scale_with_level' in out:
            out.pop('scale_with_level', None)
        return out

# --------- Tabs ---------
class ItemsTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.active_file = ""
        self.active_list = []

        self.columnconfigure(0, weight=0); self.columnconfigure(1, weight=1)

        # Left panel: file picker + search + list
        left = ttk.Frame(self); left.grid(row=0, column=0, sticky="nsw", padx=8, pady=8)
        ttk.Label(left, text="Items File").pack(anchor="w")
        self.file_combo = ttk.Combobox(left, state="readonly")
        self.file_combo.pack(fill="x")
        self.file_combo.bind("<<ComboboxSelected>>", lambda e: self.on_file_change())

        ttk.Label(left, text="Search").pack(anchor="w", pady=(8,0))
        self.search_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.search_var).pack(fill="x")
        self.search_var.trace_add("write", lambda *_: self.refresh_list())

        self.listbox = tk.Listbox(left, height=30, exportselection=False)
        self.listbox.pack(fill="both", expand=True, pady=(8,0))
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_select())

        # Right panel: form + buttons
        right = ttk.Frame(self); right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        right.columnconfigure(0, weight=1)
        self.form = KeyValueForm(right); self.form.pack(fill="both", expand=True)

        btns = ttk.Frame(right); btns.pack(fill="x", pady=(8,0))
        ttk.Button(btns, text="New", command=self.on_new).pack(side="left", padx=3)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="left", padx=3)
        ttk.Button(btns, text="Delete", command=self.on_delete).pack(side="left", padx=3)

        self.load_datasets()

    def load_datasets(self):
        # Populate file dropdown from JSONs
        files = []
        if os.path.isdir(ITEMS_DIR):
            for name in os.listdir(ITEMS_DIR):
                if name.endswith(".json"):
                    files.append(name)
        files.sort()
        self.file_combo["values"] = files
        if files:
            self.file_combo.set(files[0])
            self.on_file_change()

    def on_file_change(self):
        name = self.file_combo.get()
        path = os.path.join(ITEMS_DIR, name) if name else ""
        self.active_file = path
        try:
            raw = json.load(open(path, "r", encoding="utf-8"))
            self.active_list = _normalize_items_container(raw)
        except Exception:
            self.active_list = []
        # Load global labels for Components picker across ALL jsons
        load_all_item_labels(ITEMS_DIR)

        # Set form category context from file name
        try:
            cat = os.path.splitext(os.path.basename(self.active_file or ""))[0].lower()
            if cat == "armors": cat = "armour"
            self.form.set_category_context(cat)
        except Exception:
            pass

        self.refresh_list()

    def refresh_list(self):
        q = (self.search_var.get() or "").strip().lower()
        self.listbox.delete(0,"end")
        for i, it in enumerate(self.active_list):
            if not isinstance(it, dict):
                continue
            name = it.get("name","(no name)"); iid = it.get("id","")
            label = f"{name} [{iid}]"
            if q and q not in name.lower() and q not in (iid or "").lower():
                continue
            self.listbox.insert("end", label)
        # Clear form when changing files or when nothing selected
        self.form.set_object({})

    def on_select(self):
        idxs = self.listbox.curselection()
        if not idxs: return
        idx = idxs[0]
        try:
            obj = self.active_list[idx]
        except Exception:
            obj = {}
        self.form.set_object(obj)

    def on_new(self):
        # Create skeleton item; id auto next number (ignore 0s like IT00000000)
        prefix = "IT"
        next_num = 1
        ids = [x.get("id","") for x in self.active_list if isinstance(x, dict)]
        nums = []
        for s in ids:
            if isinstance(s, str) and len(s) >= 10 and s[:2].isalpha() and s[2:].isdigit():
                n = int(s[2:])
                if n > 0: nums.append(n)
        if nums:
            next_num = max(nums) + 1
        new_id = f"{prefix}{next_num:08d}"
        obj = {"id": new_id, "name": "", "type": "", "rarity":"common", "value":0, "weight":0.0, "description":"", "slot":"", "components":[]}
        self.form.set_object(obj)

    def on_save(self):
        obj = self.form.get_object()
        # Inject category from context if missing
        if "category" not in obj:
            try:
                cat = os.path.splitext(os.path.basename(self.active_file or ""))[0].lower()
                if cat == "armors": cat = "armour"
                obj["category"] = cat
            except Exception:
                pass

        # Update list: replace by id or append
        idxs = self.listbox.curselection()
        if idxs:
            idx = idxs[0]
            old_id = self.active_list[idx].get("id","") if isinstance(self.active_list[idx], dict) else ""
            if not obj.get("id"): obj["id"] = old_id
            if isinstance(self.active_list[idx], dict):
                self.active_list[idx] = obj
            else:
                self.active_list.append(obj)
        else:
            self.active_list.append(obj)

        # Write to file (dict list only)
        try:
            json.dump([x for x in self.active_list if isinstance(x, dict)],
                      open(self.active_file, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            self.refresh_list()
            messagebox.showinfo("Saved", "Item saved.")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def on_delete(self):
        idxs = self.listbox.curselection()
        if not idxs: return
        idx = idxs[0]
        if messagebox.askyesno("Delete", "Delete selected item?"):
            try:
                if 0 <= idx < len(self.active_list):
                    self.active_list.pop(idx)
                json.dump([x for x in self.active_list if isinstance(x, dict)],
                          open(self.active_file, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                self.refresh_list()
                self.form.set_object({})
            except Exception as e:
                messagebox.showerror("Delete Error", str(e))

class NPCsTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        ttk.Label(self, text="NPC Editor (minimal placeholder)").pack(pady=40)

# --------- App ---------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RPGenesis Entity Editor — FIXED FINAL2")
        self.state("zoomed")
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.items_tab = ItemsTab(nb); nb.add(self.items_tab, text="Items")
        self.npcs_tab = NPCsTab(nb); nb.add(self.npcs_tab, text="NPCs")

if __name__ == "__main__":
    App().mainloop()
