#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LIB_DIR="$HOME/.local/lib/local-ai-runtime"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/local-ai-runtime"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p \
  "$LIB_DIR" \
  "$BIN_DIR" \
  "$CONFIG_DIR" \
  "$SYSTEMD_DIR" \
  "$HOME/.local/share/local-ai-runtime"

install -m 0755 \
  "$ROOT/src/local_ai_runtime.py" \
  "$LIB_DIR/local_ai_runtime.py"

install -m 0644 \
  "$ROOT/src/runtime_manager.py" \
  "$LIB_DIR/runtime_manager.py"

install -m 0644 \
  "$ROOT/src/runtime_api.py" \
  "$LIB_DIR/runtime_api.py"

install -m 0755 \
  "$ROOT/src/runtimectl.py" \
  "$LIB_DIR/runtimectl.py"

cat > "$BIN_DIR/local-ai-runtime" <<EOF
#!/usr/bin/env bash
exec python3 "$LIB_DIR/local_ai_runtime.py" "\$@"
EOF

cat > "$BIN_DIR/local-ai-runtime-runtime" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$LIB_DIR" exec python3 "$LIB_DIR/runtimectl.py" "\$@"
EOF

chmod 0755 \
  "$BIN_DIR/local-ai-runtime" \
  "$BIN_DIR/local-ai-runtime-runtime"

if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  install -m 0644 \
    "$ROOT/config.example.json" \
    "$CONFIG_DIR/config.json"
fi

cat > "$SYSTEMD_DIR/local-ai-runtime.service" <<EOF
[Unit]
Description=Local AI Runtime
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/local-ai-runtime --config %h/.config/local-ai-runtime/config.json
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

echo
echo "Installed Local AI Runtime."
echo
echo "Configuration:"
echo "  $CONFIG_DIR/config.json"
echo
echo "Service:"
echo "  $SYSTEMD_DIR/local-ai-runtime.service"
echo
echo "The service was NOT started automatically."
echo "Flameshot v2.4 remains untouched."
