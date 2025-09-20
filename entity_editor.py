#!/usr/bin/env python3
# entity_editor.py
# A lightweight Items/NPCs reader & creator for RPGenesis.
# - Shows items by file (weapons/armour/clothing/accessories/consumables if present)
# - Search + category filter
# - Edit fields via form or raw JSON
# - Create, duplicate, delete, save (with auto .bak backups)
# - NPC tab with similar flow (reads data/npcs.json if present; creates if missing)

import json, os, re, sys, time
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --------- Config ----------
BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
ITEMS_DIR  = os.path.join(BASE_DIR, "data", "items")
NPCS_DIR  = os.path.join(BASE_DIR, "data", "npcs")


RE_ID_ITEM = re.compile(r"^IT\d{8}$")
RE_ID_NPC  = re.compile(r"^(?:NP|NPC)\d{8}$")

# Default templates
DEFAULT_ITEM = {
    "id": "IT00000000",
    "name": "New Item",
    "category": "misc",
    "slot": "",
    "rarity": "common",
    "value": 0,
    "weight": 0,
    "description": "",
    "desc": "",
    "components": [],
    "bonus": {},
    "resist": {}
}
DEFAULT_NPC = {
    "id": "NP00000000",
    "name": "New NPC",
    "race": "",
    "sex": "",
    "type": "",
    "faction": "Neutral",
    "level": 1,
    "skin_tone": "",
    "skin_texture": "",
    "hair_colour": "",
    "hair_length": "",
    "hair_style": "",
    "eye_color": "",
    "height": "",
    "build": "",
    "curse": [],
    "clothing_alignment": [],
    "features": [],
    "appearance": {},
    "inventory": [],
    "clothing": [],
    "personality": [],
    "notes": ""
}

# --------- Helpers ----------
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
    return sorted(
        f for f in os.listdir(folder)
        if f.lower().endswith('.json')
    )

def load_dataset(
    path: str,
    preferred_keys: Sequence[str] = (),
    *,
    allow_first_list: bool = True,
    fallback_key: Optional[str] = None,
):
    if not os.path.exists(path):
        return None
    if os.path.getsize(path) == 0:
        if fallback_key:
            root = {fallback_key: []}
            return root, root[fallback_key], fallback_key
        empty: List[Any] = []
        return empty, empty, None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        messagebox.showerror('Invalid JSON', f"{os.path.basename(path)} could not be parsed: {exc}")
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
    if isinstance(root_obj, dict):
        if list_key:
            root_obj[list_key] = list_ref
        payload = root_obj
    else:
        payload = list_ref
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    backup_data = None
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as src:
                backup_data = src.read()
        except Exception:
            backup_data = None
    if backup_data:
        ts = time.strftime('%Y%m%d_%H%M%S')
        bak = path + f'.{ts}.bak'
        try:
            with open(bak, 'w', encoding='utf-8') as bf:
                bf.write(backup_data)
        except Exception:
            pass
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def ensure_item_id(item, existing_ids):
    _id = item.get('id','').strip()
    if RE_ID_ITEM.match(_id) and _id not in existing_ids:
        return _id
    base = 1
    if existing_ids:
        nums = []
        for s in existing_ids:
            m = re.match(r'IT(\d{8})', (s or ''))
            if m:
                nums.append(int(m.group(1)))
        base = (max(nums) + 1) if nums else 1
    return f'IT{base:08d}'

def ensure_npc_id(npc, existing_ids):
    _id = (npc.get('id','') or '').strip().upper()
    if RE_ID_NPC.match(_id) and _id not in existing_ids:
        return _id
    prefix = 'NP'
    nums = []
    for s in existing_ids:
        if not s:
            continue
        m = re.match(r'^(NP|NPC)(\d{8})$', s.strip().upper())
        if m:
            nums.append(int(m.group(2)))
            if m.group(1) == 'NPC':
                prefix = 'NPC'
    next_num = (max(nums) + 1) if nums else 1
    if RE_ID_NPC.match(_id):
        prefix = re.match(r'^(NP|NPC)', _id).group(1)
    return f'{prefix}{next_num:08d}'

def infer_category(item):
    for k in ('category','slot','type'):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return f'{k}:{v}'
    return 'uncategorized'

