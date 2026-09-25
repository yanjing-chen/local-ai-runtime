#!/usr/bin/env python3

import json
import sys
import time
import urllib.request


base = sys.argv[1]

request = urllib.request.Request(
    base + "/v1/chat/completions",
    data=json.dumps(
        {
            "model": "model-b",
            "messages": [
                {
                    "role": "user",
                    "content": "stream test",
                }
            ],
            "stream": True,
        }
    ).encode(),
    method="POST",
    headers={
        "Content-Type": "application/json",
    },
)

started = time.monotonic()
events = []

with urllib.request.urlopen(
    request,
    timeout=10,
) as response:
    assert response.status == 200
    assert (
        response.headers
        .get_content_type()
        == "text/event-stream"
    )
    assert (
        response.headers.get(
            "X-Accel-Buffering"
        )
        == "no"
    )
    assert (
        response.headers.get(
            "Content-Length"
        )
        is None
    )

    while True:
        line = response.readline()

        if not line:
            break

        if not line.startswith(
            b"data: "
        ):
            continue

        elapsed = (
            time.monotonic()
            - started
        )
        data = line[
            len(b"data: "):
        ].strip()

        events.append(
            (
                elapsed,
                data,
            )
        )

        if data == b"[DONE]":
            break

assert len(events) == 3, events

first_elapsed = events[0][0]
done_elapsed = events[-1][0]

assert first_elapsed < 0.75, events
assert done_elapsed >= 1.75, events

first = json.loads(
    events[0][1]
)
second = json.loads(
    events[1][1]
)

assert (
    first["choices"][0]
    ["delta"]["content"]
    == "first"
)
assert (
    second["choices"][0]
    ["delta"]["content"]
    == "second"
)

print(
    "SSE FIRST CHUNK     PASS "
    f"({first_elapsed:.3f}s)"
)
print(
    "SSE COMPLETE        PASS "
    f"({done_elapsed:.3f}s)"
)
print("STREAMING PROXY      PASS")
