#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

case "${1:-}" in
  test)
    echo "===== PYTHON SYNTAX ====="

    "$PY" -m py_compile \
      "$ROOT/src/local_ai_runtime.py" \
      "$ROOT/src/runtime_manager.py" \
      "$ROOT/src/runtime_api.py" \
      "$ROOT/src/runtimectl.py"

    echo "PYTHON SYNTAX        PASS"

    TMP="$ROOT/.runtime-test"

    rm -rf "$TMP"
    mkdir -p "$TMP"

    MANIFEST="$(
      "$PY" \
        "$ROOT/tests/make_runtime_api_fixture.py" \
        "$TMP"
    )"

    cat > "$TMP/config.json" <<JSON
{
  "listen_host": "127.0.0.1",
  "listen_port": 18111,

  "backend_host": "127.0.0.1",
  "backend_port": 18180,

  "llama_server": "",

  "llama_runtime_root": "$TMP/live-llama-runtime",
  "llama_runtime_manifest_url": "$MANIFEST",

  "startup_timeout_seconds": 5,
  "idle_unload_seconds": 5,

  "models": []
}
JSON

    echo "===== STAGE 0 API TEST ====="

    "$PY" \
      "$ROOT/src/local_ai_runtime.py" \
      --config "$TMP/config.json" \
      >"$TMP/server.log" 2>&1 &

    PID=$!

    cleanup() {
      kill "$PID" 2>/dev/null || true
      wait "$PID" 2>/dev/null || true
    }

    trap cleanup EXIT

    READY=0

    for _ in $(seq 1 50); do
      if "$PY" - <<'CHECK' >/dev/null 2>&1
import urllib.request
urllib.request.urlopen(
    "http://127.0.0.1:18111/health",
    timeout=1,
).read()
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

    "$PY" \
      "$ROOT/tests/smoke.py" \
      "http://127.0.0.1:18111"

    echo "===== STAGE 2B RUNTIME API TEST ====="

    "$PY" \
      "$ROOT/tests/runtime_api_test.py" \
      "http://127.0.0.1:18111"

    cleanup
    trap - EXIT

    echo "===== DIRECT RUNTIME MANAGER TEST ====="

    PYTHONPATH="$ROOT/src" \
      "$PY" \
      "$ROOT/tests/runtime_manager_test.py"

    echo "===== RESULT ====="
    echo "STAGE 0 API           PASS"
    echo "RUNTIME MANAGER       PASS"
    echo "RUNTIME STATUS API    PASS"
    echo "ASYNC INSTALL API     PASS"
    echo "INSTALL POLLING       PASS"
    echo "ROLLBACK GUARD        PASS"
    echo "LOCAL AI RUNTIME STAGE 2B: PASS"
    ;;

  run)
    exec "$PY" \
      "$ROOT/src/local_ai_runtime.py" \
      --config \
      "${2:-$HOME/.config/local-ai-runtime/config.json}"
    ;;

  runtime-status)
    PYTHONPATH="$ROOT/src" \
      exec "$PY" \
      "$ROOT/src/runtimectl.py" \
      status
    ;;

  *)
    echo "Usage:"
    echo "  ./dev.sh test"
    echo "  ./dev.sh run [config.json]"
    echo "  ./dev.sh runtime-status"
    exit 2
    ;;
esac
