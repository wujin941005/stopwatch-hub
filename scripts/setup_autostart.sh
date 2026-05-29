#!/usr/bin/env bash
#
# Install the Mac-side bridge as a background LaunchAgent that starts at login
# and pushes usage to the watch over BLE. Re-runnable.
#
# Usage: scripts/setup_autostart.sh [INTERVAL_MINUTES]   (default 5)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE="$REPO_ROOT/bridge/codexisland_bridge.py"
INTERVAL="${1:-5}"
LABEL="com.ccisland.bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$REPO_ROOT/bridge.log"

# Use the python.org / system Python (CoreBluetooth works there), not a venv.
PY="$(command -v python3)"

echo "==> Installing Python deps (bleak, certifi) for $PY ..."
CERT="$("$PY" -c 'import certifi; print(certifi.where())' 2>/dev/null || true)"
SSL_CERT_FILE="$CERT" "$PY" -m pip install --user --quiet bleak certifi

echo "==> Writing LaunchAgent $PLIST"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>-u</string>
    <string>$BRIDGE</string>
    <string>--ble</string>
    <string>$INTERVAL</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

echo "==> (Re)loading the agent"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

cat <<EOF

==> Done. The bridge now runs at login.
    - First run will ask for Bluetooth permission — click Allow.
    - Open the CC Island app on the watch so it starts advertising.
    - Logs: $LOG
    - Stop:    launchctl bootout gui/$(id -u)/$LABEL
    - Restart: launchctl kickstart -k gui/$(id -u)/$LABEL
EOF