def get_all_categories(items):
    cats = set()
    for it in items:
        cats.add(infer_category(it))
    return ['(all)'] + sorted(cats)
# --------- Generic form builder ----------
class KeyValueForm(ttk.Frame):
    """Dynamic key-value editor with type inference, plus raw JSON toggle."""
    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self.current_obj = {}
        self.inputs = {}  # key -> (label, entry/widget)
        self.raw_mode = False

        # toolbar
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0,4))
        self.toggle_btn = ttk.Button(bar, text="Raw JSON", command=self.toggle_raw)
        self.toggle_btn.pack(side="right")

        # scrollable area
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0,0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        # raw text
        self.raw_text = tk.Text(self, height=24)
        self.raw_text.configure(font=("Courier", 10))

    def toggle_raw(self):
        self.raw_mode = not self.raw_mode
        if self.raw_mode:
            # Switch to raw
            for w in (self.canvas, self.scroll):
                w.pack_forget()
            self.raw_text.pack(fill="both", expand=True)
            self.raw_text.delete("1.0", "end")
            self.raw_text.insert("1.0", json.dumps(self.current_obj, ensure_ascii=False, indent=2))
            self.toggle_btn.config(text="Form View")
        else:
            # Switch to form, parse text
            try:
                obj = json.loads(self.raw_text.get("1.0","end"))
                self.set_object(obj)
            except Exception as e:
                messagebox.showerror("Invalid JSON", str(e))
                return
            self.raw_text.pack_forget()
            self.canvas.pack(side="left", fill="both", expand=True)
            self.scroll.pack(side="right", fill="y")
            self.toggle_btn.config(text="Raw JSON")

    def set_object(self, obj: dict):
        self.current_obj = dict(obj) if obj else {}
        # rebuild form
        for w in self.inner.winfo_children():
            w.destroy()
        self.inputs.clear()
        # Hard-prefer some keys at the top if present
        preferred = ["id","name","type","rarity","value","weight","description","slot","category"]
        keys = list(self.current_obj.keys())
        keys_sorted = preferred + [k for k in keys if k not in preferred]
        row = 0
        for k in keys_sorted:
            val = self.current_obj.get(k)
            ttk.Label(self.inner, text=k).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            if isinstance(val, (dict, list)):
                # show as JSON snippet with button to edit in raw
                text = tk.Text(self.inner, height=4, width=40)
                text.insert("1.0", json.dumps(val, ensure_ascii=False, indent=2))
                text.grid(row=row, column=1, sticky="we", padx=6, pady=4)
                self.inputs[k] = ("json", text)
            else:
                entry = ttk.Entry(self.inner)
                entry.insert(0, "" if val is None else str(val))
                entry.grid(row=row, column=1, sticky="we", padx=6, pady=4)
                self.inputs[k] = ("scalar", entry)
            row += 1

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
            if kind == "json":
                try:
                    out[k] = json.loads(widget.get("1.0","end"))
                except Exception as e:
                    messagebox.showerror("Invalid JSON in field '%s'"%k, str(e))
                    return None
            else:
                s = widget.get()
                # try cast numeric if looks like number
                if s.strip() == "":
                    out[k] = ""
                else:
                    if re.match(r"^-?\d+(\.\d+)?$", s.strip()):
                        out[k] = float(s) if "." in s else int(s)
                    else:
                        out[k] = s
        return out

