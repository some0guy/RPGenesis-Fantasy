import json, os, sys

paths = [
    os.path.join('data','npcs','villains.json'),
    os.path.join('data','npcs','citizens.json'),
    os.path.join('data','npcs','allies.json'),
]

ok = True
for p in paths:
    try:
        with open(p,'r',encoding='utf-8') as f:
            json.load(f)
        print(p, 'OK')
    except Exception as e:
        ok = False
        print(p, 'ERR', e)

sys.exit(0 if ok else 1)

