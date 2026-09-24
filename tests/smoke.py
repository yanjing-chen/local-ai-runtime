#!/usr/bin/env python3

import json
import sys
import urllib.error
import urllib.request


base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18111"


def get_json(path):
    with urllib.request.urlopen(base + path, timeout=3) as response:
        return response.status, json.load(response)


status, health = get_json("/health")
assert status == 200
assert health["status"] == "ok"
assert health["service"] == "local-ai-runtime"

status, models = get_json("/v1/models")
assert status == 200
assert models["object"] == "list"
assert models["data"] == []

status, runtime = get_json("/v1/runtime/status")
assert status == 200
assert runtime["current_model"] is None
assert runtime["backend_running"] is False

request = urllib.request.Request(
    base + "/v1/chat/completions",
    data=json.dumps(
        {
            "model": "does-not-exist",
            "messages": [
                {
                    "role": "user",
                    "content": "hello"
                }
            ]
        }
    ).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)

try:
    urllib.request.urlopen(request, timeout=3)
    raise AssertionError("Unknown model request unexpectedly succeeded")
except urllib.error.HTTPError as exc:
    assert exc.code == 404
    payload = json.load(exc)
    assert payload["error"]["type"] == "model_not_found"

print("HEALTH          PASS")
print("MODELS          PASS")
print("STATUS          PASS")
print("MODEL GUARD     PASS")
print("SMOKE TEST      PASS")
