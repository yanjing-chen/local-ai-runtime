#!/usr/bin/env python3

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from model_api import ModelApiError, ModelController


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with tempfile.TemporaryDirectory(
    prefix="local-ai-runtime-hunyuan-test-"
) as temporary:
    root = Path(temporary)
    source = root / "source"
    source.mkdir()

    payloads = {
        "LICENSE": b"test license\n",
        "config.json": b'{"model_type":"hunyuan_vl"}\n',
        "model.safetensors": b"fake safetensors payload\n",
        "tokenizer.json": b'{"version":"1.0"}\n',
    }

    source_files = []

    for name, payload in payloads.items():
        path = source / name
        path.write_bytes(payload)
        source_files.append(
            {
                "name": name,
                "url": path.as_uri(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
        )

    manifest = root / "models.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": [
                    {
                        "id": "hunyuanocr-1.5",
                        "display_name": "HunyuanOCR 1.5 F16",
                        "version": "1.5-f16",
                        "type": "ocr",
                        "license": {
                            "name": "Test license",
                            "url": "https://example.invalid/license",
                            "requires_acceptance": True,
                        },
                        "files": [
                            {
                                "name": "hyocr-f16.gguf",
                                "role": "model",
                                "generated": True,
                                "min_size": 1024,
                            },
                            {
                                "name": "mmproj-hyocr-f16.gguf",
                                "role": "mmproj",
                                "generated": True,
                                "min_size": 1024,
                            },
                        ],
                        "install": {
                            "method": "hunyuanocr_hf_to_gguf",
                            "source_files": source_files,
                        },
                        "default_prompt": "OCR:",
                        "capabilities": {
                            "vision": True,
                            "ocr": True,
                            "streaming": True,
                        },
                        "inference": {
                            "extra_args": [
                                "-c",
                                "10240",
                                "-ngl",
                                "99",
                                "--n-predict",
                                "4096",
                                "-fa",
                                "on",
                                "--jinja",
                            ]
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    controller = ModelController(
        {
            "model_root": str(root / "models"),
            "model_manifest_url": manifest.as_uri(),
            "custom_model_registry": str(root / "custom.json"),
            "model_install_log_root": str(root / "logs"),
            "hunyuanocr_converter_command": [
                sys.executable,
                str(ROOT / "tests" / "fake_hunyuanocr_converter.py"),
            ],
        }
    )

    status = controller.model_status("hunyuanocr-1.5")
    assert status["installed"] is False, status
    assert status["install_method"] == "hunyuanocr_hf_to_gguf", status
    assert status["license"]["requires_acceptance"] is True, status
    assert status["download_size"] == sum(len(value) for value in payloads.values()), status

    try:
        controller.start_install("hunyuanocr-1.5")
    except ModelApiError as exc:
        assert exc.status_code == 409, exc.status_code
        assert exc.error_type == "license_acceptance_required", exc.error_type
    else:
        raise AssertionError("license gate did not reject an unaccepted install")

    operation = controller.start_install(
        "hunyuanocr-1.5",
        accept_license=True,
    )
    assert operation["state"] == "running", operation
    assert operation["phase"] == "queued", operation

    deadline = time.monotonic() + 20

    while time.monotonic() < deadline:
        status = controller.model_status("hunyuanocr-1.5")
        state = status["operation"]["state"]

        if state != "running":
            break

        time.sleep(0.05)

    assert state == "success", status
    assert status["operation"]["phase"] == "complete", status
    assert status["installed"] is True, status

    profile = controller.runtime_profile("hunyuanocr-1.5")
    assert profile["model_path"].endswith("/hyocr-f16.gguf"), profile
    assert profile["mmproj_path"].endswith("/mmproj-hyocr-f16.gguf"), profile
    assert profile["extra_args"][-3:] == ["-fa", "on", "--jinja"], profile

    final = root / "models" / "hunyuanocr-1.5" / "1.5-f16"
    metadata = json.loads(
        (final / ".installed.json").read_text(encoding="utf-8")
    )
    assert metadata["license_accepted"] is True, metadata
    assert metadata["install_method"] == "hunyuanocr_hf_to_gguf", metadata
    assert set(metadata["generated_files"]) == {
        "hyocr-f16.gguf",
        "mmproj-hyocr-f16.gguf",
    }, metadata
    assert (final / "LICENSE").read_bytes() == payloads["LICENSE"]
    assert not (root / "models" / ".downloads" / "hunyuanocr-1.5").exists()

    before = {
        name: sha256(source / name)
        for name in payloads
    }
    controller.uninstall("hunyuanocr-1.5")
    after = {
        name: sha256(source / name)
        for name in payloads
    }
    assert before == after
    assert not final.exists()

print("HUNYUANOCR LICENSE GATE   PASS")
print("HUNYUANOCR RECIPE INSTALL PASS")
print("HUNYUANOCR ATOMIC OUTPUT  PASS")
print("HUNYUANOCR SOURCE CLEANUP PASS")
print("HUNYUANOCR UNINSTALL      PASS")
