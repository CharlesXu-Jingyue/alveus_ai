#!/usr/bin/env bash
# Render and install the systemd --user units for the current machine.
# Usage: scripts/install_services.sh [--enable] [--start]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON_BIN:-$(command -v python)}"
MODELS="${ALVEUS_MODELS:-$(cd "$HERE" && "$PY" -c 'from alveus.config import load_config;print(load_config()._env["ALVEUS_MODELS"])')}"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
for u in alveus-llm alveus; do
  sed -e "s#@ALVEUS_HOME@#$HERE#g" -e "s#@ALVEUS_MODELS@#$MODELS#g" -e "s#@PYTHON_BIN@#$PY#g" \
      "$HERE/systemd/$u.service.in" > "$UNIT_DIR/$u.service"
  echo "wrote $UNIT_DIR/$u.service"
done
systemctl --user daemon-reload
if [[ " $* " == *" --enable "* ]]; then systemctl --user enable alveus-llm.service alveus.service; fi
if [[ " $* " == *" --start "* ]]; then systemctl --user restart alveus-llm.service alveus.service; fi
echo "Manage with: systemctl --user {start|stop|status} alveus-llm alveus ; logs: journalctl --user -u alveus -f"
