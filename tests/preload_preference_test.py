#!/usr/bin/env python3

import json
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path


base = sys.argv[1]
phase = sys.argv[2]
preference_path = Path(sys.argv[3])


def request(method, path, payload=None):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()

    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


if phase == "configure":
    status, runtime = request("GET", "/v1/runtime/status")
    assert status == 200, runtime
    assert runtime["current_model"] is None, runtime
    assert runtime["backend_running"] is False, runtime
    assert runtime["startup_preload"]["state"] == "disabled", runtime

    # Read-only inspection must never load a model.
    status, _ = request("GET", "/health")
    assert status == 200
    status, _ = request("GET", "/v1/models")
    assert status == 200
    status, preferences = request("GET", "/v1/runtime/preferences")
    assert status == 200, preferences
    assert preferences["preload_enabled"] is False, preferences

    status, runtime = request("GET", "/v1/runtime/status")
    assert runtime["current_model"] is None, runtime
    assert runtime["backend_running"] is False, runtime

    status, result = request(
        "POST",
        "/v1/runtime/preferences",
        {"preload_model": "model-a"},
    )
    assert status == 200, result
    assert result["preload_enabled"] is True, result
    assert result["preload_model"] == "model-a", result
    assert result["applies_on_next_start"] is True, result
    assert result["startup_preload"]["state"] == "pending_restart", result

    assert preference_path.is_file(), preference_path
    assert preference_path.stat().st_mode & 0o777 == 0o600
    stored = json.loads(preference_path.read_text(encoding="utf-8"))
    assert stored["preload_model"] == "model-a", stored

    status, missing = request(
        "POST",
        "/v1/runtime/preferences",
        {"preload_model": "does-not-exist"},
    )
    assert status == 404, missing
    assert missing["error"]["type"] == "model_not_found", missing

    print("DEFAULT PRELOAD OFF       PASS")
    print("READ-ONLY NO LOAD         PASS")
    print("PREFERENCE PERSISTENCE    PASS")
    print("UNKNOWN MODEL GUARD       PASS")

elif phase == "verify-loaded":
    deadline = time.time() + 15
    runtime = None

    while time.time() < deadline:
        status, runtime = request("GET", "/v1/runtime/status")
        assert status == 200, runtime
        if runtime["startup_preload"]["state"] in ("loaded", "error"):
            break
        time.sleep(0.1)

    assert runtime["startup_preload"]["state"] == "loaded", runtime
    assert runtime["current_model"] == "model-a", runtime
    assert runtime["backend_running"] is True, runtime

    status, result = request(
        "POST",
        "/v1/runtime/preferences",
        {"preload_model": ""},
    )
    assert status == 200, result
    assert result["preload_enabled"] is False, result
    assert result["startup_preload"]["state"] == "disabled", result

    # Disabling controls the next start and must not interrupt an active
    # client/model in the current session.
    status, runtime = request("GET", "/v1/runtime/status")
    assert runtime["current_model"] == "model-a", runtime
    assert runtime["backend_running"] is True, runtime

    print("STARTUP PRELOAD           PASS")
    print("SINGLE MODEL RESIDENCY    PASS")
    print("DISABLE WITHOUT DISRUPT   PASS")

elif phase == "verify-disabled":
    status, runtime = request("GET", "/v1/runtime/status")
    assert status == 200, runtime
    assert runtime["startup_preload"]["state"] == "disabled", runtime
    assert runtime["current_model"] is None, runtime
    assert runtime["backend_running"] is False, runtime

    print("DISABLED AFTER RESTART    PASS")

else:
    raise SystemExit(f"Unknown phase: {phase}")
