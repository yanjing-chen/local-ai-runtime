#!/usr/bin/env python3

import json
import sys
import time
import urllib.error
import urllib.request


base = sys.argv[1]


def request(
    method,
    path,
    payload=None,
):
    data = None

    if payload is not None:
        data = json.dumps(
            payload
        ).encode()

    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Content-Type":
            "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=5,
        ) as r:
            return (
                r.status,
                json.load(r),
            )

    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            json.load(exc),
        )


status, info = request(
    "GET",
    "/v1/runtime/llama/status?refresh=1",
)

assert status == 200
assert info["current"] is None
assert info["latest"] == "fixture-r1"
assert info["install_available"] is True

status, accepted = request(
    "POST",
    "/v1/runtime/llama/install",
    {},
)

assert status == 202
assert accepted["accepted"] is True

deadline = time.time() + 20

while time.time() < deadline:
    status, info = request(
        "GET",
        "/v1/runtime/llama/status",
    )

    assert status == 200

    state = (
        info["operation"]["state"]
    )

    if state in (
        "success",
        "error",
    ):
        break

    time.sleep(
        0.1
    )

assert (
    info["operation"]["state"]
    == "success"
), info

assert info["current"] == "fixture-r1"
assert info["installed"] is True
assert info["install_available"] is False
assert info["update_available"] is False

status, rollback = request(
    "POST",
    "/v1/runtime/llama/rollback",
    {},
)

assert status == 409

print("RUNTIME STATUS API   PASS")
print("ASYNC INSTALL API    PASS")
print("INSTALL POLLING      PASS")
print("RUNTIME ACTIVATE     PASS")
print("ROLLBACK GUARD       PASS")
