#!/usr/bin/env python3
"""
RPGenesis – bulk conflict marker cleaner (safe)
- Makes <file>.bak backups
- Resolves <<<<<<< / ======= / >>>>>>> markers
- Policy: keep TOP or keep BOTTOM (config flag)
- Normalizes UTF-8 and ensures trailing newline
"""

from __future__ import annotations
import sys, re
from pathlib import Path

# --- CONFIG: choose which side to keep on conflicts
KEEP = "TOP"   # "TOP"  -> keep version between <<<<<<< and =======
               # "BOT"  -> keep version between ======= and >>>>>>>
# File extensions to scan
EXTS = {".py", ".json", ".txt", ".md"}

MARK_START = re.compile(r"^<{7}")   # <<<<<<<
MARK_SEP   = re.compile(r"^={7}$")  # =======
MARK_END   = re.compile(r"^>{7}")   # >>>>>>>

def clean_file(path: Path) -> bool:
    """
    Returns True if file was changed.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # fallback: try raw read, then decode replacing errors
        text = path.read_bytes().decode("utf-8", errors="replace")

    lines = text.splitlines()
    out: list[str] = []
    i = 0
    changed = False

    while i < len(lines):
        line = lines[i]
        if MARK_START.match(line):
            # inside conflict
            i += 1
            top: list[str] = []
            bot: list[str] = []

            # collect top until =======
            while i < len(lines) and not MARK_SEP.match(lines[i]):
                top.append(lines[i])
                i += 1
            if i >= len(lines) or not MARK_SEP.match(lines[i]):
                # malformed conflict; give up and copy raw
                out.append(line)
                continue
            i += 1  # skip =======

            # collect bottom until >>>>>>>
            while i < len(lines) and not MARK_END.match(lines[i]):
                bot.append(lines[i])
                i += 1
            if i < len(lines) and MARK_END.match(lines[i]):
                i += 1  # skip >>>>>>>
            # apply policy
            out.extend(top if KEEP == "TOP" else bot)
            changed = True
        else:
            out.append(line)
            i += 1

    if changed:
        bak = path.with_suffix(path.suffix + ".bak")
        bak.write_text(text, encoding="utf-8")
        new = "\n".join(out) + "\n"
        path.write_text(new, encoding="utf-8")
        print(f"[FIX] {path}")
    return changed

def main():
    root = Path(".").resolve()
    total = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in EXTS:
            # quick detect to skip reading every file
            try:
                s = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "<<<<<<<" in s and ">>>>>>>" in s:
                if clean_file(p):
                    total += 1
    if total == 0:
        print("[OK] No conflict markers found.")
    else:
        print(f"[OK] Cleaned {total} file(s). Backups saved as *.bak")

if __name__ == "__main__":
    sys.exit(main())
