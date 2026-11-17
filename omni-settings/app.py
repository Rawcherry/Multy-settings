"""Omni Settings — the GTK4 / libadwaita window."""

from __future__ import annotations

import json
import queue
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango, Gdk  # noqa: E402

from .backends import APP_CONF, BackendError, Engine, Setting  # noqa: E402
from .schema import PAGES, Page, all_settings  # noqa: E402
from .themes import choices  # noqa: E402

APP_ID = "io.github.omni_settings"
VERSION = "1.0.0"
SECTIONS = {"hypr": "Hyprland", "gnome": "Desktops", "kde": "Desktops", "xfce": "Desktops"}
DESKTOP_NAMES = {"hypr": "Hyprland", "gnome": "GNOME", "kde": "KDE Plasma", "xfce": "XFCE"}


# ----------------------------------------------------------------------------- colours
def parse_hypr_color(v: Any) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    s = str(v or "").strip()
    m = re.match(r"rgba\(([0-9a-fA-F]{8})\)", s) or re.match(r"rgb\(([0-9a-fA-F]{6})\)", s)
    if m:
        h = m.group(1) + ("ff" if len(m.group(1)) == 6 else "")
    else:
        m = re.match(r"0x([0-9a-fA-F]{8})", s)  # 0xAARRGGBB
        h = (m.group(1)[2:] + m.group(1)[:2]) if m else "33ccffee"
    rgba.red, rgba.green, rgba.blue, rgba.alpha = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4, 6))
    return rgba


def rgba_to_hypr(c: Gdk.RGBA) -> str:
    return "rgba(" + "".join(f"{round(x * 255):02x}" for x in (c.red, c.green, c.blue, c.alpha)) + ")"


# ----------------------------------------------------------------------------- background writer
class Writer:
    """Applies settings one after another off the UI thread (plasma-apply-* can take a second)."""

    def __init__(self, on_done: Callable[[list[str]], bool]) -> None:
        self.q: queue.Queue = queue.Queue()
        self.on_done = on_done
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, fn: Callable[..., Any], *args: Any) -> None:
        self.q.put((fn, args))

    def _loop(self) -> None:
        while True:
            fn, args = self.q.get()
            try:
                errs = fn(*args) or []
            except BackendError as e:
                errs = [str(e)]
            except Exception as e:  # noqa: BLE001
                errs = [f"{type(e).__name__}: {e}"]
            GLib.idle_add(self.on_done, list(errs))


