#!/usr/bin/env bash
# Civitai Widget installer.
#   ./install.sh               install or update
#   ./install.sh --autostart   install and start the widget on login
#   ./install.sh --uninstall   remove the widget (settings and cache are kept)
set -euo pipefail

APP_ID="civitai-widget"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
BIN_DIR="$HOME/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LAUNCHER="$BIN_DIR/$APP_ID"
DESKTOP_FILE="$APP_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.svg"
AUTOSTART_FILE="$AUTOSTART_DIR/$APP_ID.desktop"

refresh_caches() {
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$(dirname "$(dirname "$ICON_DIR")")" >/dev/null 2>&1 || true
}

write_desktop_entry() {
    cat > "$1" << EOF
[Desktop Entry]
Type=Application
Name=Civitai Widget
Comment=Trending AI art from Civitai on your desktop
Exec=$LAUNCHER
Icon=$APP_ID
Terminal=false
Categories=Utility;Graphics;
StartupNotify=false
EOF
}

if [ "${1:-}" = "--uninstall" ]; then
    echo "=== Removing Civitai Widget ==="
    rm -f "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" "$AUTOSTART_FILE"
    rm -rf "$INSTALL_DIR/venv"
    refresh_caches
    echo "Done. Settings (~/.config/$APP_ID) and cache (~/.cache/civitai_widget) were left in place."
    exit 0
fi

echo "=== Installing Civitai Widget ==="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 was not found." >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Error: Python 3.10 or newer is required." >&2
    exit 1
fi
if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
    echo "Error: the Python venv module is missing. On Debian/Ubuntu: sudo apt install python3-venv" >&2
    exit 1
fi
if command -v ldconfig >/dev/null 2>&1 && ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so'; then
    echo "Warning: libxcb-cursor0 is not installed; Qt 6.5+ cannot start on X11/XWayland without it."
    echo "         On Debian/Ubuntu: sudo apt install libxcb-cursor0"
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APP_DIR" "$ICON_DIR"

if [ ! -x "$INSTALL_DIR/venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
fi

echo "Installing the application and its dependencies..."
"$INSTALL_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/python" -m pip install --quiet --upgrade "$SCRIPT_DIR"

# The launcher may be a symlink left by an older install: replace it, never write through it.
rm -f "$LAUNCHER"
cat > "$LAUNCHER" << EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/venv/bin/civitai-widget" "\$@"
EOF
chmod +x "$LAUNCHER"

install -m 644 "$SCRIPT_DIR/civitai_widget/assets/icon.svg" "$ICON_FILE"
write_desktop_entry "$DESKTOP_FILE"

if [ "${1:-}" = "--autostart" ]; then
    mkdir -p "$AUTOSTART_DIR"
    write_desktop_entry "$AUTOSTART_FILE"
    echo "Autostart enabled."
fi

refresh_caches

echo "=== Installation complete ==="
echo "Launch it from the application menu (Civitai Widget) or run: $APP_ID"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Note: $BIN_DIR is not in your PATH." ;;
esac
