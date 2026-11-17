#!/usr/bin/env bash
# Omni Settings installer — run as your normal user:  bash install.sh
set -Eeuo pipefail
SRC=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
find "$SRC" -type f \( -name '*.py' -o -name '*.sh' -o -name '*.desktop' -o -path '*/bin/*' \) -exec sed -i 's/\r$//' {} +

DEST="${XDG_DATA_HOME:-$HOME/.local/share}/omni-settings"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [[ -t 2 ]]; then B=$'\e[1m' BL=$'\e[34m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[0m'; else B='' BL='' G='' Y='' R=''; fi
msg() { printf '%s::%s %s%s%s\n' "$B$BL" "$R" "$B" "$*" "$R" >&2; }
ok() { printf '   %s%s%s\n' "$G" "$*" "$R" >&2; }
warn() { printf '%swarning:%s %s\n' "$B$Y" "$R" "$*" >&2; }
ask() {
    local d=${2:-Y} h="[Y/n]" a
    [[ $d == N ]] && h="[y/N]"
    [[ -t 0 ]] || { [[ $d == Y ]]; return; }
    read -r -p "$B$BL::$R$B $1 $h $R" a || a=""
    [[ ${a:-$d} =~ ^[Yy] ]]
}

[[ $EUID -ne 0 ]] || { echo "run as your normal user, not root" >&2; exit 1; }
msg "Omni Settings"

if command -v pacman >/dev/null; then
    need=()
    for p in python python-gobject gtk4 libadwaita; do pacman -Qq "$p" >/dev/null 2>&1 || need+=("$p"); done
    if ((${#need[@]})); then
        msg "Needed packages: ${need[*]}"
        ask "Install with 'sudo pacman -S --needed'?" Y && sudo pacman -S --needed "${need[@]}"
    fi
    if pacman -Qq hyprland >/dev/null 2>&1 && ! pacman -Qq wlr-randr >/dev/null 2>&1; then
        ask "Install wlr-randr (live monitor changes with a Lua Hyprland config)?" Y && sudo pacman -S --needed wlr-randr
    fi
fi

python3 - <<'EOF' || warn "GTK4/libadwaita check failed — the window may not open (the command-line mode still works)"
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
v = (Adw.get_major_version(), Adw.get_minor_version())
print(f"   GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()} · libadwaita {v[0]}.{v[1]}")
if v < (1, 5):
    raise SystemExit("libadwaita 1.5 or newer is needed (sudo pacman -Syu)")
EOF

msg "Installing to $DEST"
mkdir -p "$DEST" "$BIN" "$APPS"
rm -rf "$DEST/omni_settings" "$DEST/bin"
cp -r "$SRC/omni_settings" "$SRC/bin" "$DEST/"
cp "$SRC/README.md" "$SRC/uninstall.sh" "$DEST/" 2>/dev/null || true
find "$DEST" -name '__pycache__' -prune -exec rm -rf {} +
chmod +x "$DEST/bin/omni-settings"
ln -sfn "$DEST/bin/omni-settings" "$BIN/omni-settings"
sed "s|^Exec=.*|Exec=$BIN/omni-settings|" "$SRC/io.github.omni_settings.desktop" >"$APPS/io.github.omni_settings.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
ok "command: omni-settings   ·   app menu: “Omni Settings”"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "add ~/.local/bin to PATH" ;; esac

echo
"$BIN/omni-settings" --desktops | sed 's/^/   /'
msg "Done. Start it from your launcher, or run: omni-settings"
