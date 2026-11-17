"""How each desktop stores its settings, plus the Engine that applies one setting everywhere.

No GTK imports in this module, so it can be tested on its own (see tests/).
Backends:
  gnome    gsettings (dconf) — also read by GTK4/libadwaita apps under Hyprland
  kde      kreadconfig6 / kwriteconfig6 (+ KWin reconfigure, KGlobalSettings notify)
  xfce     xfconf-query
  hypr     live: hyprctl keyword / hyprctl eval (Lua config); saved: ~/.config/hypr/omni-settings.conf|.lua
  gtk      ~/.config/gtk-3.0/settings.ini and gtk-4.0/settings.ini
  special  things that need a program call (colour schemes, cursors, wallpaper, night light)
"""

from __future__ import annotations

import ast
import configparser
import fnmatch
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HOME = Path.home()
CONF_HOME = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
APP_CONF = CONF_HOME / "omni-settings"
APP_CONF.mkdir(parents=True, exist_ok=True)


class BackendError(Exception):
    pass


def run(args: list[str], timeout: float = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip()


def which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def spawn(args: list[str]) -> None:
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ============================================================================ GNOME / gsettings

def parse_gvariant(text: str) -> Any:
    t = text.strip()
    if t in ("true", "false"):
        return t == "true"
    t = re.sub(r"^(u?int(16|32|64)|byte|double|@\w+(\(\w+\))?)\s+", "", t)
    if t.startswith("@") and t.endswith("[]"):
        return []
    try:
        return ast.literal_eval(t)
    except (ValueError, SyntaxError):
        return t


def to_gvariant(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, tuple):
        return "(" + ", ".join(to_gvariant(x) for x in v) + ")"
    if isinstance(v, list):
        if not v:
            return "@as []"
        return "[" + ", ".join(to_gvariant(x) for x in v) + "]"
    raise BackendError(f"cannot convert {v!r} to GVariant")


class Gnome:
    name, label = "gnome", "GNOME"

    def __init__(self) -> None:
        self._schemas: set[str] | None = None
        self._keys: dict[str, set[str]] = {}

    def available(self) -> bool:
        return bool(which("gsettings"))

    def target_ok(self, t: tuple[str, str]) -> bool:
        schema, key = t
        if self._schemas is None:
            rc, out = run(["gsettings", "list-schemas"])
            self._schemas = set(out.split()) if rc == 0 else set()
        if schema not in self._schemas:
            return False
        if schema not in self._keys:
            rc, out = run(["gsettings", "list-keys", schema])
            self._keys[schema] = set(out.split()) if rc == 0 else set()
        return key in self._keys[schema]

    def read(self, t: tuple[str, str]) -> Any:
        rc, out = run(["gsettings", "get", *t])
        if rc:
            raise BackendError(out)
        return parse_gvariant(out)

    def write(self, t: tuple[str, str], v: Any) -> None:
        rc, out = run(["gsettings", "set", *t, to_gvariant(v)])
        if rc:
            raise BackendError(out)


# ============================================================================ KDE / kconfig

@dataclass
class KTarget:
    file: str
    group: str | list[str]
    key: str
    type: str = "str"           # str | bool | int | float
    hook: str = ""              # "" | "kwin" | "kglobal:<n>"  (n: 0 palette, 1 font, 3 settings, 4 icons, 5 cursor)


class Kde:
    name, label = "kde", "KDE Plasma"

    def _bin(self, kind: str) -> str | None:
        return which(f"k{kind}config6", f"k{kind}config5")

    def available(self) -> bool:
        return bool(self._bin("read") and self._bin("write"))

    def target_ok(self, t: KTarget) -> bool:
        return True

    def _groups(self, t: KTarget) -> list[str]:
        out: list[str] = []
        for g in [t.group] if isinstance(t.group, str) else t.group:
            out += ["--group", g]
        return out

    def read(self, t: KTarget) -> Any:
        rc, out = run([self._bin("read") or "kreadconfig6", "--file", t.file, *self._groups(t), "--key", t.key])
        if rc:
            raise BackendError(out)
        return out if out != "" else None

    def write(self, t: KTarget, v: Any) -> None:
        val = ("true" if v else "false") if t.type == "bool" else str(v)
        args = [self._bin("write") or "kwriteconfig6", "--file", t.file, *self._groups(t), "--key", t.key]
        if t.type == "bool":
            args += ["--type", "bool"]
        rc, out = run(args + [val])
        if rc:
            raise BackendError(out)
        self.hook(t.hook)

    @staticmethod
    def hook(h: str) -> None:
        if not h:
            return
        if h == "kwin":
            q = which("qdbus6", "qdbus")
            if q:
                run([q, "org.kde.KWin", "/KWin", "reconfigure"], timeout=5)
            else:
                run(["dbus-send", "--session", "--type=method_call", "--dest=org.kde.KWin", "/KWin",
                     "org.kde.KWin.reconfigure"], timeout=5)
        elif h.startswith("kglobal:"):
            run(["dbus-send", "--session", "--type=signal", "/KGlobalSettings",
                 "org.kde.KGlobalSettings.notifyChange", f"int32:{h.split(':')[1]}", "int32:0"], timeout=5)


# ============================================================================ XFCE / xfconf

@dataclass
class XTarget:
    channel: str
    prop: str                   # may contain * to match every device (touchpads)
    type: str = "string"        # bool | int | uint | double | string


class Xfce:
    name, label = "xfce", "XFCE"

    def __init__(self) -> None:
        self._lists: dict[str, list[str]] = {}

    def available(self) -> bool:
        return bool(which("xfconf-query"))

    def target_ok(self, t: XTarget) -> bool:
        return "*" not in t.prop or bool(self._match(t))

    def _match(self, t: XTarget) -> list[str]:
        if "*" not in t.prop:
            return [t.prop]
        if t.channel not in self._lists:
            rc, out = run(["xfconf-query", "-c", t.channel, "-l"])
            self._lists[t.channel] = out.split() if rc == 0 else []
        return [p for p in self._lists[t.channel] if fnmatch.fnmatch(p, t.prop)]

    def read(self, t: XTarget) -> Any:
        props = self._match(t)
        if not props:
            return None
        rc, out = run(["xfconf-query", "-c", t.channel, "-p", props[0]])
        if rc:
            return None  # property not set yet
        return out

    def write(self, t: XTarget, v: Any) -> None:
        val = ("true" if v else "false") if t.type == "bool" else str(v)
        for p in self._match(t):
            rc, out = run(["xfconf-query", "-c", t.channel, "-p", p, "-n", "-t", t.type, "-s", val])
            if rc:
                raise BackendError(out)


# ============================================================================ GTK settings.ini

class GtkIni:
    name, label = "gtk", "GTK apps"
    FILES = [CONF_HOME / "gtk-3.0/settings.ini", CONF_HOME / "gtk-4.0/settings.ini"]

    def available(self) -> bool:
        return True

    def target_ok(self, t: str) -> bool:
        return True

    @staticmethod
    def _load(p: Path) -> configparser.ConfigParser:
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str  # type: ignore[assignment,method-assign]
        if p.is_file():
            try:
                cp.read(p)
            except configparser.Error:
                pass
        return cp

    def read(self, t: str) -> Any:
        cp = self._load(self.FILES[0])
        return cp.get("Settings", t, fallback=None)

    def write(self, t: str, v: Any) -> None:
        for p in self.FILES:
            cp = self._load(p)
            if not cp.has_section("Settings"):
                cp.add_section("Settings")
            cp.set("Settings", t, ("true" if v else "false") if isinstance(v, bool) else str(v))
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w") as f:
                cp.write(f, space_around_delimiters=False)


# ============================================================================ Hyprland

class Hypr:
    name, label = "hypr", "Hyprland"
    STORE = APP_CONF / "hyprland.json"
    CONF = CONF_HOME / "hypr/omni-settings.conf"
    LUA = CONF_HOME / "hypr/omni-settings.lua"
    HEADER = "Generated by Omni Settings — change values in the app; edits here are overwritten."

    def __init__(self) -> None:
        self.store: dict = {"options": {}, "monitors": {}, "cursor": {}}
        if self.STORE.is_file():
            try:
                self.store.update(json.loads(self.STORE.read_text()))
            except ValueError:
                pass
        self.notice = ""  # one-time message for the UI

    # ---- environment
    def available(self) -> bool:
        return bool(which("Hyprland", "hyprland", "hyprctl"))

    def target_ok(self, t: str) -> bool:
        return True

    def running(self) -> bool:
        rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if sig and Path(rt, "hypr", sig, ".socket.sock").exists():
            return bool(which("hyprctl"))
        dirs = sorted(Path(rt, "hypr").glob("*/.socket.sock"), key=lambda p: p.stat().st_mtime, reverse=True)
        if dirs:
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = dirs[0].parent.name
            return bool(which("hyprctl"))
        return False

    def is_lua(self) -> bool:
        return (CONF_HOME / "hypr/hyprland.lua").is_file()

    # ---- formatting
    @staticmethod
    def fmt_conf(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, float):
            return f"{v:.3f}".rstrip("0").rstrip(".")
        return str(v)

    @staticmethod
    def fmt_lua(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return Hypr.fmt_conf(v)
        return json.dumps(str(v), ensure_ascii=False)

    @staticmethod
    def lua_table(opt: str, v: Any) -> str:
        out = Hypr.fmt_lua(v)
        for seg in reversed(opt.split(":")):
            key = seg if re.fullmatch(r"[A-Za-z_]\w*", seg) else f'["{seg}"]'
            out = "{ " + key + " = " + out + " }"
        return f"hl.config({out})"

    # ---- read / write options
    def read(self, opt: str) -> Any:
        if opt in self.store["options"]:
            return self.store["options"][opt]
        if not self.running():
            return None
        rc, out = run(["hyprctl", "getoption", "-j", opt])
        if rc:
            return None
        try:
            d = json.loads(out)
        except ValueError:
            return None
        for k in ("int", "float", "str", "custom", "data"):
            if k in d:
                v = d[k]
                if k == "custom" and isinstance(v, str):
                    m = re.match(r"([0-9a-fA-F]{8})\b", v.strip())  # gradient "AARRGGBB ... 45deg"
                    if m:
                        a, rgb = m.group(1)[:2], m.group(1)[2:]
                        return f"rgba({rgb}{a})"
                return v
        return None

    def write(self, opt: str, v: Any) -> None:
        self.store["options"][opt] = v
        self.save()
        if self.running():
            self.apply_live(opt, v)

    def apply_live(self, opt: str, v: Any) -> None:
        if self.is_lua():
            rc, out = run(["hyprctl", "eval", self.lua_table(opt, v)])
        else:
            rc, out = run(["hyprctl", "keyword", opt, self.fmt_conf(v)])
        if rc or (out and "ok" not in out.lower()):
            raise BackendError(f"Hyprland: {out or 'error'} (saved to config anyway)")

    # ---- cursor (env + hyprctl setcursor)
    def set_cursor(self, theme: str | None = None, size: int | None = None) -> None:
        c = self.store["cursor"]
        if theme is not None:
            c["theme"] = theme
        if size is not None:
            c["size"] = int(size)
        self.save()
        if self.running() and c.get("theme"):
            run(["hyprctl", "setcursor", c["theme"], str(c.get("size", 24))])

    # ---- monitors
    def monitors(self) -> list[dict]:
        if not self.running():
            return []
        rc, out = run(["hyprctl", "monitors", "-j"])
        try:
            return json.loads(out) if rc == 0 else []
        except ValueError:
            return []

    def set_monitor(self, name: str, mode: str, scale: float, x: int, y: int, vrr: int | None = None) -> None:
        line = f"{name},{mode},{x}x{y},{self.fmt_conf(float(scale))}"
        if vrr is not None:
            line += f",vrr,{vrr}"
        self.store["monitors"][name] = line
        self.save()
        if not self.running():
            return
        if not self.is_lua():
            rc, out = run(["hyprctl", "keyword", "monitor", line])
            if rc == 0 and "ok" in out.lower():
                return
        if which("wlr-randr"):
            wmode = mode if "@" not in mode or mode.endswith("Hz") else mode + "Hz"
            run(["wlr-randr", "--output", name, "--mode", wmode, "--scale", self.fmt_conf(float(scale))])
        else:
            raise BackendError("install wlr-randr to change monitors live with a Lua config")

    # ---- persistence
    def save(self) -> None:
        self.STORE.write_text(json.dumps(self.store, indent=2, ensure_ascii=False))
        self.CONF.parent.mkdir(parents=True, exist_ok=True)
        opts, mons, cur = self.store["options"], self.store["monitors"], self.store["cursor"]
        conf = [f"# {self.HEADER}", ""]
        conf += [f"{k} = {self.fmt_conf(v)}" for k, v in sorted(opts.items())]
        if mons:
            conf += ["", *[f"monitor = {line}" for line in mons.values()]]
        if cur.get("theme"):
            conf += ["", f"env = XCURSOR_THEME,{cur['theme']}", f"env = XCURSOR_SIZE,{cur.get('size', 24)}",
                     f"env = HYPRCURSOR_SIZE,{cur.get('size', 24)}",
                     f"exec-once = hyprctl setcursor {cur['theme']} {cur.get('size', 24)}"]
        self.CONF.write_text("\n".join(conf) + "\n")
        lua = [f"-- {self.HEADER}", ""]
        lua += [self.lua_table(k, v) for k, v in sorted(opts.items())]
        if cur.get("theme"):
            lua += ["", 'hl.on("hyprland.start", function()',
                    f'    hl.exec_cmd("hyprctl setcursor {cur["theme"]} {cur.get("size", 24)}")', "end)"]
        self.LUA.write_text("\n".join(lua) + "\n")
        self.ensure_sourced()

    def ensure_sourced(self) -> None:
        main = CONF_HOME / "hypr/hyprland.conf"
        if self.is_lua():
            lua_main = CONF_HOME / "hypr/hyprland.lua"
            if "omni-settings.lua" not in lua_main.read_text(errors="ignore"):
                self.notice = ('Your Hyprland uses a Lua config. To keep these settings after a restart, add this '
                               'line at the end of hyprland.lua:  dofile(os.getenv("HOME") .. '
                               '"/.config/hypr/omni-settings.lua")')
            return
        if main.is_file() and "omni-settings.conf" not in main.read_text(errors="ignore"):
            backup = main.with_suffix(".conf.bak-omni-settings")
            if not backup.exists():
                shutil.copy2(main, backup)
            with main.open("a") as f:
                f.write("\n# Omni Settings — keep this line LAST so the app's values win\n"
                        "source = ~/.config/hypr/omni-settings.conf\n")
            self.notice = "Added 'source = ~/.config/hypr/omni-settings.conf' to hyprland.conf (backup saved)."


# ============================================================================ special actions

class Special:
    """Settings that are applied by running a program rather than writing a key."""

    name, label = "special", ""
    LABELS = {"kde_dark": "KDE Plasma", "kde_colorscheme": "KDE Plasma", "kde_lnf": "KDE Plasma",
              "kde_cursor": "KDE Plasma", "kde_wallpaper": "KDE Plasma", "hyprsunset": "Hyprland",
              "hypr_cursor_theme": "Hyprland", "hypr_cursor_size": "Hyprland", "xcursor_default": "X11 apps",
              "wallpaper": "GNOME · KDE · XFCE · Hyprland"}

    def __init__(self, engine: "Engine") -> None:
        self.e = engine

    def available(self) -> bool:
        return True

    def target_ok(self, t: str) -> bool:
        need = {
            "kde_dark": "plasma-apply-colorscheme", "kde_colorscheme": "plasma-apply-colorscheme",
            "kde_lnf": "plasma-apply-lookandfeel", "kde_cursor": "plasma-apply-cursortheme",
            "kde_wallpaper": "plasma-apply-wallpaperimage", "hyprsunset": "hyprsunset",
        }.get(t)
        if need:
            return bool(which(need))
        if t.startswith("hypr_"):
            return self.e.backends["hypr"].available()
        return True

    def read(self, t: str) -> Any:
        k = self.e.backends["kde"]
        if t == "kde_dark":
            v = k.read(KTarget("kdeglobals", "General", "ColorScheme")) if k.available() else None
            return None if v is None else "dark" in v.lower()
        if t == "kde_colorscheme":
            return k.read(KTarget("kdeglobals", "General", "ColorScheme")) if k.available() else None
        if t == "kde_lnf":
            return k.read(KTarget("kdeglobals", "KDE", "LookAndFeelPackage")) if k.available() else None
        if t == "hyprsunset":
            return run(["pgrep", "-x", "hyprsunset"])[0] == 0
        if t == "hypr_cursor_theme":
            return self.e.backends["hypr"].store["cursor"].get("theme")
        if t == "hypr_cursor_size":
            return self.e.backends["hypr"].store["cursor"].get("size")
        if t == "wallpaper":
            return json.loads((APP_CONF / "state.json").read_text()).get("wallpaper") \
                if (APP_CONF / "state.json").is_file() else None
        return None  # kde_cursor, kde_wallpaper, xcursor_default: write-only

    def write(self, t: str, v: Any) -> None:
        if t == "kde_dark":
            scheme = "BreezeDark" if v else "BreezeLight"
            rc, out = run(["plasma-apply-colorscheme", scheme])
            if rc:
                raise BackendError(out)
        elif t == "kde_colorscheme":
            rc, out = run(["plasma-apply-colorscheme", str(v)])
            if rc:
                raise BackendError(out)
        elif t == "kde_lnf":
            rc, out = run(["plasma-apply-lookandfeel", "-a", str(v)], timeout=30)
            if rc:
                raise BackendError(out)
        elif t == "kde_cursor":
            run(["plasma-apply-cursortheme", str(v)])
        elif t == "kde_wallpaper":
            run(["plasma-apply-wallpaperimage", str(v)])
        elif t == "xcursor_default":
            # XWayland / X11 apps read this
            p = HOME / ".icons/default/index.theme"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"[Icon Theme]\nName=Default\nComment=Default cursor theme\nInherits={v}\n")
        elif t == "hypr_cursor_theme":
            self.e.backends["hypr"].set_cursor(theme=str(v))
        elif t == "hypr_cursor_size":
            self.e.backends["hypr"].set_cursor(size=int(v))
        elif t == "hyprsunset":
            if v:
                if run(["pgrep", "-x", "hyprsunset"])[0] != 0:
                    spawn(["hyprsunset", "-t", "4000"])
            else:
                run(["pkill", "-x", "hyprsunset"])
        elif t == "wallpaper":
            self.wallpaper(str(v))

    def wallpaper(self, path: str) -> None:
        state_f = APP_CONF / "state.json"
        state = json.loads(state_f.read_text()) if state_f.is_file() else {}
        state["wallpaper"] = path
        state_f.write_text(json.dumps(state, indent=2))
        uri = Path(path).as_uri()
        g = self.e.backends["gnome"]
        for key in ("picture-uri", "picture-uri-dark"):
            if g.available() and g.target_ok(("org.gnome.desktop.background", key)):
                g.write(("org.gnome.desktop.background", key), uri)
        if which("plasma-apply-wallpaperimage") and run(["pgrep", "-x", "plasmashell"])[0] == 0:
            run(["plasma-apply-wallpaperimage", path])
        x = self.e.backends["xfce"]
        if x.available():
            x.write(XTarget("xfce4-desktop", "/backdrop/screen*/monitor*/workspace*/last-image"), path)
        if self.e.backends["hypr"].running():
            if run(["pgrep", "-x", "swww-daemon"])[0] == 0:
                run(["swww", "img", path, "--transition-type", "grow"])
            elif run(["pgrep", "-x", "hyprpaper"])[0] == 0:
                run(["hyprctl", "hyprpaper", "reload", f",{path}"])
            elif which("swaybg"):
                run(["pkill", "-x", "swaybg"])
                spawn(["swaybg", "-m", "fill", "-i", path])


# ============================================================================ the engine

@dataclass
class Map:
    backend: str
    target: Any
    to: Callable[[Any], Any] | None = None          # app value -> backend value
    frm: Callable[[Any], Any] | None = None         # backend value -> app value
    merge: Callable[[Any, Any], Any] | None = None  # (app value, current backend value) -> backend value
    write_only: bool = False


@dataclass
class Setting:
    id: str
    title: str
    kind: str                       # bool int float enum choice text font color file
    maps: list[Map]
    subtitle: str = ""
    default: Any = None
    min: float = 0
    max: float = 100
    step: float = 1
    digits: int = 0
    options: list[tuple[Any, str]] = field(default_factory=list)   # for enum
    source: str = ""                # for choice: provider name in themes.py
    keywords: str = ""              # extra words for search


def coerce(kind: str, v: Any) -> Any:
    if v is None:
        return None
    try:
        if kind == "bool":
            return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
        if kind == "int":
            return int(float(v))
        if kind == "float":
            return float(v)
    except (TypeError, ValueError):
        return None
    return v


def detect_desktops() -> dict[str, dict[str, bool]]:
    cur = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    found = {
        "hypr": bool(which("Hyprland", "hyprland")),
        "gnome": bool(which("gnome-shell")),
        "kde": bool(which("plasmashell")),
        "xfce": bool(which("xfwm4", "xfce4-session")),
    }
    names = {"hypr": "hyprland", "gnome": "gnome", "kde": "kde", "xfce": "xfce"}
    return {k: {"installed": v, "running": names[k] in cur} for k, v in found.items()}


class Engine:
    def __init__(self) -> None:
        self.backends: dict[str, Any] = {"gnome": Gnome(), "kde": Kde(), "xfce": Xfce(), "hypr": Hypr(),
                                         "gtk": GtkIni()}
        self.backends["special"] = Special(self)
        self.desktops = detect_desktops()
        self.originals: dict[str, Any] = {}
        self._ok: dict[int, bool] = {}
        running = [k for k, d in self.desktops.items() if d["running"]]
        self.order = running + [b for b in ("gnome", "kde", "xfce", "hypr", "gtk", "special") if b not in running]

    def map_ok(self, m: Map) -> bool:
        key = id(m)
        if key not in self._ok:
            b = self.backends[m.backend]
            try:
                self._ok[key] = b.available() and b.target_ok(m.target)
            except Exception:  # noqa: BLE001
                self._ok[key] = False
        return self._ok[key]

    def maps_for(self, s: Setting) -> list[Map]:
        return [m for m in s.maps if self.map_ok(m)]

    def applies_to(self, s: Setting) -> list[str]:
        labels: list[str] = []
        for m in self.maps_for(s):
            if m.write_only:
                continue
            lab = self.backends[m.backend].label or Special.LABELS.get(str(m.target), "")
            if lab and lab not in labels:
                labels.append(lab)
        return labels

    def read(self, s: Setting, use_default: bool = True) -> Any:
        maps = sorted((m for m in self.maps_for(s) if not m.write_only),
                      key=lambda m: self.order.index(m.backend) if m.backend in self.order else 99)
        for m in maps:
            try:
                raw = self.backends[m.backend].read(m.target)
            except BackendError:
                continue
            if raw is None:
                continue
            try:
                v = coerce(s.kind, m.frm(raw) if m.frm else raw)
            except Exception:  # noqa: BLE001  (odd value in a config file)
                continue
            if v is not None:
                return v
        return s.default if use_default else None

    def write(self, s: Setting, value: Any) -> list[str]:
        """Apply value to every desktop that has this setting. Returns error messages."""
        if s.id not in self.originals:
            self.originals[s.id] = self.read(s, use_default=False)
        errors: list[str] = []
        for m in self.maps_for(s):
            b = self.backends[m.backend]
            try:
                raw = m.to(value) if m.to else value
                if m.merge:
                    try:
                        old = b.read(m.target)
                    except BackendError:
                        old = None
                    raw = m.merge(value, old)
                if raw is None:
                    continue
                b.write(m.target, raw)
            except BackendError as e:
                errors.append(f"{b.label or m.target}: {e}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{b.label or m.target}: {e}")
        return errors

    # ---- profiles
    def snapshot(self, settings: list[Setting]) -> dict[str, Any]:
        """Only values really read from a desktop (never built-in defaults)."""
        out: dict[str, Any] = {}
        for s in settings:
            if self.maps_for(s) and s.kind != "file":
                v = self.read(s, use_default=False)
                if v is not None:
                    out[s.id] = v
        return out

    def save_profile(self, name: str, settings: list[Setting]) -> Path:
        d = APP_CONF / "profiles"
        d.mkdir(exist_ok=True)
        p = d / (re.sub(r"[^\w.-]+", "_", name).strip("_") or "profile")
        p = p.with_suffix(".json")
        p.write_text(json.dumps({"name": name, "saved": time.strftime("%F %T"),
                                 "values": self.snapshot(settings)}, indent=2, ensure_ascii=False))
        return p

    def apply_values(self, values: dict[str, Any], settings: list[Setting]) -> list[str]:
        by_id = {s.id: s for s in settings}
        errors: list[str] = []
        for sid, v in values.items():
            s = by_id.get(sid)
            if s is None or v is None:
                continue
            cur = self.read(s, use_default=False)
            if cur is not None and str(coerce(s.kind, v)) == str(cur):
                continue  # unchanged: don't pin it into every config file
            errors += self.write(s, v)
        return errors
