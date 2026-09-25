#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path


base = sys.argv[1]
fixture = Path(sys.argv[2]).resolve()
registry = Path(sys.argv[3]).resolve()

fixture.mkdir(
    parents=True,
    exist_ok=True,
)

model_path = fixture / "custom-chat.gguf"
mmproj_path = fixture / "custom-mmproj.gguf"

model_path.write_bytes(b"custom model fixture\n")
mmproj_path.write_bytes(b"custom mmproj fixture\n")


def request(method, path, payload=None):
    data = None

    if payload is not None:
        data = json.dumps(payload).encode()

    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=15,
        ) as response:
            return response.status, json.load(response)

    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


payload = {
    "id": "custom-chat",
    "display_name": "Custom Chat Fixture",
    "type": "vision",
    "model_path": str(model_path),
    "mmproj_path": str(mmproj_path),
    "context_size": 8192,
    "gpu_layers": 17,
    "default_prompt": "Describe:",
    "capabilities": {
        "chat": True,
        "vision": True,
        "ocr": False,
        "translation": False,
        "streaming": True,
        "thinking": False,
        "temperature": True,
        "custom_prompt": True,
        "context_size": True,
    },
}

status, created = request(
    "POST",
    "/v1/models/custom",
    payload,
)

assert status == 201, created
assert created["id"] == "custom-chat"
assert created["source"] == "custom"
assert created["editable"] is True
assert created["installed"] is True
assert created["context_size"] == 8192
assert created["gpu_layers"] == 17
assert created["capabilities"]["vision"] is True

status, custom = request(
    "GET",
    "/v1/models/custom",
)

assert status == 200
assert [item["id"] for item in custom["data"]] == [
    "custom-chat"
]

status, models = request(
    "GET",
    "/v1/models",
)

ids = {item["id"] for item in models["data"]}
assert "custom-chat" in ids
assert "model-a" in ids
assert "model-b" in ids

status, collision = request(
    "POST",
    "/v1/models/custom",
    {
        **payload,
        "id": "model-a",
    },
)

assert status == 409, collision
assert collision["error"]["type"] == "model_id_conflict"

status, invalid = request(
    "POST",
    "/v1/models/custom",
    {
        **payload,
        "id": "Bad Model Id",
    },
)

assert status == 400, invalid

status, external = request(
    "POST",
    "/v1/models/install",
    {
        "model": "custom-chat",
    },
)

assert status == 409, external
assert external["error"]["type"] == "custom_model_external"

status, chat = request(
    "POST",
    "/v1/chat/completions",
    {
        "model": "custom-chat",
        "messages": [
            {
                "role": "user",
                "content": "hello",
            }
        ],
    },
)

assert status == 200, chat
content = chat["choices"][0]["message"]["content"]
assert "served:custom-chat.gguf" in content

_, runtime = request(
    "GET",
    "/v1/runtime/status",
)

assert runtime["current_model"] == "custom-chat"
first_pid = runtime["backend_pid"]
assert first_pid

command = Path(
    f"/proc/{first_pid}/cmdline"
).read_bytes().split(b"\0")

assert b"-c" in command
assert b"8192" in command
assert b"-ngl" in command
assert b"17" in command
assert b"--mmproj" in command
assert str(mmproj_path).encode() in command

status, invalid_update = request(
    "POST",
    "/v1/models/custom",
    {
        **payload,
        "model_path": "relative.gguf",
    },
)

assert status == 400, invalid_update

_, still_running = request(
    "GET",
    "/v1/runtime/status",
)

assert still_running["current_model"] == "custom-chat"
assert still_running["backend_pid"] == first_pid
assert still_running["backend_running"] is True

status, updated = request(
    "POST",
    "/v1/models/custom",
    {
        **payload,
        "context_size": 4096,
        "gpu_layers": 9,
    },
)

assert status == 200, updated
assert updated["context_size"] == 4096
assert updated["gpu_layers"] == 9

_, stopped = request(
    "GET",
    "/v1/runtime/status",
)

assert stopped["current_model"] is None
assert stopped["backend_running"] is False

try:
    os.kill(first_pid, 0)
except ProcessLookupError:
    pass
else:
    raise AssertionError("old custom model process still exists")

status, chat = request(
    "POST",
    "/v1/chat/completions",
    {
        "model": "custom-chat",
        "messages": [
            {
                "role": "user",
                "content": "hello again",
            }
        ],
    },
)

assert status == 200, chat

_, runtime = request(
    "GET",
    "/v1/runtime/status",
)

second_pid = runtime["backend_pid"]
assert second_pid and second_pid != first_pid

command = Path(
    f"/proc/{second_pid}/cmdline"
).read_bytes().split(b"\0")

assert b"4096" in command
assert b"9" in command

status, catalog_chat = request(
    "POST",
    "/v1/chat/completions",
    {
        "model": "model-a",
        "messages": [
            {
                "role": "user",
                "content": "switch to catalog",
            }
        ],
    },
)

assert status == 200, catalog_chat

_, catalog_runtime = request(
    "GET",
    "/v1/runtime/status",
)

catalog_pid = catalog_runtime["backend_pid"]
assert catalog_runtime["current_model"] == "model-a"
assert catalog_pid and catalog_pid != second_pid

try:
    os.kill(second_pid, 0)
except ProcessLookupError:
    pass
else:
    raise AssertionError("custom process survived catalog switch")

status, chat = request(
    "POST",
    "/v1/chat/completions",
    {
        "model": "custom-chat",
        "messages": [
            {
                "role": "user",
                "content": "switch back to custom",
            }
        ],
    },
)

assert status == 200, chat

_, runtime = request(
    "GET",
    "/v1/runtime/status",
)

third_pid = runtime["backend_pid"]
assert runtime["current_model"] == "custom-chat"
assert third_pid and third_pid != catalog_pid

status, removed = request(
    "POST",
    "/v1/models/custom/remove",
    {
        "model": "custom-chat",
    },
)

assert status == 200, removed
assert removed["deleted"] is True
assert removed["files_removed"] is False
assert model_path.is_file()
assert mmproj_path.is_file()

_, runtime = request(
    "GET",
    "/v1/runtime/status",
)

assert runtime["current_model"] is None
assert runtime["backend_running"] is False

registry_data = json.loads(
    registry.read_text(
        encoding="utf-8"
    )
)

assert registry_data == {
    "schema_version": 1,
    "models": [],
}
assert registry.stat().st_mode & 0o777 == 0o600

print("CUSTOM REGISTER       PASS")
print("CUSTOM UPDATE         PASS")
print("CUSTOM REMOVE         PASS")
print("EXTERNAL FILES KEPT   PASS")
print("CONTEXT SIZE          PASS")
print("GPU LAYERS            PASS")
print("MMPROJ                PASS")
print("CAPABILITIES          PASS")
print("ACTIVE MODEL UNLOAD   PASS")
print("INVALID UPDATE GUARD   PASS")
print("CUSTOM/CATALOG SWITCH  PASS")
print("CUSTOM MODEL API      PASS")
