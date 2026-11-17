"""The settings catalogue: every setting, its control type, and where each desktop stores it.

To add a setting, add a Setting(...) to a Group with one Map per desktop that has it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backends import KTarget, Map, Setting, XTarget
from .themes import pango_to_qt, qt_to_pango


# ---- short constructors ---------------------------------------------------------
def G(schema: str, key: str, **kw: Any) -> Map:
    return Map("gnome", (schema, key), **kw)


def K(file: str, group: str | list[str], key: str, type: str = "str", hook: str = "", **kw: Any) -> Map:
    return Map("kde", KTarget(file, group, key, type, hook), **kw)


def X(channel: str, prop: str, type: str = "string", **kw: Any) -> Map:
    return Map("xfce", XTarget(channel, prop, type), **kw)


def H(opt: str, **kw: Any) -> Map:
    return Map("hypr", opt, **kw)


def T(key: str, **kw: Any) -> Map:
    return Map("gtk", key, **kw)


def S(name: str, **kw: Any) -> Map:
    return Map("special", name, **kw)


IFACE = "org.gnome.desktop.interface"
TOUCH = "org.gnome.desktop.peripherals.touchpad"
MOUSE = "org.gnome.desktop.peripherals.mouse"
KBD = "org.gnome.desktop.peripherals.keyboard"
WM = "org.gnome.desktop.wm.preferences"
MUTTER = "org.gnome.mutter"
POWER = "org.gnome.settings-daemon.plugins.power"
SOURCES = "org.gnome.desktop.input-sources"


# ---- conversions -------------------------------------------------------------------
def _grp(opts: list[str]) -> str:
    return next((o for o in opts if o.startswith("grp:")), "")


def merge_list(v: str, old: Any) -> list[str]:
    old = old if isinstance(old, list) else []
    return [o for o in old if not o.startswith("grp:")] + ([v] if v else [])


def merge_str(v: str, old: Any) -> str:
    parts = [o for o in str(old or "").split(",") if o and not o.startswith("grp:")]
    return ",".join(parts + ([v] if v else []))


def gnome_layouts_to(v: str) -> list[tuple[str, str]]:
    return [("xkb", x.strip()) for x in v.split(",") if x.strip()]


def gnome_layouts_from(raw: Any) -> str:
    return ",".join(t[1] for t in raw if isinstance(t, tuple) and t[0] == "xkb")


@dataclass
class Group:
    title: str
    settings: list[Setting]
    description: str = ""


@dataclass
class Page:
    id: str
    title: str
    icon: str
    groups: list[Group]
    desktop: str = ""          # "" = all desktops; else gnome/kde/xfce/hypr (page hidden if not installed)
    description: str = ""
    special: str = ""          # "monitors" | "profiles" | "about"
    sub: list[str] = field(default_factory=list)


SWITCH_OPTS = [("grp:alt_shift_toggle", "Alt + Shift"), ("grp:ctrl_shift_toggle", "Ctrl + Shift"),
               ("grp:win_space_toggle", "Super + Space"), ("grp:caps_toggle", "Caps Lock"),
               ("grp:alt_space_toggle", "Alt + Space"), ("", "None")]

# =============================================================================== EVERYWHERE
everywhere = Page("everywhere", "Everywhere", "preferences-desktop-symbolic", description=(
    "Set once, applied to every installed desktop: GNOME, KDE Plasma, XFCE, Hyprland and GTK apps."), groups=[
    Group("Style", [
        Setting("dark", "Dark style", "bool", subtitle="Dark colours for apps and the desktop", maps=[
            G(IFACE, "color-scheme", to=lambda v: "prefer-dark" if v else "default",
              frm=lambda r: r == "prefer-dark"),
            S("kde_dark"),
            T("gtk-application-prefer-dark-theme", frm=lambda r: str(r).lower() in ("1", "true")),
        ], keywords="dark mode night theme тёмная"),
        Setting("gtk_theme", "Application theme (GTK)", "choice", source="gtk-themes", maps=[
            G(IFACE, "gtk-theme"), X("xsettings", "/Net/ThemeName"), T("gtk-theme-name"),
        ], keywords="theme gtk look"),
        Setting("icons", "Icon theme", "choice", source="icon-themes", maps=[
            G(IFACE, "icon-theme"), K("kdeglobals", "Icons", "Theme", hook="kglobal:4"),
            X("xsettings", "/Net/IconThemeName"), T("gtk-icon-theme-name"),
        ], keywords="icons"),
        Setting("cursor", "Cursor theme", "choice", source="cursor-themes", maps=[
            G(IFACE, "cursor-theme"), K("kcminputrc", "Mouse", "cursorTheme", hook="kglobal:5"),
            S("kde_cursor", write_only=True), X("xsettings", "/Gtk/CursorThemeName"),
            T("gtk-cursor-theme-name"), S("hypr_cursor_theme"), S("xcursor_default", write_only=True),
        ], keywords="mouse pointer cursor"),
        Setting("cursor_size", "Cursor size", "int", min=16, max=128, step=4, default=24, maps=[
            G(IFACE, "cursor-size"), K("kcminputrc", "Mouse", "cursorSize", "int", hook="kglobal:5"),
            X("xsettings", "/Gtk/CursorThemeSize", "int"), T("gtk-cursor-theme-size"), S("hypr_cursor_size"),
        ], keywords="mouse pointer big"),
        Setting("wallpaper", "Wallpaper", "file", subtitle="GNOME, KDE, XFCE; on Hyprland via swww, hyprpaper "
                "or swaybg", maps=[S("wallpaper")], keywords="background picture обои"),
    ]),
    Group("Fonts", [
        Setting("font", "Interface font", "font", default="Noto Sans 10", maps=[
            G(IFACE, "font-name"), K("kdeglobals", "General", "font", hook="kglobal:1", to=pango_to_qt,
                                     frm=qt_to_pango),
            X("xsettings", "/Gtk/FontName"), T("gtk-font-name"),
        ], keywords="text font size"),
        Setting("mono_font", "Monospace font", "font", default="Monospace 10", maps=[
            G(IFACE, "monospace-font-name"),
            K("kdeglobals", "General", "fixed", hook="kglobal:1", to=pango_to_qt, frm=qt_to_pango),
            X("xsettings", "/Gtk/MonospaceFontName"),
        ], keywords="terminal code font"),
        Setting("text_scale", "Text scaling", "float", min=0.5, max=3.0, step=0.05, digits=2, default=1.0,
                subtitle="Makes text bigger without scaling the whole screen", maps=[
            G(IFACE, "text-scaling-factor"),
            K("kcmfonts", "General", "forceFontDPI", "int", to=lambda v: int(round(96 * v)),
              frm=lambda r: int(r) / 96 if int(r) > 0 else 1.0),
            X("xsettings", "/Xft/DPI", "int", to=lambda v: int(round(96 * v)), frm=lambda r: int(r) / 96),
            T("gtk-xft-dpi", to=lambda v: int(round(98304 * v)), frm=lambda r: int(r) / 98304),
        ], keywords="dpi zoom size larger"),
        Setting("hinting", "Font hinting", "enum", default="slight",
                options=[("none", "None"), ("slight", "Slight"), ("medium", "Medium"), ("full", "Full")], maps=[
            G(IFACE, "font-hinting"),
            K("kdeglobals", "General", "XftHintStyle", to=lambda v: f"hint{v}", frm=lambda r: r.removeprefix("hint")),
            X("xsettings", "/Xft/HintStyle", to=lambda v: f"hint{v}", frm=lambda r: r.removeprefix("hint")),
            T("gtk-xft-hintstyle", to=lambda v: f"hint{v}", frm=lambda r: str(r).removeprefix("hint")),
        ], keywords="font rendering sharp"),
    ]),
    Group("Keyboard", [
        Setting("layouts", "Keyboard layouts", "text", default="us",
                subtitle="Comma separated, e.g. us,ru", maps=[
            G(SOURCES, "sources", to=gnome_layouts_to, frm=gnome_layouts_from),
            K("kxkbrc", "Layout", "LayoutList"), K("kxkbrc", "Layout", "Use", "bool", to=lambda v: True,
                                                   write_only=True),
            X("keyboard-layout", "/Default/XkbLayout"),
            X("keyboard-layout", "/Default/XkbDisable", "bool", to=lambda v: False, write_only=True),
            H("input:kb_layout"),
        ], keywords="language russian раскладка"),
        Setting("layout_switch", "Switch layout with", "enum", options=SWITCH_OPTS, default="", maps=[
            G(SOURCES, "xkb-options", merge=merge_list, frm=_grp),
            K("kxkbrc", "Layout", "Options", merge=merge_str, frm=lambda r: _grp(str(r).split(","))),
            K("kxkbrc", "Layout", "ResetOldOptions", "bool", to=lambda v: True, write_only=True),
            X("keyboard-layout", "/Default/XkbOptions/Group"),
            H("input:kb_options", merge=merge_str, frm=lambda r: _grp(str(r).split(","))),
        ], keywords="shortcut language toggle переключение"),
        Setting("repeat_delay", "Key repeat delay (ms)", "int", min=150, max=1000, step=25, default=600, maps=[
            G(KBD, "delay"), K("kcminputrc", "Keyboard", "RepeatDelay", "int"),
            X("keyboards", "/Default/KeyRepeat/Delay", "int"), H("input:repeat_delay"),
        ], keywords="typing"),
        Setting("repeat_rate", "Key repeat rate (per second)", "int", min=5, max=80, step=1, default=25, maps=[
            G(KBD, "repeat-interval", to=lambda v: int(round(1000 / v)), frm=lambda r: round(1000 / max(int(r), 1))),
            K("kcminputrc", "Keyboard", "RepeatRate", "float"),
            X("keyboards", "/Default/KeyRepeat/Rate", "int"), H("input:repeat_rate"),
        ], keywords="typing speed"),
    ]),
    Group("Mouse & touchpad", [
        Setting("pointer_speed", "Pointer speed", "float", min=-1, max=1, step=0.05, digits=2, default=0.0, maps=[
            G(TOUCH, "speed"), G(MOUSE, "speed"), H("input:sensitivity"),
        ], keywords="mouse sensitivity acceleration"),
        Setting("natural_touchpad", "Natural scrolling (touchpad)", "bool", default=True, maps=[
            G(TOUCH, "natural-scroll"),
            X("pointers", "/*ouch*ad*/Properties/libinput_Natural_Scrolling_Enabled", "int", to=int),
            H("input:touchpad:natural_scroll"),
        ], keywords="reverse scroll"),
        Setting("natural_mouse", "Natural scrolling (mouse)", "bool", default=False, maps=[
            G(MOUSE, "natural-scroll"), H("input:natural_scroll"),
        ], keywords="reverse scroll wheel"),
        Setting("tap_click", "Tap to click", "bool", default=True, maps=[
            G(TOUCH, "tap-to-click"), X("pointers", "/*ouch*ad*/Properties/libinput_Tapping_Enabled", "int", to=int),
            H("input:touchpad:tap-to-click"),
        ], keywords="touchpad tap"),
        Setting("dwt", "Disable touchpad while typing", "bool", default=True, maps=[
            G(TOUCH, "disable-while-typing"),
            X("pointers", "/*ouch*ad*/Properties/libinput_Disable_While_Typing_Enabled", "int", to=int),
            H("input:touchpad:disable_while_typing"),
        ], keywords="palm"),
    ], description="KDE keeps touchpad settings per device — set those in Plasma's own settings."),
    Group("Behaviour", [
        Setting("animations", "Animations", "bool", default=True, maps=[
            G(IFACE, "enable-animations"),
            K("kdeglobals", "KDE", "AnimationDurationFactor", "float", hook="kwin", to=lambda v: 1.0 if v else 0.0,
              frm=lambda r: float(r) > 0),
            H("animations:enabled"),
        ], keywords="effects motion speed"),
        Setting("focus_mouse", "Focus follows mouse", "bool", default=False,
                subtitle="Windows get focus when the pointer moves over them", maps=[
            G(WM, "focus-mode", to=lambda v: "sloppy" if v else "click", frm=lambda r: r in ("sloppy", "mouse")),
            K("kwinrc", "Windows", "FocusPolicy", hook="kwin", to=lambda v: "FocusFollowsMouse" if v else "ClickToFocus",
              frm=lambda r: r != "ClickToFocus"),
            X("xfwm4", "/general/click_to_focus", "bool", to=lambda v: not v, frm=lambda r: str(r) != "true"),
            H("input:follow_mouse", to=lambda v: 1 if v else 0),
        ], keywords="focus hover"),
        Setting("workspaces", "Number of workspaces", "int", min=1, max=20, default=4,
                subtitle="GNOME: turns off dynamic workspaces", maps=[
            G(WM, "num-workspaces"), G(MUTTER, "dynamic-workspaces", to=lambda v: False, write_only=True),
            K("kwinrc", "Desktops", "Number", "int", hook="kwin"),
            X("xfwm4", "/general/workspace_count", "int"),
        ], keywords="virtual desktops"),
        Setting("night_light", "Night light", "bool", subtitle="Warmer colours (Hyprland: hyprsunset)", maps=[
            G("org.gnome.settings-daemon.plugins.color", "night-light-enabled"),
            K("kwinrc", "NightColor", "Active", "bool", hook="kwin"), S("hyprsunset"),
        ], keywords="blue light warm ночной"),
        Setting("event_sounds", "Event sounds", "bool", default=True, maps=[
            G("org.gnome.desktop.sound", "event-sounds"), X("xsettings", "/Net/EnableEventSounds", "bool"),
            T("gtk-enable-event-sounds"),
        ], keywords="beep sound"),
    ]),
])

# =============================================================================== HYPRLAND
hypr_look = Page("hypr-look", "Look", "applications-graphics-symbolic", desktop="hypr", groups=[
    Group("Gaps & borders", [
        Setting("h_gaps_in", "Gaps between windows", "int", min=0, max=50, default=5, maps=[H("general:gaps_in")]),
        Setting("h_gaps_out", "Gaps to screen edges", "int", min=0, max=80, default=20, maps=[H("general:gaps_out")]),
        Setting("h_border", "Border size", "int", min=0, max=10, default=1, maps=[H("general:border_size")]),
        Setting("h_col_active", "Active border colour", "color", default="rgba(33ccffee)",
                maps=[H("general:col.active_border")]),
        Setting("h_col_inactive", "Inactive border colour", "color", default="rgba(595959aa)",
                maps=[H("general:col.inactive_border")]),
        Setting("h_rounding", "Corner rounding", "int", min=0, max=30, default=0, maps=[H("decoration:rounding")]),
        Setting("h_rounding_power", "Rounding curve", "float", min=1, max=10, step=0.1, digits=1, default=2.0,
                subtitle="2 = circle, higher = squircle", maps=[H("decoration:rounding_power")]),
    ]),
    Group("Transparency", [
        Setting("h_active_op", "Active window opacity", "float", min=0.1, max=1, step=0.02, digits=2, default=1.0,
                maps=[H("decoration:active_opacity")]),
        Setting("h_inactive_op", "Inactive window opacity", "float", min=0.1, max=1, step=0.02, digits=2,
                default=1.0, maps=[H("decoration:inactive_opacity")]),
        Setting("h_dim", "Dim inactive windows", "bool", default=False, maps=[H("decoration:dim_inactive")]),
        Setting("h_dim_strength", "Dim strength", "float", min=0, max=1, step=0.05, digits=2, default=0.5,
                maps=[H("decoration:dim_strength")]),
    ]),
    Group("Blur", [
        Setting("h_blur", "Blur", "bool", default=True, maps=[H("decoration:blur:enabled")]),
        Setting("h_blur_size", "Blur size", "int", min=1, max=20, default=8, maps=[H("decoration:blur:size")]),
        Setting("h_blur_passes", "Blur passes", "int", min=1, max=6, default=1, maps=[H("decoration:blur:passes")]),
        Setting("h_blur_vibrancy", "Vibrancy", "float", min=0, max=1, step=0.05, digits=2, default=0.17,
                maps=[H("decoration:blur:vibrancy")]),
        Setting("h_blur_xray", "X-ray (blur only the wallpaper)", "bool", default=False,
                maps=[H("decoration:blur:xray")]),
    ], description="Blur costs GPU time and battery."),
    Group("Shadows & animations", [
        Setting("h_shadow", "Shadows", "bool", default=True, maps=[H("decoration:shadow:enabled")]),
        Setting("h_shadow_range", "Shadow size", "int", min=0, max=60, default=4, maps=[H("decoration:shadow:range")]),
        Setting("h_shadow_power", "Shadow falloff", "int", min=1, max=4, default=3,
                maps=[H("decoration:shadow:render_power")]),
        Setting("h_shadow_color", "Shadow colour", "color", default="rgba(1a1a1aee)",
                maps=[H("decoration:shadow:color")]),
        Setting("h_anim", "Animations", "bool", default=True, maps=[H("animations:enabled")]),
    ]),
])

hypr_windows = Page("hypr-windows", "Windows & layout", "view-grid-symbolic", desktop="hypr", groups=[
    Group("Layout", [
        Setting("h_layout", "Tiling layout", "enum", default="dwindle",
                options=[("dwindle", "Dwindle (binary tree)"), ("master", "Master + stack"),
                         ("scrolling", "Scrolling")], maps=[H("general:layout")]),
        Setting("h_pseudotile", "Dwindle: pseudotiling", "bool", default=False, maps=[H("dwindle:pseudotile")]),
        Setting("h_preserve_split", "Dwindle: preserve split direction", "bool", default=False,
                maps=[H("dwindle:preserve_split")]),
        Setting("h_smart_split", "Dwindle: split by cursor position", "bool", default=False,
                maps=[H("dwindle:smart_split")]),
        Setting("h_master_new", "Master: new window becomes", "enum", default="slave",
                options=[("master", "Master"), ("slave", "Stack"), ("inherit", "Inherit")],
                maps=[H("master:new_status")]),
    ]),
    Group("Window behaviour", [
        Setting("h_resize_border", "Resize by dragging borders", "bool", default=False,
                maps=[H("general:resize_on_border")]),
        Setting("h_focus_activate", "Focus apps that request it", "bool", default=False,
                maps=[H("misc:focus_on_activate")]),
        Setting("h_tearing", "Allow tearing (lower input lag in games)", "bool", default=False,
                maps=[H("general:allow_tearing")]),
        Setting("h_anim_resize", "Animate manual resizes", "bool", default=False,
                maps=[H("misc:animate_manual_resizes")]),
        Setting("h_new_over_fs", "New window while fullscreen", "enum", default=0,
                options=[(0, "Opens behind"), (1, "Takes over fullscreen"), (2, "Unfullscreens")],
                maps=[H("misc:new_window_takes_over_fullscreen")]),
    ]),
])

hypr_input = Page("hypr-input", "Input", "input-keyboard-symbolic", desktop="hypr", groups=[
    Group("Keyboard", [
        Setting("h_kb_layout", "Layouts", "text", default="us", subtitle="e.g. us,ru", maps=[H("input:kb_layout")]),
        Setting("h_kb_variant", "Variants", "text", default="", subtitle="e.g. ,phonetic", maps=[H("input:kb_variant")]),
        Setting("h_kb_options", "XKB options", "text", default="",
                subtitle="e.g. grp:alt_shift_toggle,caps:escape", maps=[H("input:kb_options")]),
        Setting("h_numlock", "Num Lock on at start", "bool", default=False, maps=[H("input:numlock_by_default")]),
        Setting("h_repeat_rate", "Repeat rate", "int", min=5, max=80, default=25, maps=[H("input:repeat_rate")]),
        Setting("h_repeat_delay", "Repeat delay (ms)", "int", min=150, max=1000, step=25, default=600,
                maps=[H("input:repeat_delay")]),
    ]),
    Group("Mouse", [
        Setting("h_sens", "Sensitivity", "float", min=-1, max=1, step=0.05, digits=2, default=0.0,
                maps=[H("input:sensitivity")]),
        Setting("h_accel", "Acceleration", "enum", default="",
                options=[("", "Default"), ("adaptive", "Adaptive"), ("flat", "Flat (no acceleration)")],
                maps=[H("input:accel_profile")]),
        Setting("h_follow", "Focus follows mouse", "enum", default=1,
                options=[(0, "Off"), (1, "Always"), (2, "Cursor focus only"), (3, "Fully separate")],
                maps=[H("input:follow_mouse")]),
        Setting("h_natural", "Natural scrolling", "bool", default=False, maps=[H("input:natural_scroll")]),
        Setting("h_scroll_factor", "Scroll speed", "float", min=0.1, max=5, step=0.1, digits=1, default=1.0,
                maps=[H("input:scroll_factor")]),
    ]),
    Group("Touchpad", [
        Setting("h_tp_natural", "Natural scrolling", "bool", default=False, maps=[H("input:touchpad:natural_scroll")]),
        Setting("h_tp_tap", "Tap to click", "bool", default=True, maps=[H("input:touchpad:tap-to-click")]),
        Setting("h_tp_dwt", "Disable while typing", "bool", default=True,
                maps=[H("input:touchpad:disable_while_typing")]),
        Setting("h_tp_clickfinger", "Two-finger click = right click", "bool", default=False,
                maps=[H("input:touchpad:clickfinger_behavior")]),
        Setting("h_tp_scroll", "Scroll speed", "float", min=0.1, max=5, step=0.1, digits=1, default=1.0,
                maps=[H("input:touchpad:scroll_factor")]),
    ]),
])

hypr_misc = Page("hypr-misc", "Misc & performance", "preferences-other-symbolic", desktop="hypr", groups=[
    Group("Performance", [
        Setting("h_vfr", "Variable frame rate (saves battery)", "bool", default=True, maps=[H("misc:vfr")]),
        Setting("h_scanout", "Direct scanout", "enum", default=0,
                options=[(0, "Off"), (1, "On"), (2, "Games only")], maps=[H("render:direct_scanout")]),
        Setting("h_hw_cursor", "Hardware cursors", "enum", default=2,
                options=[(2, "Auto"), (0, "On"), (1, "Off (fixes glitches on some GPUs)")],
                maps=[H("cursor:no_hardware_cursors")]),
    ]),
    Group("Appearance", [
        Setting("h_logo", "Hide Hyprland logo", "bool", default=False, maps=[H("misc:disable_hyprland_logo")]),
        Setting("h_splash", "Hide splash text", "bool", default=False, maps=[H("misc:disable_splash_rendering")]),
        Setting("h_default_wall", "Built-in wallpaper", "enum", default=-1,
                options=[(-1, "Random"), (0, "Plain"), (1, "Anime 1"), (2, "Anime 2")],
                maps=[H("misc:force_default_wallpaper")]),
        Setting("h_cursor_timeout", "Hide cursor after (s, 0 = never)", "float", min=0, max=60, step=1, digits=0,
                default=0.0, maps=[H("cursor:inactive_timeout")]),
        Setting("h_cursor_keys", "Hide cursor while typing", "bool", default=False, maps=[H("cursor:hide_on_key_press")]),
    ]),
    Group("Compatibility", [
        Setting("h_xwayland_zero", "XWayland apps: no scaling (sharp, but small)", "bool", default=False,
                maps=[H("xwayland:force_zero_scaling")]),
        Setting("h_middle_paste", "Middle-click paste", "bool", default=True, maps=[H("misc:middle_click_paste")]),
        Setting("h_no_news", "Don't show update news", "bool", default=False, maps=[H("ecosystem:no_update_news")]),
        Setting("h_no_donate", "Don't show donation request", "bool", default=False,
                maps=[H("ecosystem:no_donation_nag")]),
    ]),
])

hypr_monitors = Page("hypr-monitors", "Monitors", "video-display-symbolic", desktop="hypr", special="monitors",
                     groups=[])

# =============================================================================== GNOME
gnome = Page("gnome", "GNOME", "org.gnome.Settings-symbolic", desktop="gnome", groups=[
    Group("Top bar & style", [
        Setting("g_accent", "Accent colour", "enum", default="blue",
                options=[(c, c.title()) for c in ("blue", "teal", "green", "yellow", "orange", "red", "pink",
                                                   "purple", "slate")], maps=[G(IFACE, "accent-color")]),
        Setting("g_clock_fmt", "Clock format", "enum", default="24h", options=[("24h", "24-hour"), ("12h", "AM/PM")],
                maps=[G(IFACE, "clock-format")]),
        Setting("g_seconds", "Show seconds", "bool", maps=[G(IFACE, "clock-show-seconds")]),
        Setting("g_weekday", "Show weekday", "bool", maps=[G(IFACE, "clock-show-weekday")]),
        Setting("g_battery", "Battery percentage", "bool", maps=[G(IFACE, "show-battery-percentage")]),
        Setting("g_hot_corner", "Hot corner", "bool", maps=[G(IFACE, "enable-hot-corners")]),
        Setting("g_overlay_scroll", "Overlay scrollbars", "bool", maps=[G(IFACE, "overlay-scrolling")]),
        Setting("g_locate", "Locate pointer with Ctrl", "bool", maps=[G(IFACE, "locate-pointer")]),
    ]),
    Group("Windows", [
        Setting("g_buttons", "Title bar buttons", "enum", default="appmenu:close", options=[
            ("appmenu:close", "Close only"), ("appmenu:minimize,maximize,close", "Minimize, maximize, close"),
            ("close,minimize,maximize:appmenu", "Left side (macOS style)")], maps=[G(WM, "button-layout")]),
        Setting("g_edge_tiling", "Snap windows to screen edges", "bool", maps=[G(MUTTER, "edge-tiling")]),
        Setting("g_center", "Center new windows", "bool", maps=[G(MUTTER, "center-new-windows")]),
        Setting("g_dynamic_ws", "Dynamic workspaces", "bool", maps=[G(MUTTER, "dynamic-workspaces")]),
        Setting("g_ws_primary", "Workspaces on primary display only", "bool",
                maps=[G(MUTTER, "workspaces-only-on-primary")]),
        Setting("g_switcher_ws", "Alt+Tab: current workspace only", "bool",
                maps=[G("org.gnome.shell.app-switcher", "current-workspace-only")]),
    ]),
    Group("Power & privacy", [
        Setting("g_idle", "Blank screen after", "enum", default=300, options=[
            (0, "Never"), (60, "1 minute"), (120, "2 minutes"), (300, "5 minutes"), (600, "10 minutes"),
            (900, "15 minutes")], maps=[G("org.gnome.desktop.session", "idle-delay")]),
        Setting("g_lock", "Lock screen when blank", "bool", maps=[G("org.gnome.desktop.screensaver", "lock-enabled")]),
        Setting("g_suspend_ac", "On AC: automatic suspend", "enum", default="nothing",
                options=[("nothing", "Off"), ("suspend", "Suspend")], maps=[G(POWER, "sleep-inactive-ac-type")]),
        Setting("g_suspend_bat", "On battery: automatic suspend", "enum", default="suspend",
                options=[("nothing", "Off"), ("suspend", "Suspend")], maps=[G(POWER, "sleep-inactive-battery-type")]),
        Setting("g_power_btn", "Power button", "enum", default="suspend",
                options=[("nothing", "Do nothing"), ("suspend", "Suspend"), ("hibernate", "Hibernate"),
                         ("interactive", "Ask")], maps=[G(POWER, "power-button-action")]),
        Setting("g_night_temp", "Night light temperature (K)", "int", min=1700, max=4700, step=100, default=2700,
                maps=[G("org.gnome.settings-daemon.plugins.color", "night-light-temperature")]),
        Setting("g_recent", "Remember recent files", "bool", maps=[G("org.gnome.desktop.privacy", "remember-recent-files")]),
    ]),
])

# =============================================================================== KDE
kde = Page("kde", "KDE Plasma", "preferences-desktop-theme-global-symbolic", desktop="kde", description=(
    "Some Plasma changes show after restarting the app or logging out."), groups=[
    Group("Look", [
        Setting("k_lnf", "Global theme", "choice", source="kde-lnf", maps=[S("kde_lnf")]),
        Setting("k_colors", "Colour scheme", "choice", source="kde-color-schemes", maps=[S("kde_colorscheme")]),
        Setting("k_anim", "Animation duration", "float", min=0, max=3, step=0.25, digits=2, default=1.0,
                subtitle="0 = instant, 1 = normal, 2 = slow",
                maps=[K("kdeglobals", "KDE", "AnimationDurationFactor", "float", hook="kwin")]),
        Setting("k_border", "Window border size", "enum", default="Normal", options=[
            ("None", "None"), ("NoSides", "No side borders"), ("Tiny", "Tiny"), ("Normal", "Normal"),
            ("Large", "Large")], maps=[K("kwinrc", "org.kde.kdecoration2", "BorderSize", hook="kwin")]),
        Setting("k_buttons", "Title bar buttons (right)", "enum", default="IAX", options=[
            ("IAX", "Minimize, maximize, close"), ("X", "Close only"), ("HIAX", "Help, minimize, maximize, close")],
            maps=[K("kwinrc", "org.kde.kdecoration2", "ButtonsOnRight", hook="kwin")]),
    ]),
    Group("Effects & behaviour", [
        Setting("k_blur", "Blur effect", "bool", default=True, maps=[K("kwinrc", "Plugins", "blurEnabled", "bool",
                                                                     hook="kwin")]),
        Setting("k_wobbly", "Wobbly windows", "bool", default=False,
                maps=[K("kwinrc", "Plugins", "wobblywindowsEnabled", "bool", hook="kwin")]),
        Setting("k_focus", "Focus policy", "enum", default="ClickToFocus", options=[
            ("ClickToFocus", "Click to focus"), ("FocusFollowsMouse", "Focus follows mouse"),
            ("FocusUnderMouse", "Focus under mouse"), ("FocusStrictlyUnderMouse", "Strictly under mouse")],
            maps=[K("kwinrc", "Windows", "FocusPolicy", hook="kwin")]),
        Setting("k_snap", "Maximize by dragging to top edge", "bool", default=True,
                maps=[K("kwinrc", "Windows", "ElectricBorderMaximize", "bool", hook="kwin")]),
        Setting("k_single_click", "Open files with a single click", "bool", default=False,
                maps=[K("kdeglobals", "KDE", "SingleClick", "bool", hook="kglobal:3")]),
        Setting("k_night_temp", "Night colour temperature (K)", "int", min=1000, max=6500, step=100, default=4500,
                maps=[K("kwinrc", "NightColor", "NightTemperature", "int", hook="kwin")]),
    ]),
    Group("Screen locking", [
        Setting("k_autolock", "Lock automatically", "bool", default=True,
                maps=[K("kscreenlockerrc", "Daemon", "Autolock", "bool")]),
        Setting("k_lock_timeout", "Lock after (minutes)", "int", min=1, max=120, default=5,
                maps=[K("kscreenlockerrc", "Daemon", "Timeout", "int")]),
        Setting("k_lock_resume", "Lock after waking from sleep", "bool", default=True,
                maps=[K("kscreenlockerrc", "Daemon", "LockOnResume", "bool")]),
    ]),
])

# =============================================================================== XFCE
xfce = Page("xfce", "XFCE", "xfce4-settings-symbolic", desktop="xfce", groups=[
    Group("Window manager", [
        Setting("x_theme", "Window decoration theme", "choice", source="xfwm-themes",
                maps=[X("xfwm4", "/general/theme")]),
        Setting("x_title_font", "Title font", "font", default="Sans Bold 9", maps=[X("xfwm4", "/general/title_font")]),
        Setting("x_buttons", "Title bar buttons", "enum", default="O|HMC", options=[
            ("O|HMC", "Minimize, maximize, close"), ("O|C", "Close only"), ("CMH|O", "Left side (macOS style)")],
            maps=[X("xfwm4", "/general/button_layout")]),
        Setting("x_snap", "Snap to screen edges", "bool", default=True, maps=[X("xfwm4", "/general/snap_to_border", "bool")]),
        Setting("x_tile", "Tile windows when dragged to edges", "bool", default=True,
                maps=[X("xfwm4", "/general/tile_on_move", "bool")]),
        Setting("x_wrap", "Switch workspace at screen edge", "bool", default=False,
                maps=[X("xfwm4", "/general/wrap_windows", "bool")]),
    ]),
    Group("Compositor", [
        Setting("x_comp", "Compositing", "bool", default=True, maps=[X("xfwm4", "/general/use_compositing", "bool")]),
        Setting("x_vblank", "V-sync method", "enum", default="auto", options=[
            ("auto", "Auto"), ("off", "Off"), ("glx", "GLX"), ("xpresent", "XPresent")],
            maps=[X("xfwm4", "/general/vblank_mode")]),
        Setting("x_shadows", "Window shadows", "bool", default=True, maps=[X("xfwm4", "/general/show_frame_shadow", "bool")]),
        Setting("x_popup_shadow", "Popup shadows", "bool", default=False,
                maps=[X("xfwm4", "/general/show_popup_shadow", "bool")]),
        Setting("x_frame_op", "Decoration opacity (%)", "int", min=10, max=100, default=100,
                maps=[X("xfwm4", "/general/frame_opacity", "int")]),
        Setting("x_inactive_op", "Inactive window opacity (%)", "int", min=10, max=100, default=100,
                maps=[X("xfwm4", "/general/inactive_opacity", "int")]),
    ]),
    Group("Panel & desktop", [
        Setting("x_panel_size", "Panel size", "int", min=16, max=128, default=30,
                maps=[X("xfce4-panel", "/panels/panel-1/size", "uint")]),
        Setting("x_panel_dark", "Dark panel", "bool", default=False, maps=[X("xfce4-panel", "/panels/dark-mode", "bool")]),
        Setting("x_desk_icons", "Desktop icons", "enum", default=2, options=[
            (0, "None"), (1, "Minimized apps"), (2, "Files and launchers")],
            maps=[X("xfce4-desktop", "/desktop-icons/style", "int")]),
        Setting("x_dnd", "Do not disturb", "bool", default=False, maps=[X("xfce4-notifyd", "/do-not-disturb", "bool")]),
    ]),
])

profiles = Page("profiles", "Profiles & backup", "document-save-symbolic", special="profiles", groups=[])
about = Page("about", "Desktops", "computer-symbolic", special="about", groups=[])

PAGES: list[Page] = [everywhere, hypr_look, hypr_windows, hypr_input, hypr_misc, hypr_monitors, gnome, kde, xfce,
                     profiles, about]


def all_settings() -> list[Setting]:
    return [s for p in PAGES for g in p.groups for s in g.settings]