# --------- Items Tab ----------
class ItemsTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.datasets = {}
        self.active_dataset: Optional[Dataset] = None
        self.active_file = None
        self.active_list = []
        self.filtered_indices = []
        self.selected_index = None

        left = ttk.Frame(self)
        right = ttk.Frame(self)
        left.pack(side='left', fill='y', padx=6, pady=6)
        right.pack(side='left', fill='both', expand=True, padx=6, pady=6)

        ttk.Label(left, text='Items File').pack(anchor='w')
        self.file_combo = ttk.Combobox(left, state='readonly', width=28)
        self.file_combo.pack(fill='x', pady=(0,6))
        self.file_combo.bind('<<ComboboxSelected>>', self.on_file_change)

        ttk.Label(left, text='Search').pack(anchor='w')
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(left, textvariable=self.search_var)
        search_entry.pack(fill='x', pady=(0,6))
        search_entry.bind('<KeyRelease>', lambda e: self.refresh_list())

        ttk.Label(left, text='Category').pack(anchor='w')
        self.cat_combo = ttk.Combobox(left, state='readonly')
        self.cat_combo.pack(fill='x', pady=(0,6))
        self.cat_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_list())

        self.listbox = tk.Listbox(left, height=24)
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.on_select)

        btns = ttk.Frame(left)
        btns.pack(fill='x', pady=6)
        ttk.Button(btns, text='New', command=self.on_new).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btns, text='Duplicate', command=self.on_dup).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btns, text='Delete', command=self.on_del).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btns, text='Save File', command=self.on_save).pack(side='left', expand=True, fill='x', padx=2)

        self.form = KeyValueForm(right)
        self.form.pack(fill='both', expand=True)

        self.load_datasets()

    def load_datasets(self):
        self.datasets.clear()
        if not os.path.isdir(ITEMS_DIR):
            messagebox.showwarning('Missing folder', f'Items directory not found: {ITEMS_DIR}')
            return
        files_found = []
        for fname in discover_json_files(ITEMS_DIR):
            path = os.path.join(ITEMS_DIR, fname)
            loaded = load_dataset(
                path,
                preferred_keys=('items', 'entries', 'records'),
                allow_first_list=True,
            )
            if not loaded:
                continue
            root, lst, list_key = loaded
            if not isinstance(lst, list):
                continue
            self.datasets[fname] = Dataset(fname, path, root, list_key, lst)
            files_found.append(fname)
        if not files_found:
            messagebox.showwarning('No item files', f'No item JSONs found under {ITEMS_DIR}.')
            self.file_combo.set('')
            self.cat_combo['values'] = []
            self.listbox.delete(0, 'end')
            self.form.set_object({})
            return
        self.file_combo['values'] = files_found
        self.file_combo.current(0)
        self.on_file_change()

    def on_file_change(self, *_):
        fname = self.file_combo.get()
        dataset = self.datasets.get(fname)
        if not dataset:
            self.active_dataset = None
            self.active_file = None
            self.active_list = []
            self.listbox.delete(0, 'end')
            self.form.set_object({})
            return
        self.active_dataset = dataset
        self.active_file = fname
        self.active_list = dataset.data
        cats = get_all_categories(self.active_list) if self.active_list else ['(all)']
        self.cat_combo['values'] = cats
        self.cat_combo.set('(all)')
        self.search_var.set('')
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0, 'end')
        self.filtered_indices = []
        if not self.active_list:
            self.form.set_object({})
            return
        q = self.search_var.get().lower().strip()
        cat = self.cat_combo.get()
        for i, it in enumerate(self.active_list):
            name = str(it.get('name', ''))
            show = True
            if q and q not in name.lower():
                show = False
            if show and cat and cat != '(all)':
                if infer_category(it) != cat:
                    show = False
            if show:
                self.filtered_indices.append(i)
                self.listbox.insert('end', f"{it.get('id','?')}  {name}")
        self.selected_index = None
        self.form.set_object({})

    def on_select(self, *_):
        if not self.active_list:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = self.filtered_indices[sel[0]]
        self.selected_index = idx
        self.form.set_object(self.active_list[idx])

    def on_new(self):
        if not self.active_dataset:
            return
        existing_ids = {it.get('id', '') for it in self.active_list}
        item = dict(DEFAULT_ITEM)
        item['id'] = ensure_item_id(item, existing_ids)
        self.active_list.append(item)
        self.refresh_list()
        self.listbox.select_set('end')
        self.on_select()

    def on_dup(self):
        if self.selected_index is None or not self.active_dataset:
            return
        src = dict(self.active_list[self.selected_index])
        existing_ids = {it.get('id', '') for it in self.active_list}
        src['id'] = ensure_item_id(src, existing_ids)
        self.active_list.append(src)
        self.refresh_list()
        self.listbox.select_set('end')
        self.on_select()

    def on_del(self):
        if self.selected_index is None or not self.active_dataset:
            return
        if not messagebox.askyesno('Delete item', 'Delete the selected item?'):
            return
        del self.active_list[self.selected_index]
        self.refresh_list()

    def on_save(self):
        dataset = self.active_dataset
        if not dataset:
            return
        if self.selected_index is not None and self.selected_index < len(self.active_list):
            obj = self.form.get_object()
            if obj is None:
                return
            ids = {it.get('id', '') for idx, it in enumerate(self.active_list) if idx != self.selected_index}
            obj['id'] = ensure_item_id(obj, ids)
            self.active_list[self.selected_index] = obj
        dataset.data = self.active_list
        save_json_file(dataset.path, dataset.root, dataset.data, dataset.list_key)
        messagebox.showinfo('Saved', f'Saved {dataset.file_name}')
