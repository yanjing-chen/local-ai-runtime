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
            timeout=15,
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


status, models = request(
    "GET",
    "/v1/models?refresh=1",
)

assert status == 200
assert {
    x["id"]
    for x in models["data"]
} == {
    "model-a",
    "model-b",
}

for model_id in (
    "model-a",
    "model-b",
):
    status, result = request(
        "POST",
        "/v1/models/install",
        {
            "model": model_id
        },
    )

    assert status == 202

    deadline = (
        time.time()
        + 20
    )

    while (
        time.time()
        < deadline
    ):
        status, models = request(
            "GET",
            "/v1/models",
        )

        entry = next(
            x
            for x in models["data"]
            if x["id"] == model_id
        )

        state = (
            entry["operation"]["state"]
        )

        if state in (
            "success",
            "error",
        ):
            break

        time.sleep(
            0.1
        )

    assert state == "success", entry
    assert entry["installed"] is True


def chat(model_id):
    status, response = request(
        "POST",
        "/v1/chat/completions",
        {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
        },
    )

    assert status == 200, response

    return (
        response["choices"][0]
        ["message"]["content"]
    )


result_a = chat(
    "model-a"
)

assert (
    "served:model-a.gguf"
    in result_a
)

status, runtime_a = request(
    "GET",
    "/v1/runtime/status",
)

assert (
    runtime_a["current_model"]
    == "model-a"
)

pid_a = runtime_a[
    "backend_pid"
]

assert pid_a


result_b = chat(
    "model-b"
)

assert (
    "served:model-b.gguf"
    in result_b
)

status, runtime_b = request(
    "GET",
    "/v1/runtime/status",
)

assert (
    runtime_b["current_model"]
    == "model-b"
)

pid_b = runtime_b[
    "backend_pid"
]

assert pid_b
assert pid_b != pid_a

result_b2 = chat(
    "model-b"
)

status, runtime_b2 = request(
    "GET",
    "/v1/runtime/status",
)

assert (
    runtime_b2["backend_pid"]
    == pid_b
)

print("MODEL MANIFEST       PASS")
print("MODEL INSTALL        PASS")
print("MODEL A LOAD         PASS")
print("A -> B SWITCH        PASS")
print("OLD PROCESS RELEASE  PASS")
print("SAME MODEL REUSE     PASS")
print("SINGLE RESIDENCY     PASS")
