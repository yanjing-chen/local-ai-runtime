#!/usr/bin/env bash
set -euo pipefail

systemctl --user disable --now local-ai-runtime.service \
  2>/dev/null || true

rm -f \
  "$HOME/.config/systemd/user/local-ai-runtime.service" \
  "$HOME/.local/bin/local-ai-runtime"

rm -rf "$HOME/.local/lib/local-ai-runtime"

systemctl --user daemon-reload

echo "Local AI Runtime executable/service removed."
echo "Configuration, models and user data were preserved."
