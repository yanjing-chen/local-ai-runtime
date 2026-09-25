#!/usr/bin/env bash
set -euo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )" &&
    pwd
)"

START_SERVICE=0
USE_SYSTEMD=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --start)
            START_SERVICE=1
            ;;

        --no-systemd)
            USE_SYSTEMD=0
            ;;

        *)
            echo "Unknown option: $1"
            echo "Usage: ./install-user.sh [--start] [--no-systemd]"
            exit 2
            ;;
    esac

    shift
done

LIB_DIR="$HOME/.local/lib/local-ai-runtime"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/local-ai-runtime"
SYSTEMD_DIR="$HOME/.config/systemd/user"
DATA_DIR="$HOME/.local/share/local-ai-runtime"

mkdir -p \
    "$LIB_DIR" \
    "$BIN_DIR" \
    "$CONFIG_DIR" \
    "$DATA_DIR"

install -m 0755 \
    "$ROOT/src/local_ai_runtime.py" \
    "$LIB_DIR/local_ai_runtime.py"

install -m 0644 \
    "$ROOT/src/runtime_manager.py" \
    "$LIB_DIR/runtime_manager.py"

install -m 0644 \
    "$ROOT/src/runtime_api.py" \
    "$LIB_DIR/runtime_api.py"

install -m 0644 \
    "$ROOT/src/model_api.py" \
    "$LIB_DIR/model_api.py"

install -m 0644 \
    "$ROOT/src/hunyuanocr_installer.py" \
    "$LIB_DIR/hunyuanocr_installer.py"

install -m 0644 \
    "$ROOT/src/custom_model_api.py" \
    "$LIB_DIR/custom_model_api.py"

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

if [[ "$USE_SYSTEMD" = "1" ]]; then
    mkdir -p "$SYSTEMD_DIR"

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

    if [[ "$START_SERVICE" = "1" ]]; then
        systemctl --user enable --now \
            local-ai-runtime.service
    fi
fi

echo
echo "Local AI Runtime installed."
echo
echo "Binary:"
echo "  $BIN_DIR/local-ai-runtime"
echo
echo "Configuration:"
echo "  $CONFIG_DIR/config.json"

if [[ "$USE_SYSTEMD" = "1" ]]; then
    echo
    echo "Service:"
    echo "  $SYSTEMD_DIR/local-ai-runtime.service"

    if [[ "$START_SERVICE" = "1" ]]; then
        echo
        echo "Service enabled and started."
    else
        echo
        echo "Service installed but not started."
    fi
fi
