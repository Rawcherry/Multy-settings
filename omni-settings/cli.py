"""Command-line interface (no GTK needed) — handy for scripts, keybinds and testing.

  omni-settings --list [WORD]          list settings (id, current value, where it applies)
  omni-settings --get ID               print a value
  omni-settings --set ID VALUE         change a value on every desktop
  omni-settings --save-profile NAME    save all current values as a profile
  omni-settings --profile NAME         apply a saved profile (e.g. from a Hyprland keybind)
  omni-settings --desktops             what is installed / running
"""

from __future__ import annotations

import json
import sys

from .backends import APP_CONF, Engine, Setting
from .schema import all_settings


def parse_value(s: Setting, text: str) -> object:
    if s.kind == "bool":
        return text.strip().lower() in ("1", "true", "yes", "on")
    if s.kind == "int":
        return int(float(text))
    if s.kind == "float":
        return float(text)
    if s.kind == "enum":
        for v, label in s.options:
            if text in (str(v), label):
                return v
    return text


def main(argv: list[str]) -> int:
    eng = Engine()
    settings = all_settings()
    by_id = {s.id: s for s in settings}
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd == "--desktops":
        for k, d in eng.desktops.items():
            print(f"{k:<6} installed={d['installed']} running={d['running']}")
        return 0
    if cmd == "--list":
        word = argv[1].lower() if len(argv) > 1 else ""
        for s in settings:
            if not eng.maps_for(s) or (word and word not in f"{s.id} {s.title} {s.keywords}".lower()):
                continue
            print(f"{s.id:<20} {str(eng.read(s)):<28} {s.title}  [{', '.join(eng.applies_to(s))}]")
        return 0
    if cmd in ("--get", "--set"):
        if len(argv) < 2 or argv[1] not in by_id:
            print(f"unknown setting id — see: omni-settings --list", file=sys.stderr)
            return 2
        s = by_id[argv[1]]
        if cmd == "--get":
            print(eng.read(s))
            return 0
        if len(argv) < 3:
            print("usage: omni-settings --set ID VALUE", file=sys.stderr)
            return 2
        errs = eng.write(s, parse_value(s, " ".join(argv[2:])))
        for e in errs:
            print("error:", e, file=sys.stderr)
        if eng.backends["hypr"].notice:
            print("note:", eng.backends["hypr"].notice)
        return 1 if errs else 0
    if cmd == "--save-profile" and len(argv) > 1:
        print(eng.save_profile(" ".join(argv[1:]), settings))
        return 0
    if cmd == "--profile" and len(argv) > 1:
        name = " ".join(argv[1:])
        cands = [p for p in (APP_CONF / "profiles").glob("*.json")
                 if p.stem == name or json.loads(p.read_text()).get("name") == name]
        if not cands:
            print(f"no profile named {name!r}", file=sys.stderr)
            return 2
        errs = eng.apply_values(json.loads(cands[0].read_text()).get("values", {}), settings)
        for e in errs:
            print("error:", e, file=sys.stderr)
        return 1 if errs else 0
    print(__doc__.strip(), file=sys.stderr)
    return 2