# ----------------------------------------------------------------------------- window
class Window(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Omni Settings", default_width=1080, default_height=780)
        self.engine = Engine()
        self.settings = all_settings()
        self.writer = Writer(self._after_write)
        self.cache: dict[str, Gtk.Widget] = {}
        self.timers: dict[str, int] = {}
        self.lua_notice_shown = False
        self.current: Page | None = None

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=230, max_sidebar_width=300)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        # ---- sidebar
        running = [DESKTOP_NAMES[k] for k, d in self.engine.desktops.items() if d["running"]]
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Omni Settings",
                                                subtitle=("Running: " + ", ".join(running)) if running else ""))
        self.search = Gtk.SearchEntry(placeholder_text="Search all settings", margin_start=10, margin_end=10,
                                      margin_top=6, margin_bottom=6)
        self.search.connect("search-changed", self._on_search)
        self.listbox = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.listbox.set_header_func(self._header)
        self.pages = [p for p in PAGES if self._page_visible(p)]
        for p in self.pages:
            row = Gtk.ListBoxRow()
            row.page = p  # type: ignore[attr-defined]
            box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=6)
            box.append(Gtk.Image.new_from_icon_name(p.icon))
            box.append(Gtk.Label(label=p.title, xalign=0))
            row.set_child(box)
            self.listbox.append(row)
        self.listbox.connect("row-selected", self._on_row)
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.listbox)
        sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sbox.append(self.search)
        sbox.append(scroller)
        tv = Adw.ToolbarView()
        tv.add_top_bar(header)
        tv.set_content(sbox)
        self.split.set_sidebar(Adw.NavigationPage(title="Omni Settings", child=tv))
        self.content = Adw.NavigationPage(title="")
        self.split.set_content(self.content)
        self.listbox.select_row(self.listbox.get_row_at_index(0))

        key = Gtk.ShortcutController()
        key.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("<Control>f"),
                                          Gtk.CallbackAction.new(lambda *_: self.search.grab_focus() or True)))
        self.add_controller(key)

    # ---------------------------------------------------------------- navigation
    def _page_visible(self, p: Page) -> bool:
        if not p.desktop:
            return True
        d = self.engine.desktops.get(p.desktop, {})
        return bool(d.get("installed") or d.get("running"))

    def _header(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        sec = SECTIONS.get(row.page.desktop, "Tools" if row.page.special in ("profiles", "about") else "")
        prev = None
        if before is not None:
            prev = SECTIONS.get(before.page.desktop, "Tools" if before.page.special in ("profiles", "about") else "")
        if sec and sec != prev:
            lbl = Gtk.Label(label=sec, xalign=0, margin_start=12, margin_top=12, margin_bottom=4,
                            css_classes=["dim-label", "caption-heading"])
            row.set_header(lbl)
        else:
            row.set_header(None)

    def _on_row(self, _lb: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        if self.search.get_text():
            self.search.set_text("")
        self.show_page(row.page)

    def show_page(self, p: Page, rebuild: bool = False) -> None:
        self.current = p
        if rebuild or p.id not in self.cache:
            self.cache[p.id] = self._wrap(p.title, self.build(p), p)
        self.content.set_title(p.title)
        self.content.set_child(self.cache[p.id])
        self.split.set_show_content(True)

    def _wrap(self, title: str, body: Gtk.Widget, p: Page | None = None) -> Gtk.Widget:
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar(show_title=True))
        if p is not None and p.desktop == "hypr":
            hypr = self.engine.backends["hypr"]
            if not hypr.running():
                tv.add_top_bar(Adw.Banner(title="Hyprland is not running — changes are saved and apply at its next "
                                                "start.", revealed=True))
            elif hypr.is_lua() and "omni-settings.lua" not in (hypr.LUA.parent / "hyprland.lua").read_text(
                    errors="ignore"):
                b = Adw.Banner(title="Lua config: changes apply now, but need one line in hyprland.lua to persist.",
                               button_label="Show line", revealed=True)
                b.connect("button-clicked", lambda *_: self._show_lua_line())
                tv.add_top_bar(b)
        tv.set_content(body)
        return tv

    # ---------------------------------------------------------------- page builders
    def build(self, p: Page) -> Gtk.Widget:
        if p.special == "monitors":
            return self.build_monitors()
        if p.special == "profiles":
            return self.build_profiles()
        if p.special == "about":
            return self.build_about()
        page = Adw.PreferencesPage(title=p.title, icon_name=p.icon)
        if p.description:
            page.add(Adw.PreferencesGroup(description=p.description))
        shown = 0
        for g in p.groups:
            items = [s for s in g.settings if self.engine.maps_for(s)]
            if not items:
                continue
            grp = Adw.PreferencesGroup(title=g.title, description=g.description)
            for s in items:
                grp.add(self.make_row(s, badges=(p.id == "everywhere")))
                shown += 1
            page.add(grp)
        if not shown:
            page.add(Adw.PreferencesGroup(title="Nothing to set here",
                                          description="The tools this page needs are not installed."))
        return page

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        q = entry.get_text().strip().lower()
        if len(q) < 2:
            if self.current:
                self.show_page(self.current)
            return
        page = Adw.PreferencesPage()
        found = 0
        for p in self.pages:
            hits = [s for g in p.groups for s in g.settings
                    if self.engine.maps_for(s) and q in f"{s.title} {s.subtitle} {s.keywords} {p.title}".lower()]
            if hits:
                grp = Adw.PreferencesGroup(title=p.title)
                for s in hits[:30]:
                    grp.add(self.make_row(s, badges=True))
                    found += 1
                page.add(grp)
        if not found:
            page.add(Adw.PreferencesGroup(title=f"No settings match “{entry.get_text()}”"))
        self.cache.clear()  # rows elsewhere may show stale values after editing here
        self.content.set_title("Search")
        self.content.set_child(self._wrap("Search", page))
        self.split.set_show_content(True)

    # ---------------------------------------------------------------- rows
    def make_row(self, s: Setting, badges: bool = False) -> Gtk.Widget:
        value = self.engine.read(s)
        sub = s.subtitle
        if badges:
            where = " · ".join(self.engine.applies_to(s))
            if where:
                sub = f"{sub}\n{where}" if sub else where
        k = s.kind

        if k == "bool":
            row = Adw.SwitchRow(title=s.title, subtitle=sub)
            row.set_active(bool(value))
            row.connect("notify::active", lambda r, _p: self.apply(s, r.get_active()))
        elif k in ("int", "float"):
            v = value if value is not None else (s.default if s.default is not None else s.min)
            v = min(max(float(v), s.min), s.max)
            adj = Gtk.Adjustment.new(v, s.min, s.max, s.step, s.step * 10, 0)
            row = Adw.SpinRow(title=s.title, subtitle=sub, adjustment=adj, digits=s.digits, climb_rate=1)
            row.connect("notify::value", lambda r, _p: self.apply_later(
                s, int(round(r.get_value())) if k == "int" else round(r.get_value(), max(s.digits, 2))))
        elif k == "enum":
            opts = list(s.options)
            if value is not None and str(value) not in [str(o[0]) for o in opts]:
                opts.append((value, str(value)))
            row = Adw.ComboRow(title=s.title, subtitle=sub, model=Gtk.StringList.new([o[1] for o in opts]))
            want = value if value is not None else s.default
            row.set_selected(next((i for i, o in enumerate(opts) if str(o[0]) == str(want)), 0))
            row.connect("notify::selected", lambda r, _p: self.apply(s, opts[r.get_selected()][0])
                        if r.get_selected() < len(opts) else None)
        elif k == "choice":
            items = choices(s.source)
            if value and value not in items:
                items.insert(0, str(value))
            if not items:
                items = [str(value or "—")]
            row = Adw.ComboRow(title=s.title, subtitle=sub, model=Gtk.StringList.new(items), enable_search=True)
            row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            row.set_selected(items.index(value) if value in items else Gtk.INVALID_LIST_POSITION)
            row.connect("notify::selected", lambda r, _p: self.apply(s, items[r.get_selected()])
                        if r.get_selected() < len(items) else None)
        elif k == "text":
            row = Adw.EntryRow(title=s.title, show_apply_button=True)
            row.set_text("" if value is None else str(value))
            if sub:
                row.set_tooltip_text(sub)
            row.connect("apply", lambda r: self.apply(s, r.get_text().strip()))
        elif k == "font":
            row = Adw.ActionRow(title=s.title, subtitle=sub)
            btn = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), valign=Gtk.Align.CENTER, use_font=True, use_size=True)
            btn.set_font_desc(Pango.FontDescription.from_string(str(value or s.default or "Sans 10")))
            btn.connect("notify::font-desc", lambda b, _p: self.apply(s, b.get_font_desc().to_string()))
            row.add_suffix(btn)
            row.set_activatable_widget(btn)
        elif k == "color":
            row = Adw.ActionRow(title=s.title, subtitle=sub)
            btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True), valign=Gtk.Align.CENTER)
            btn.set_rgba(parse_hypr_color(value or s.default))
            btn.connect("notify::rgba", lambda b, _p: self.apply_later(s, rgba_to_hypr(b.get_rgba())))
            row.add_suffix(btn)
            row.set_activatable_widget(btn)
        elif k == "file":
            row = Adw.ActionRow(title=s.title, subtitle=str(value) if value else (sub or "Not set"))
            btn = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda *_: self.pick_image(s, row))
            row.add_suffix(btn)
        else:
            row = Adw.ActionRow(title=s.title, subtitle=f"unknown kind {k}")
        if isinstance(row, Adw.PreferencesRow):
            row.set_use_markup(False)
        return row

    def pick_image(self, s: Setting, row: Adw.ActionRow) -> None:
        f = Gtk.FileFilter(name="Images")
        f.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dlg = Gtk.FileDialog(title=s.title, filters=filters)
        pics = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or Path.home())
        if pics.is_dir():
            dlg.set_initial_folder(Gio.File.new_for_path(str(pics)))

        def done(d: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
            try:
                file = d.open_finish(res)
            except GLib.Error:
                return
            if file and file.get_path():
                row.set_subtitle(file.get_path())
                self.apply(s, file.get_path())

        dlg.open(self, None, done)

    # ---------------------------------------------------------------- applying
    def apply(self, s: Setting, value: Any) -> None:
        self.writer.submit(self.engine.write, s, value)

    def apply_later(self, s: Setting, value: Any, ms: int = 400) -> None:
        """Debounce spin buttons / colour drags: apply once the user stops changing the value."""
        if s.id in self.timers:
            GLib.source_remove(self.timers.pop(s.id))

        def fire() -> bool:
            self.timers.pop(s.id, None)
            self.apply(s, value)
            return False

        self.timers[s.id] = GLib.timeout_add(ms, fire)

    def _after_write(self, errors: list[str]) -> bool:
        if errors:
            more = f"  (+{len(errors) - 1} more)" if len(errors) > 1 else ""
            self.toast(errors[0] + more, 6)
            for e in errors:
                print("omni-settings:", e, file=sys.stderr)
        hypr = self.engine.backends["hypr"]
        if hypr.notice:
            if hypr.is_lua():
                if not self.lua_notice_shown:
                    self.lua_notice_shown = True
                    self._show_lua_line()
            else:
                self.toast(hypr.notice, 6)
            hypr.notice = ""
        return False

    def toast(self, msg: str, timeout: int = 3) -> None:
        t = Adw.Toast(title=GLib.markup_escape_text(msg), timeout=timeout)
        self.toasts.add_toast(t)

    def _show_lua_line(self) -> None:
        line = 'dofile(os.getenv("HOME") .. "/.config/hypr/omni-settings.lua")'
        dlg = Adw.AlertDialog(heading="Keep settings after restart",
                              body="Your Hyprland uses a Lua config (hyprland.lua). Changes already apply live. "
                                   "To load them at every start, add this line at the END of hyprland.lua:\n\n"
                                   f"{line}\n\nIf your Hyprland version doesn't allow dofile, copy the contents of "
                                   "~/.config/hypr/omni-settings.lua into hyprland.lua instead.")
        dlg.add_response("copy", "Copy line")
        dlg.add_response("close", "Close")
        dlg.set_default_response("copy")

        def resp(_d: Adw.AlertDialog, r: str) -> None:
            if r == "copy":
                self.get_clipboard().set(line)
                self.toast("Copied")

        dlg.connect("response", resp)
        dlg.present(self)

    # ---------------------------------------------------------------- monitors (Hyprland)
    def build_monitors(self) -> Gtk.Widget:
        hypr = self.engine.backends["hypr"]
        page = Adw.PreferencesPage()
        mons = hypr.monitors()
        if not mons:
            page.add(Adw.PreferencesGroup(title="No monitors found",
                                          description="Open Omni Settings inside a running Hyprland session."))
            return page
        page.add(Adw.PreferencesGroup(description=(
            "Hyprland may round the scale to the nearest value that gives whole pixels (1.25, 1.333, 1.5, 1.6, 2…). "
            "Settings are saved to ~/.config/hypr/omni-settings.conf.")))
        for m in mons:
            name = m.get("name", "?")
            desc = " ".join(x for x in (m.get("make", ""), m.get("model", "")) if x).strip()
            grp = Adw.PreferencesGroup(title=name, description=desc)
            modes = []
            for md in m.get("availableModes", []):
                md = md.removesuffix("Hz")
                if md not in modes:
                    modes.append(md)
            cur = f"{m.get('width')}x{m.get('height')}@{float(m.get('refreshRate', 60)):.2f}"
            if cur not in modes:
                modes.insert(0, cur)
            mode_row = Adw.ComboRow(title="Resolution & refresh rate", model=Gtk.StringList.new(modes))
            mode_row.set_selected(modes.index(cur))
            scale_row = Adw.SpinRow(title="Scale", digits=2, adjustment=Gtk.Adjustment.new(
                float(m.get("scale", 1)), 0.5, 4, 0.05, 0.25, 0))
            vrr_now = m.get("vrr", 0)
            vrr_row = Adw.ComboRow(title="Variable refresh rate (VRR)",
                                   model=Gtk.StringList.new(["Off", "On", "Fullscreen only"]))
            vrr_row.set_selected(int(vrr_now) if isinstance(vrr_now, (int, bool)) else 0)
            btn = Gtk.Button(label="Apply", css_classes=["suggested-action"], valign=Gtk.Align.CENTER)
            act = Adw.ActionRow(title="Apply to this monitor")
            act.add_suffix(btn)
            x, y = int(m.get("x", 0)), int(m.get("y", 0))

            def do_apply(_b: Gtk.Button, name: str = name, modes: list[str] = modes, mr: Adw.ComboRow = mode_row,
                         sr: Adw.SpinRow = scale_row, vr: Adw.ComboRow = vrr_row, x: int = x, y: int = y) -> None:
                mode = modes[mr.get_selected()]
                scale = round(sr.get_value(), 3)
                vrr = vr.get_selected()
                self.writer.submit(lambda: hypr.set_monitor(name, mode, scale, x, y, vrr))
                self.toast(f"{name}: {mode} × {scale:g}")

            btn.connect("clicked", do_apply)
            for r in (mode_row, scale_row, vrr_row, act):
                grp.add(r)
            page.add(grp)
        return page

    # ---------------------------------------------------------------- profiles & backup
    def build_profiles(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        sess = Adw.PreferencesGroup(title="This session",
                                    description=f"{len(self.engine.originals)} setting(s) changed since Omni Settings "
                                                "was opened.")
        undo = Adw.ActionRow(title="Undo all changes", subtitle="Restore every value to what it was at start")
        b = Gtk.Button(label="Undo all", valign=Gtk.Align.CENTER, css_classes=["destructive-action"],
                       sensitive=bool(self.engine.originals))
        b.connect("clicked", lambda *_: self._undo_all())
        undo.add_suffix(b)
        sess.add(undo)
        page.add(sess)

        prof = Adw.PreferencesGroup(title="Profiles",
                                    description="A profile stores every setting shown in this app. Handy before "
                                                "experimenting, or to switch between a 'work' and a 'gaming' setup.")
        save = Adw.EntryRow(title="Save current settings as…", show_apply_button=True)
        save.connect("apply", lambda r: self._save_profile(r.get_text().strip()))
        prof.add(save)
        pdir = APP_CONF / "profiles"
        for f in sorted(pdir.glob("*.json")) if pdir.is_dir() else []:
            try:
                data = json.loads(f.read_text())
            except ValueError:
                continue
            row = Adw.ActionRow(title=data.get("name", f.stem),
                                subtitle=f"saved {data.get('saved', '?')} · {len(data.get('values', {}))} settings")
            row.set_use_markup(False)
            apply_b = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
            apply_b.connect("clicked", lambda _b, d=data: self._apply_values(d.get("values", {}), d.get("name", "")))
            del_b = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                               tooltip_text="Delete")
            del_b.connect("clicked", lambda _b, f=f: (f.unlink(missing_ok=True), self._refresh_profiles()))
            row.add_suffix(apply_b)
            row.add_suffix(del_b)
            prof.add(row)
        page.add(prof)

        io = Adw.PreferencesGroup(title="Export / import")
        for title, sub, cb in (("Export to file…", "Save all current settings as a JSON file", self._export),
                               ("Import from file…", "Apply settings from a JSON file", self._import)):
            r = Adw.ActionRow(title=title, subtitle=sub, activatable=True)
            r.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            r.connect("activated", lambda *_a, cb=cb: cb())
            io.add(r)
        page.add(io)
        return page

    def _refresh_profiles(self) -> None:
        prof = next(p for p in PAGES if p.special == "profiles")
        self.show_page(prof, rebuild=True)

    def _undo_all(self) -> None:
        values = dict(self.engine.originals)
        self._apply_values(values, "the start of this session")
        self.engine.originals.clear()

    def _apply_values(self, values: dict, name: str) -> None:
        def job() -> list[str]:
            errs = self.engine.apply_values(values, self.settings)
            GLib.idle_add(lambda: (self.cache.clear(), self.toast(f"Applied {name}"), self._refresh_profiles())
                          and False)
            return errs

        self.writer.submit(job)

    def _save_profile(self, name: str) -> None:
        if not name:
            return

        def job() -> list[str]:
            p = self.engine.save_profile(name, self.settings)
            GLib.idle_add(lambda: (self.toast(f"Saved profile “{name}” ({p.name})"), self._refresh_profiles()) and False)
            return []

        self.toast("Reading all settings…", 2)
        self.writer.submit(job)

    def _export(self) -> None:
        dlg = Gtk.FileDialog(title="Export settings", initial_name="omni-settings.json")

        def done(d: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            path = f.get_path()

            def job() -> list[str]:
                Path(path).write_text(json.dumps({"name": Path(path).stem, "values":
                                                  self.engine.snapshot(self.settings)}, indent=2, ensure_ascii=False))
                GLib.idle_add(lambda: self.toast(f"Exported to {path}") and False)
                return []

            self.writer.submit(job)

        dlg.save(self, None, done)

    def _import(self) -> None:
        f = Gtk.FileFilter(name="JSON")
        f.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dlg = Gtk.FileDialog(title="Import settings", filters=filters)

        def done(d: Gtk.FileDialog, res: Gio.AsyncResult) -> None:
            try:
                file = d.open_finish(res)
                data = json.loads(Path(file.get_path()).read_text())
            except (GLib.Error, ValueError, OSError) as e:
                self.toast(f"Could not import: {e}")
                return
            self._apply_values(data.get("values", data), Path(file.get_path()).name)

        dlg.open(self, None, done)

    # ---------------------------------------------------------------- about
    def build_about(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        grp = Adw.PreferencesGroup(title="Desktops on this computer")
        for k, d in self.engine.desktops.items():
            state = "running now" if d["running"] else ("installed" if d["installed"] else "not installed")
            row = Adw.ActionRow(title=DESKTOP_NAMES[k], subtitle=state)
            icon = "emblem-ok-symbolic" if d["installed"] or d["running"] else "window-close-symbolic"
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            grp.add(row)
        page.add(grp)
        hypr = self.engine.backends["hypr"]
        files = Adw.PreferencesGroup(title="Where settings are saved")
        for title, sub in (("GNOME", "dconf database (gsettings)"),
                           ("KDE Plasma", "~/.config/kdeglobals, kwinrc, kcminputrc, kxkbrc…"),
                           ("XFCE", "xfconf (~/.config/xfce4/xfconf)"),
                           ("Hyprland", f"{hypr.CONF}  ·  {hypr.LUA}"),
                           ("GTK apps", "~/.config/gtk-3.0/settings.ini, ~/.config/gtk-4.0/settings.ini"),
                           ("Profiles", str(APP_CONF / "profiles"))):
            r = Adw.ActionRow(title=title, subtitle=sub)
            r.set_use_markup(False)
            files.add(r)
        page.add(files)
        ver = Adw.PreferencesGroup(title=f"Omni Settings {VERSION}",
                                   description="One settings app for GNOME, KDE Plasma, XFCE and Hyprland.")
        page.add(ver)
        return page


class App(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        win = self.props.active_window or Window(self)
        win.present()


def main() -> int:
    return App().run(sys.argv)
