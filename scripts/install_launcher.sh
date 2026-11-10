#!/usr/bin/env bash
# Add an "Alveus" launcher to the app grid (Activities search, can be pinned to the dock) and an
# icon on the desktop. Both run scripts/alveus-start, which starts everything and opens the GUI.
# Usage: scripts/install_launcher.sh [--no-desktop]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$HERE/scripts/alveus-start"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
cat > "$APPS/alveus.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Alveus
Comment=Start the Alveus assistant and open its window
Exec=$HERE/scripts/alveus-start
Icon=audio-input-microphone
Terminal=false
Categories=Utility;
DESK
update-desktop-database "$APPS" 2>/dev/null || true
echo "wrote $APPS/alveus.desktop"
if [[ " $* " != *" --no-desktop "* ]]; then
  DESK_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
  mkdir -p "$DESK_DIR"
  cp "$APPS/alveus.desktop" "$DESK_DIR/alveus.desktop"
  chmod +x "$DESK_DIR/alveus.desktop"
  gio set "$DESK_DIR/alveus.desktop" metadata::trusted true 2>/dev/null || true
  echo "wrote $DESK_DIR/alveus.desktop (if it shows as a file: right-click → Allow Launching)"
fi
