# RPGenesis Fantasy

This is the data-first scaffold for a text-based fantasy RPG.

## Structure
- `assets/` — audio and images (bucketed by category)
- `data/` — JSON game data
  - `dialogues/` — per-NPC dialogue trees
  - `items/` — items split by type
  - `npcs/` — categorized NPCs
  - root JSON: `appearance.json`, `enchants.json`, `traits.json`, `encounters.json`, `loot_tables.json`, `magic.json`, `names.json`, `status.json`, `world_map.json`
- `logs/` — log files
- `scripts/` — utilities for validation/migration
- `tools/` — local tools (untracked by git)

Each JSON may include a `schema` and `version` to help with validation.

## ID Format (10 chars)
- Items: `IT########`
- NPCs: `NP########`
- Enchants: `EN########`
- Traits: `TR########`
- Magic (spells): `MG########`
- Status effects: `ST########`

Validate with: `python scripts/validate_json.py`

## World Map
- File: `data/world_map.json`
- Edited/viewed in the map editor (Start → World View).
- Stores a simple grid layout: `{ layout: { "Map Name": { x, y } }, start: { map, entry, pos } }`.
- Controls: `S` to save, `Tab` to cycle, arrow keys to move, `Esc` back.

