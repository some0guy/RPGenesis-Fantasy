import json, os, re, time

BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'npcs')
FILES = ['villains.json', 'citizens.json', 'allies.json']

REPLACEMENTS = [
    (re.compile(r"\bsilk slippers with tassels\b", re.I), "lace-up sandals with tassels"),
    (re.compile(r"\bsoft slippers\b", re.I), "soft-soled sandals"),
]

SENTENCE_REPLS = [
    (re.compile(r"\bHer slippers make no sound\b", re.I), "Her soft-soled sandals make no sound"),
    (re.compile(r"\bSoft slippers keep\b", re.I), "Soft-soled sandals keep"),
]

GENERIC = (re.compile(r"\bslippers\b", re.I), "sandals")


def fix_text(s: str) -> str:
    if not isinstance(s, str):
        return s
    out = s
    for rx, rep in REPLACEMENTS:
        out = rx.sub(rep, out)
    for rx, rep in SENTENCE_REPLS:
        out = rx.sub(rep, out)
    out = GENERIC[0].sub(GENERIC[1], out)
    return out


def main():
    changed = {}
    for fname in FILES:
        path = os.path.join(BASE, fname)
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            root = json.load(f)
        npcs = root.get('npcs') if isinstance(root, dict) else None
        if not isinstance(npcs, list):
            continue
        edits = 0
        for npc in npcs:
            if not isinstance(npc, dict):
                continue
            for key in ('clothing_short', 'clothing_long', 'notes', 'personality_long', 'personality_short'):
                val = npc.get(key)
                if isinstance(val, str) and re.search(r'slippers', val, re.I):
                    new_val = fix_text(val)
                    if new_val != val:
                        npc[key] = new_val
                        edits += 1
        if edits:
            ts = time.strftime('%Y%m%d_%H%M%S')
            with open(path + f'.{ts}.bak', 'w', encoding='utf-8') as b:
                json.dump(root, b, ensure_ascii=False, indent=2)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(root, f, ensure_ascii=False, indent=2)
            changed[path] = edits
    print(json.dumps({"changed": changed}, indent=2))


if __name__ == '__main__':
    main()

