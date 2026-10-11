#!/usr/bin/env python3

import json
import sys
import time
import urllib.error
import urllib.request


base = sys.argv[1]


def request(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


status, info = request("GET", "/v1/runtime/cuda/status?refresh=1")
assert status == 200, info
assert info["latest"] == "cuda-fixture-r1", info
assert info["installed"] is False, info

status, accepted = request("POST", "/v1/runtime/cuda/install", {})
assert status == 202, accepted

deadline = time.time() + 20
while time.time() < deadline:
    status, info = request("GET", "/v1/runtime/cuda/status")
    assert status == 200, info
    if info["operation"]["state"] in ("success", "error"):
        break
    time.sleep(0.1)

assert info["operation"]["state"] == "success", info
assert info["current"] == "cuda-fixture-r1", info

status, preference = request(
    "POST",
    "/v1/runtime/preferences",
    {"backend_preference": "cuda"},
)
assert status == 200, preference
assert preference["backend_preference"] == "cuda", preference
assert preference["backend_changed"] is True, preference

status, backends = request("GET", "/v1/runtime/backends")
assert status == 200, backends
assert backends["preference"] == "cuda", backends
assert backends["effective_backend"] == "cuda", backends
assert backends["availability"]["cuda"]["usable"] is True, backends

status, invalid = request(
    "POST",
    "/v1/runtime/preferences",
    {"backend_preference": "metal"},
)
assert status == 400, invalid

print("CUDA STATUS API          PASS")
print("ASYNC CUDA INSTALL       PASS")
print("BACKEND PREFERENCE API   PASS")
print("CUDA AVAILABILITY PROBE  PASS")
print("INVALID BACKEND GUARD    PASS")
