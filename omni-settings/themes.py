"""Lists of installed themes etc. for the drop-downs (no GTK imports)."""

from __future__ import annotations

from pathlib import Path

HOME = Path.home()
THEME_DIRS = [HOME / ".themes", HOME / ".local/share/themes", Path("/usr/share/themes")]
ICON_DIRS = [HOME / ".icons", HOME / ".local/share/icons", Path("/usr/share/icons")]


def _dirs(bases: list[Path]) -> list[Path]:
    out: dict[str, Path] = {}
    for b in bases:
        if b.is_dir():
            for d in sorted(b.iterdir()):
                if d.is_dir() and d.name not in out:
                    out[d.name] = d
    return list(out.values())


def gtk_themes() -> list[str]:
    names = {d.name for d in _dirs(THEME_DIRS) if (d / "gtk-3.0").is_dir() or (d / "gtk-4.0").is_dir()}
    return sorted(names | {"Adwaita", "Adwaita-dark", "HighContrast"}, key=str.lower)


def icon_themes() -> list[str]:
    out = []
    for d in _dirs(ICON_DIRS):
        if d.name in ("default", "hicolor", "locolor") or not (d / "index.theme").is_file():
            continue
        subdirs = [s.name for s in d.iterdir() if s.is_dir()]
        if subdirs and subdirs != ["cursors"]:
            out.append(d.name)
    return sorted(out, key=str.lower)


def cursor_themes() -> list[str]:
    return sorted({d.name for d in _dirs(ICON_DIRS) if (d / "cursors").is_dir() and d.name != "default"},
                  key=str.lower)


def xfwm_themes() -> list[str]:
    return sorted({d.name for d in _dirs(THEME_DIRS) if (d / "xfwm4").is_dir()}, key=str.lower)


def kde_color_schemes() -> list[str]:
    out = set()
    for b in (HOME / ".local/share/color-schemes", Path("/usr/share/color-schemes")):
        if b.is_dir():
            out |= {f.stem for f in b.glob("*.colors")}
    return sorted(out, key=str.lower)


def kde_lnf() -> list[str]:
    out = set()
    for b in (HOME / ".local/share/plasma/look-and-feel", Path("/usr/share/plasma/look-and-feel")):
        if b.is_dir():
            out |= {d.name for d in b.iterdir() if d.is_dir()}
    return sorted(out, key=str.lower)


PROVIDERS = {
    "gtk-themes": gtk_themes,
    "icon-themes": icon_themes,
    "cursor-themes": cursor_themes,
    "xfwm-themes": xfwm_themes,
    "kde-color-schemes": kde_color_schemes,
    "kde-lnf": kde_lnf,
}


def choices(source: str) -> list[str]:
    fn = PROVIDERS.get(source)
    try:
        return fn() if fn else []
    except OSError:
        return []


# ---- font name conversions ----------------------------------------------------
# GNOME / XFCE / GTK use Pango strings: "Noto Sans Bold 11"
# KDE uses Qt strings:                   "Noto Sans,11,-1,5,700,0,0,0,0,0,0,0,0,0,0,1"
STYLE_WORDS = {"bold", "italic", "oblique", "light", "medium", "semibold", "regular", "book", "thin", "black",
               "heavy", "condensed", "ultra-light", "extra-light", "demi-bold", "extra-bold"}


def pango_to_qt(p: str) -> str:
    parts = p.split()
    size = 10.0
    if parts and parts[-1].replace(".", "", 1).isdigit():
        size = float(parts.pop())
    weight = 700 if any(w.lower() == "bold" for w in parts) else 400
    italic = 1 if any(w.lower() in ("italic", "oblique") for w in parts) else 0
    family = " ".join(w for w in parts if w.lower() not in STYLE_WORDS) or "Noto Sans"
    sz = f"{size:g}"
    return f"{family},{sz},-1,5,{weight},{italic},0,0,0,0,0,0,0,0,0,1"


def qt_to_pango(q: str) -> str:
    f = q.split(",")
    if len(f) < 2:
        return q
    out = f[0]
    if len(f) > 4 and f[4].isdigit() and int(f[4]) >= 600:
        out += " Bold"
    if len(f) > 5 and f[5] == "1":
        out += " Italic"
    try:
        out += f" {float(f[1]):g}"
    except ValueError:
        pass
    return out
