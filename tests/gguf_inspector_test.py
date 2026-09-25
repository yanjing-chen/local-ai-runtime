#!/usr/bin/env python3

import json
import shutil
import struct
import sys
import urllib.error
import urllib.request

from pathlib import Path


base = sys.argv[1]
fixture = Path(sys.argv[2]).resolve()

if fixture.exists():
    shutil.rmtree(fixture)

fixture.mkdir(
    parents=True,
    exist_ok=True,
)


def packed_string(value):
    data = str(value).encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def packed_value(value):
    if isinstance(value, bool):
        return 7, struct.pack("<B", int(value))

    if isinstance(value, int):
        return 10, struct.pack("<Q", value)

    if isinstance(value, str):
        return 8, packed_string(value)

    if isinstance(value, list):
        body = struct.pack("<IQ", 8, len(value))

        for item in value:
            body += packed_string(item)

        return 9, body

    raise TypeError(value)


def write_gguf(path, metadata):
    body = b"GGUF"
    body += struct.pack(
        "<IQQ",
        3,
        0,
        len(metadata),
    )

    for key, value in metadata.items():
        value_type, encoded = packed_value(value)
        body += packed_string(key)
        body += struct.pack("<I", value_type)
        body += encoded

    path.write_bytes(body)


def request(path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        method="POST",
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


hy_model = fixture / "Hy-MT2-7B-Q4_K_M.gguf"
paddle_model = (
    fixture
    / "PaddleOCR-VL-1.6-GGUF.gguf"
)
paddle_mmproj = (
    fixture
    / "mmproj-PaddleOCR-VL-1.6-F16.gguf"
)

write_gguf(
    hy_model,
    {
        "general.name": "HY-MT2-7B",
        "general.architecture": "llama",
        "general.languages": ["zh", "en"],
        "llama.context_length": 32768,
        "tokenizer.chat_template": "{{ messages }}",
        "tokenizer.ggml.tokens": [
            "one",
            "two",
            "three",
        ],
    },
)

write_gguf(
    paddle_model,
    {
        "general.name": "PaddleOCR-VL 1.6",
        "general.architecture": "ernie4_5",
        "general.description": "Vision OCR model",
        "ernie4_5.context_length": 131072,
    },
)

write_gguf(
    paddle_mmproj,
    {
        "general.name": "PaddleOCR-VL 1.6 projector",
        "general.architecture": "clip",
        "clip.has_vision_encoder": True,
        "clip.has_text_encoder": False,
        "clip.projector_type": "paddleocr",
    },
)

initial_sizes = {
    path: path.stat().st_size
    for path in (
        hy_model,
        paddle_model,
        paddle_mmproj,
    )
}

status, hy = request(
    "/v1/models/inspect",
    {
        "model_path": str(hy_model),
        "auto_match_mmproj": True,
    },
)

assert status == 200, hy
assert hy["object"] == "gguf.inspection"
assert hy["architecture"] == "llama"
assert hy["native_context_size"] == 32768
assert hy["has_chat_template"] is True
assert hy["mmproj"]["path"] == ""
assert hy["suggested"]["id"] == "hy-mt2-7b"
assert hy["suggested"]["type"] == "translation"
assert hy["suggested"]["context_size"] == 4096
assert hy["suggested"]["capabilities"]["translation"] is True
assert hy["suggested"]["capabilities"]["vision"] is False

status, paddle = request(
    "/v1/models/inspect",
    {
        "model_path": str(paddle_model),
    },
)

assert status == 200, paddle
assert paddle["native_context_size"] == 131072
assert paddle["mmproj"]["path"] == str(paddle_mmproj)
assert paddle["mmproj"]["auto_matched"] is True
assert paddle["mmproj"]["confidence"] == "high"
assert paddle["suggested"]["type"] == "ocr"
assert paddle["suggested"]["mmproj_path"] == str(
    paddle_mmproj
)
assert paddle["suggested"]["default_prompt"] == "OCR:"
assert paddle["suggested"]["capabilities"]["ocr"] is True
assert paddle["suggested"]["capabilities"]["vision"] is True
assert paddle["suggested"]["capabilities"]["chat"] is False

second_mmproj = (
    fixture
    / "mmproj-PaddleOCR-VL-1.6-copy-F16.gguf"
)
write_gguf(
    second_mmproj,
    {
        "general.name": "PaddleOCR-VL 1.6 projector copy",
        "general.architecture": "clip",
        "clip.has_vision_encoder": True,
        "clip.projector_type": "paddleocr",
    },
)

status, ambiguous = request(
    "/v1/models/inspect",
    {
        "model_path": str(paddle_model),
    },
)

assert status == 200, ambiguous
assert ambiguous["mmproj"]["path"] == ""
assert ambiguous["mmproj"]["auto_matched"] is False
assert len(ambiguous["mmproj"]["candidates"]) == 2
assert any(
    "manually" in warning
    for warning in ambiguous["warnings"]
)

status, explicit = request(
    "/v1/models/inspect",
    {
        "model_path": str(paddle_model),
        "mmproj_path": str(paddle_mmproj),
    },
)

assert status == 200, explicit
assert explicit["mmproj"]["path"] == str(
    paddle_mmproj
)
assert explicit["mmproj"]["confidence"] == "explicit"
assert explicit["mmproj"]["auto_matched"] is False

status, same_file = request(
    "/v1/models/inspect",
    {
        "model_path": str(paddle_model),
        "mmproj_path": str(paddle_model),
    },
)

assert status == 400, same_file

status, no_discovery = request(
    "/v1/models/inspect",
    {
        "model_path": str(paddle_model),
        "auto_match_mmproj": False,
    },
)

assert status == 200, no_discovery
assert no_discovery["mmproj"]["path"] == ""
assert no_discovery["mmproj"]["candidates"] == []

invalid = fixture / "invalid.gguf"
invalid.write_bytes(b"not a gguf")

status, error = request(
    "/v1/models/inspect",
    {
        "model_path": str(invalid),
    },
)

assert status == 400, error
assert error["error"]["type"] == "gguf_inspection_error"

status, error = request(
    "/v1/models/inspect",
    {
        "model_path": "relative.gguf",
    },
)

assert status == 400, error

status, error = request(
    "/v1/models/inspect",
    {
        "model_path": str(hy_model),
        "auto_match_mmproj": "yes",
    },
)

assert status == 400, error

for path, size in initial_sizes.items():
    assert path.is_file()
    assert path.stat().st_size == size

print("GGUF HEADER PARSER     PASS")
print("METADATA SUGGESTIONS  PASS")
print("CHAT TEMPLATE         PASS")
print("CONTEXT SUGGESTION    PASS")
print("MMProj AUTO MATCH     PASS")
print("MMProj AMBIGUITY      PASS")
print("MANUAL OVERRIDE       PASS")
print("EXTERNAL FILES KEPT   PASS")
print("GGUF INSPECTION API   PASS")
