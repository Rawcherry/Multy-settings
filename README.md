# Omni Settings

**One settings app for GNOME, KDE Plasma, XFCE and Hyprland.**
Change your theme, cursor, fonts, keyboard layouts or touchpad once, and every installed desktop gets it, each in its own format.
Each desktop and Hyprland also has its own pages for its specific options.

Built with GTK4 + libadwaita, so it looks native on GNOME and Hyprland and fits fine on KDE and XFCE.

## What you can set

**Everywhere** (applied to all installed desktops at once):

| Group | Settings |
|---|---|
| Style | dark style · GTK theme · icon theme · cursor theme & size · wallpaper |
| Fonts | interface font · monospace font · text scaling · hinting |
| Keyboard | layouts (e.g. `us,ru`) · layout switch shortcut (Alt+Shift, Ctrl+Shift, Super+Space, Caps Lock) · repeat delay & rate |
| Mouse & touchpad | pointer speed · natural scrolling · tap to click · disable while typing |
| Behaviour | animations · focus follows mouse · number of workspaces · night light · event sounds |

Each row shows where it applies, e.g. *GNOME · KDE Plasma · XFCE · Hyprland · GTK apps*.

**Hyprland**: Look (gaps, borders, border colours, rounding, opacity, blur, shadows, animations) · Windows & layout (dwindle / master / scrolling and their options, tearing…) · Input (layouts, XKB options, mouse, touchpad) · Misc & performance (VFR, direct scanout, hardware cursors, logo/splash, XWayland scaling) · **Monitors** (resolution, refresh rate, scale, VRR).

**GNOME**: accent colour, clock, battery %, hot corner, title-bar buttons, edge tiling, workspaces, screen blank, suspend, power button, night-light temperature, privacy.

**KDE Plasma**: global theme, colour scheme, animation speed, border size, title-bar buttons, blur and wobbly effects, focus policy, single click, night colour, screen locking.

**XFCE**: window theme, title font, buttons, snapping, tiling, compositor (v-sync, shadows, opacity), panel size, dark panel, desktop icons, do-not-disturb.

**Tools**: search across every setting (Ctrl+F) · **undo all changes from this session** · **profiles** (e.g. "Work" and "Gaming") · export/import to JSON.

Pages for desktops that aren't installed are hidden.

## Install

```bash
cd omni-settings
bash install.sh
```

The installer needs `python-gobject`, `gtk4` and `libadwaita` and offers to install them. It puts **Omni Settings** in your app launcher and adds the `omni-settings` command.

## How each desktop is changed

| Desktop | How | Live? |
|---|---|---|
| GNOME | `gsettings` (dconf) | yes |
| KDE Plasma | `kwriteconfig6`, `plasma-apply-colorscheme / -cursortheme / -lookandfeel`, KWin reconfigure | mostly. Some apps pick changes up after restart |
| XFCE | `xfconf-query` | yes |
| Hyprland | `hyprctl keyword` (or `hyprctl eval` with a Lua config) **and** saved to `~/.config/hypr/omni-settings.conf` | yes |
| GTK apps on any desktop | `~/.config/gtk-3.0/settings.ini` and `gtk-4.0/settings.ini` | new windows |

**Hyprland details**
- The first time you change a Hyprland setting, the app adds `source = ~/.config/hypr/omni-settings.conf` to the **end** of your `hyprland.conf`, so its values win. A backup is saved first. The rest of your config is never edited.
- Only the settings you actually change are written there.
- With the new **Lua config** (`hyprland.lua`, Hyprland 0.55+), changes still apply live. The app shows the one line to add so they persist: `dofile(os.getenv("HOME") .. "/.config/hypr/omni-settings.lua")`.
- The cursor is set with `hyprctl setcursor` and saved as `env = XCURSOR_*`, so XWayland apps match.
- Wallpaper on Hyprland goes through whichever is running: swww, hyprpaper or swaybg.

## Command line (scripts, keybinds)

```bash
omni-settings --list              # every setting with its current value
omni-settings --list cursor       # filter
omni-settings --set dark true
omni-settings --set layouts us,ru
omni-settings --set layout_switch "Alt + Shift"
omni-settings --set h_gaps_in 8
omni-settings --save-profile Gaming
omni-settings --profile Gaming    # e.g. bind = SUPER ALT, F1, exec, omni-settings --profile Gaming
```

## Adding a setting

Everything is described in `omni_settings/schema.py`: a title, a control type, and one line per desktop. For example:

```python
Setting("cursor_size", "Cursor size", "int", min=16, max=128, maps=[
    G("org.gnome.desktop.interface", "cursor-size"),          # GNOME
    K("kcminputrc", "Mouse", "cursorSize", "int"),            # KDE
    X("xsettings", "/Gtk/CursorThemeSize", "int"),           # XFCE
    T("gtk-cursor-theme-size"),                               # GTK settings.ini
])
```

The window builds itself from that list, so there is no UI code to write.

## Files

| Path | What |
|---|---|
| `~/.config/omni-settings/profiles/` | saved profiles |
| `~/.config/omni-settings/hyprland.json` | Hyprland values set by the app |
| `~/.config/hypr/omni-settings.conf` / `.lua` | generated Hyprland config (don't edit, it is regenerated) |
| `~/.config/hypr/hyprland.conf.bak-omni-settings` | your hyprland.conf before the source line was added |

## Uninstall

```bash
bash ~/.local/share/omni-settings/uninstall.sh
```

Your settings stay. It asks whether Hyprland should stop loading the app's values.