# --------- NPCs Tab ----------
class NPCsTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.datasets = {}
        self.active_dataset: Optional[Dataset] = None
        self.active_file = None
        self.npcs = []
        self.filtered_indices = []
        self.selected_index = None

        left = ttk.Frame(self)
        left.pack(side='left', fill='y', padx=6, pady=6)
        right = ttk.Frame(self)
        right.pack(side='left', fill='both', expand=True, padx=6, pady=6)

        ttk.Label(left, text='NPC File').pack(anchor='w')
        self.file_combo = ttk.Combobox(left, state='readonly', width=28)
        self.file_combo.pack(fill='x', pady=(0,6))
        self.file_combo.bind('<<ComboboxSelected>>', self.on_file_change)

        ttk.Label(left, text='Search').pack(anchor='w')
        self.search_var = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search_var)
        ent.pack(fill='x', pady=(0,6))
        ent.bind('<KeyRelease>', lambda e: self.refresh_list())

        ttk.Label(left, text='Faction').pack(anchor='w')
        self.faction_combo = ttk.Combobox(left, state='readonly')
        self.faction_combo.pack(fill='x', pady=(0,6))
        self.faction_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_list())

        self.listbox = tk.Listbox(left, height=24)
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.on_select)

        btns = ttk.Frame(left)
        btns.pack(fill='x', pady=6)
        ttk.Button(btns, text='New', command=self.on_new).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btns, text='Duplicate', command=self.on_dup).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btns, text='Delete', command=self.on_del).pack(side='left', expand=True, fill='x', padx=2)
        ttk.Button(btns, text='Save File', command=self.on_save).pack(side='left', expand=True, fill='x', padx=2)

        self.form = KeyValueForm(right)
        self.form.pack(fill='both', expand=True)

        self.load_datasets()

    def load_datasets(self):
        self.datasets.clear()
        if not os.path.isdir(NPCS_DIR):
            messagebox.showwarning('Missing folder', f'NPC directory not found: {NPCS_DIR}')
            return
        files_found = []
        for fname in discover_json_files(NPCS_DIR):
            path = os.path.join(NPCS_DIR, fname)
            loaded = load_dataset(
                path,
                preferred_keys=('npcs',),
                allow_first_list=False,
                fallback_key='npcs',
            )
            if not loaded:
                continue
            root, lst, list_key = loaded
            if isinstance(root, dict) and list_key != 'npcs':
                continue
            if not isinstance(lst, list):
                continue
            self.datasets[fname] = Dataset(fname, path, root, list_key, lst)
            files_found.append(fname)
        if not files_found:
            messagebox.showwarning('No NPC files', f'No NPC JSONs found under {NPCS_DIR}.')
            self.file_combo.set('')
            self.faction_combo['values'] = []
            self.listbox.delete(0, 'end')
            self.form.set_object({})
            return
        self.file_combo['values'] = files_found
        self.file_combo.current(0)
        self.on_file_change()

    def on_file_change(self, *_):
        fname = self.file_combo.get()
        dataset = self.datasets.get(fname)
        if not dataset:
            self.active_dataset = None
            self.active_file = None
            self.npcs = []
            self.listbox.delete(0, 'end')
            self.form.set_object({})
            self.faction_combo['values'] = []
            return
        self.active_dataset = dataset
        self.active_file = fname
        self.npcs = dataset.data
        self.refresh_filters()
        self.refresh_list()

    def refresh_filters(self):
        factions = set()
        for n in self.npcs:
            faction = (n.get('faction', '') or 'Neutral').strip() or 'Neutral'
            factions.add(faction)
        values = ['(all)'] + sorted(factions)
        self.faction_combo['values'] = values
        self.faction_combo.set('(all)')

    def refresh_list(self):
        self.listbox.delete(0, 'end')
        self.filtered_indices.clear()
        if not self.npcs:
            self.form.set_object({})
            return
        q = self.search_var.get().lower().strip()
        fac = self.faction_combo.get()
        for i, npc in enumerate(self.npcs):
            name = npc.get('name', '?')
            fid = npc.get('id', '?')
            faction = npc.get('faction', 'Neutral')
            show = True
            if q and q not in name.lower():
                show = False
            if show and fac and fac != '(all)' and faction != fac:
                show = False
            if show:
                self.filtered_indices.append(i)
                self.listbox.insert('end', f"{fid}  {name}  [{faction}]")
        self.selected_index = None
        self.form.set_object({})

    def on_select(self, *_):
        if not self.npcs:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = self.filtered_indices[sel[0]]
        self.selected_index = idx
        self.form.set_object(self.npcs[idx])

    def on_new(self):
        if not self.active_dataset:
            return
        existing_ids = {n.get('id', '') for n in self.npcs}
        npc = dict(DEFAULT_NPC)
        npc['id'] = ensure_npc_id(npc, existing_ids)
        self.npcs.append(npc)
        self.refresh_filters()
        self.refresh_list()
        self.listbox.select_set('end')
        self.on_select()

    def on_dup(self):
        if self.selected_index is None or not self.active_dataset:
            return
        src = dict(self.npcs[self.selected_index])
        existing_ids = {n.get('id', '') for n in self.npcs}
        src['id'] = ensure_npc_id(src, existing_ids)
        self.npcs.append(src)
        self.refresh_list()
        self.listbox.select_set('end')
        self.on_select()

    def on_del(self):
        if self.selected_index is None or not self.active_dataset:
            return
        if not messagebox.askyesno('Delete NPC', 'Delete the selected NPC?'):
            return
        del self.npcs[self.selected_index]
        self.refresh_filters()
        self.refresh_list()

    def on_save(self):
        dataset = self.active_dataset
        if not dataset:
            return
        if self.selected_index is not None and self.selected_index < len(self.npcs):
            obj = self.form.get_object()
            if obj is None:
                return
            ids = {n.get('id', '') for idx, n in enumerate(self.npcs) if idx != self.selected_index}
            obj['id'] = ensure_npc_id(obj, ids)
            self.npcs[self.selected_index] = obj
        dataset.data = self.npcs
        save_json_file(dataset.path, dataset.root, dataset.data, dataset.list_key)
        messagebox.showinfo('Saved', f'Saved {dataset.file_name}')
