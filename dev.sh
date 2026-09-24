#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

case "${1:-}" in
  test)
    echo "===== PYTHON SYNTAX ====="
    "$PY" -m py_compile "$ROOT/src/local_ai_runtime.py"
    echo "PYTHON SYNTAX   PASS"

    TMP="$ROOT/.runtime-test"
    rm -rf "$TMP"
    mkdir -p "$TMP"

    cat > "$TMP/config.json" <<'JSON'
{
  "listen_host": "127.0.0.1",
  "listen_port": 18111,
  "backend_host": "127.0.0.1",
  "backend_port": 18180,
  "llama_server": "",
  "startup_timeout_seconds": 5,
  "idle_unload_seconds": 5,
  "models": []
}
JSON

    echo "===== START TEST DAEMON ====="
    "$PY" "$ROOT/src/local_ai_runtime.py" \
      --config "$TMP/config.json" \
      >"$TMP/server.log" 2>&1 &
    PID=$!

    cleanup() {
      kill "$PID" 2>/dev/null || true
      wait "$PID" 2>/dev/null || true
    }
    trap cleanup EXIT

    READY=0
    for _ in $(seq 1 40); do
      if "$PY" - <<'CHECK' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:18111/health", timeout=1).read()
CHECK
      then
        READY=1
        break
      fi
      sleep 0.1
    done

    if [[ "$READY" != "1" ]]; then
      echo "TEST DAEMON FAILED"
      cat "$TMP/server.log"
      exit 1
    fi

    echo "DAEMON START     PASS"
    "$PY" "$ROOT/tests/smoke.py" \
      "http://127.0.0.1:18111"

    echo "===== RESULT ====="
    echo "LOCAL AI RUNTIME STAGE 0: PASS"
    ;;

  run)
    exec "$PY" "$ROOT/src/local_ai_runtime.py" \
      --config "${2:-$HOME/.config/local-ai-runtime/config.json}"
    ;;

  *)
    echo "Usage:"
    echo "  ./dev.sh test"
    echo "  ./dev.sh run [config.json]"
    exit 2
    ;;
esac
