#!/usr/bin/env bash
set -e

INSTALL_DIR="$HOME/.local/share/civitai-widget"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

echo "=== Installing Civitai Widget ==="

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$APP_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    echo "Copying files to $INSTALL_DIR..."
    cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR"/
fi

cd "$INSTALL_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r requirements.txt

# Create launcher wrapper
cat << 'EOF' > "$BIN_DIR/civitai-widget"
#!/usr/bin/env bash
export QT_QPA_PLATFORM=xcb
exec "$HOME/.local/share/civitai-widget/venv/bin/python3" "$HOME/.local/share/civitai-widget/civitai_widget.py" "$@"
EOF
chmod +x "$BIN_DIR/civitai-widget"

# Create .desktop entry
cat << EOF > "$APP_DIR/civitai-widget.desktop"
[Desktop Entry]
Type=Application
Name=Civitai Widget
Comment=Displays trending AI art from Civitai on your desktop
Exec=$BIN_DIR/civitai-widget
Icon=preferences-desktop-wallpaper
Terminal=false
Categories=Utility;Graphics;
StartupNotify=true
EOF
chmod +x "$APP_DIR/civitai-widget.desktop"

echo "=== Installation complete! ==="
echo "You can launch the widget via:"
echo "  - Terminal: civitai-widget"
echo "  - Application Menu: Civitai Widget"