# --------- App ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RPGenesis Entity Editor")
        self.geometry("1100x720")
        self.minsize(950, 600)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        self.items_tab = ItemsTab(nb)
        self.npcs_tab  = NPCsTab(nb)
        nb.add(self.items_tab, text="Items")
        nb.add(self.npcs_tab,  text="NPCs")

        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open items folder", command=self.open_items_folder)
        filemenu.add_command(label="Backup all items", command=self.backup_all_items)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        self.config(menu=menubar)

    def open_items_folder(self):
        if os.path.isdir(ITEMS_DIR):
            if sys.platform.startswith("win"):
                os.startfile(ITEMS_DIR)
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                os.system(f'"{opener}" "{ITEMS_DIR}"')
        else:
            messagebox.showwarning("Missing folder", f"Items directory not found: {ITEMS_DIR}")

    def backup_all_items(self):
        if not os.path.isdir(ITEMS_DIR):
            messagebox.showwarning("Missing folder", f"Items directory not found: {ITEMS_DIR}")
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        count = 0
        for fname in discover_json_files(ITEMS_DIR):
            path = os.path.join(ITEMS_DIR, fname)
            try:
                with open(path, "r", encoding="utf-8") as src:
                    data = src.read()
            except OSError:
                continue
            bak = path + f".{ts}.bak"
            try:
                with open(bak, "w", encoding="utf-8") as dest:
                    dest.write(data)
                count += 1
            except OSError:
                continue
        if count:
            messagebox.showinfo("Backups", f"Backed up {count} item files to .{ts}.bak")
        else:
            messagebox.showinfo("Backups", "No item JSONs were backed up.")

if __name__ == "__main__":
    App().mainloop()
