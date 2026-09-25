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
      "$ROOT/src/model_api.py" \
      "$ROOT/src/custom_model_api.py" \
      "$ROOT/src/runtimectl.py" \
      "$ROOT/tests/fake_llama_server.py" \
      "$ROOT/tests/catalog_scope_test.py" \
      "$ROOT/tests/custom_model_test.py" \
      "$ROOT/tests/streaming_proxy_test.py"

    echo "PYTHON SYNTAX        PASS"

    "$PY" \
      "$ROOT/tests/catalog_scope_test.py"

    TMP="$ROOT/.runtime-test"

    rm -rf "$TMP"
    mkdir -p "$TMP"

    RUNTIME_MANIFEST="$(
      "$PY" \
        "$ROOT/tests/make_runtime_api_fixture.py" \
        "$TMP/runtime-fixture"
    )"

    cat > "$TMP/config-stage0.json" <<JSON
{
  "listen_host": "127.0.0.1",
  "listen_port": 18111,
  "backend_host": "127.0.0.1",
  "backend_port": 18180,
  "llama_server": "",
  "llama_runtime_root": "$TMP/runtime-live",
  "llama_runtime_manifest_url": "$RUNTIME_MANIFEST",
  "model_root": "$TMP/models-empty",
  "custom_model_registry": "$TMP/custom-empty.json",
  "model_manifest_url": "",
  "startup_timeout_seconds": 5,
  "idle_unload_seconds": 5,
  "models": []
}
JSON

    echo "===== STAGE 0 / 2B REGRESSION ====="

    "$PY" \
      "$ROOT/src/local_ai_runtime.py" \
      --config "$TMP/config-stage0.json" \
      >"$TMP/stage0.log" 2>&1 &

    PID=$!

    cleanup_stage0() {
      kill "$PID" 2>/dev/null || true
      wait "$PID" 2>/dev/null || true
    }

    trap cleanup_stage0 EXIT

    READY=0

    for _ in $(seq 1 50); do
      if "$PY" - <<CHECK >/dev/null 2>&1
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

    test "$READY" = "1"

    "$PY" \
      "$ROOT/tests/smoke.py" \
      "http://127.0.0.1:18111"

    "$PY" \
      "$ROOT/tests/runtime_api_test.py" \
      "http://127.0.0.1:18111"

    cleanup_stage0
    trap - EXIT

    echo "===== DIRECT RUNTIME TEST ====="

    PYTHONPATH="$ROOT/src" \
      "$PY" \
      "$ROOT/tests/runtime_manager_test.py"

    echo "===== STAGE 3A MODEL SWITCH TEST ====="

    MODEL_FIXTURE="$TMP/model-fixture"

    MODEL_MANIFEST="$(
      "$PY" \
        "$ROOT/tests/make_model_fixture.py" \
        "$MODEL_FIXTURE"
    )"

    FAKE_SERVER="$ROOT/tests/fake_llama_server.py"

    cat > "$TMP/config-models.json" <<JSON
{
  "listen_host": "127.0.0.1",
  "listen_port": 18121,

  "backend_host": "127.0.0.1",
  "backend_port": 18181,

  "llama_server": "$FAKE_SERVER",

  "llama_runtime_root": "$TMP/runtime-unused",
  "llama_runtime_manifest_url": "$RUNTIME_MANIFEST",

  "model_root": "$TMP/live-models",
  "custom_model_registry": "$TMP/custom-models.json",
  "model_manifest_url": "$MODEL_MANIFEST",

  "startup_timeout_seconds": 10,
  "idle_unload_seconds": 30,

  "models": []
}
JSON

    "$PY" \
      "$ROOT/src/local_ai_runtime.py" \
      --config "$TMP/config-models.json" \
      >"$TMP/models.log" 2>&1 &

    MODEL_PID=$!

    cleanup_models() {
      kill "$MODEL_PID" 2>/dev/null || true
      wait "$MODEL_PID" 2>/dev/null || true
    }

    trap cleanup_models EXIT

    READY=0

    for _ in $(seq 1 50); do
      if "$PY" - <<CHECK >/dev/null 2>&1
import urllib.request
urllib.request.urlopen(
    "http://127.0.0.1:18121/health",
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
      echo "MODEL TEST DAEMON FAILED"
      cat "$TMP/models.log"
      exit 1
    fi

    "$PY" \
      "$ROOT/tests/model_switch_test.py" \
      "http://127.0.0.1:18121"

    echo "===== STAGE 5D STREAMING TEST ====="

    "$PY" \
      "$ROOT/tests/streaming_proxy_test.py" \
      "http://127.0.0.1:18121"

    echo "===== STAGE 6C CUSTOM MODEL TEST ====="

    "$PY" \
      "$ROOT/tests/custom_model_test.py" \
      "http://127.0.0.1:18121" \
      "$MODEL_FIXTURE/custom-files" \
      "$TMP/custom-models.json"

    cleanup_models
    trap - EXIT

    echo "===== RESULT ====="
    echo "STAGE 0 API           PASS"
    echo "RUNTIME MANAGER       PASS"
    echo "RUNTIME API           PASS"
    echo "MODEL MANAGER         PASS"
    echo "MODEL INSTALL         PASS"
    echo "MODEL SWITCH          PASS"
    echo "SINGLE RESIDENCY      PASS"
    echo "STREAMING PROXY       PASS"
    echo "CUSTOM MODEL API      PASS"
    echo "LOCAL AI RUNTIME STAGE 3A: PASS"
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
