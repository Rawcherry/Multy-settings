#!/usr/bin/env bash
# Remove Omni Settings. Your desktop settings stay as they are.
set -uo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
rm -rf "$DATA/omni-settings"
rm -f "$HOME/.local/bin/omni-settings" "$DATA/applications/io.github.omni_settings.desktop"
echo ":: Omni Settings removed."
echo "   Kept: $CFG/omni-settings (profiles) and $CFG/hypr/omni-settings.conf"
if [[ -f $CFG/hypr/hyprland.conf ]] && grep -q 'omni-settings.conf' "$CFG/hypr/hyprland.conf"; then
    read -r -p ":: Also stop Hyprland from loading the Omni Settings values? [y/N] " a
    if [[ ${a:-N} =~ ^[Yy] ]]; then
        sed -i '/^# Omni Settings/d; /omni-settings\.conf/d' "$CFG/hypr/hyprland.conf"
        echo "   removed the source line from hyprland.conf"
    fi
fi
