# RPGenesis Fantasy (Scaffold, Fixed Naming)

This is the **data-first scaffold** for your text-based fantasy RPG.
Now using consistent naming (`enchants_*`, `loot_tables.json`).

## Structure
- `assets/` — audio and images (bucketed by category)
- `data/` — JSON game data
  - `dialogues/` — per-NPC dialogue trees
  - `items/` — items split by type
  - `npcs/` — categorized NPCs
  - root-level JSON: `appearance.json`, `enchants_armour.json`, `enchants_accessories.json`, `enchants_weapons.json`, `encounters.json`, `loot_tables.json`, `magic.json`, `names.json`, `traits_*`
- `logs/` — log files
- `index.html` — checker (temporary, until Python version)
- `sw.js`

Each JSON file includes a `schema` and `version` to help with validation.


## ID format (10 characters)
- Items: `IT########`
- NPCs: `NP########`
- Enchants (weapons): `EW########`
- Enchants (armours): `EA########`
- Enchants (accessories): `EC########`
- Magic (spells): `MG########`
- Traits (accessories): `TC########`
- Traits (armours): `TA########`
- Traits (weapons): `TW########`
- Status effects: `ST########`

A validator is provided in `RPGenesis.py` and enforces these patterns.
