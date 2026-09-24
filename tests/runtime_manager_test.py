#!/usr/bin/env python3

import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path

from runtime_manager import (
    RuntimeInstallError,
    RuntimeManager,
)


def digest(path):
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def make_runtime(base, version, marker):
    src = base / f"src-{version}"
    archive = base / f"{version}.tar.gz"

    (src / "bin").mkdir(
        parents=True
    )

    cpu = src / "bin" / "llama-server-cpu"
    vk = src / "bin" / "llama-server-vulkan"

    cpu.write_text(
        f"#!/bin/sh\necho cpu-{marker}\n"
    )
    vk.write_text(
        f"#!/bin/sh\necho vulkan-{marker}\n"
    )

    cpu.chmod(0o755)
    vk.chmod(0o755)

    with tarfile.open(
        archive,
        "w:gz",
    ) as tar:
        tar.add(
            src / "bin",
            arcname="bin",
        )

    required = [
        {
            "path": "bin/llama-server-cpu",
            "size": cpu.stat().st_size,
        },
        {
            "path": "bin/llama-server-vulkan",
            "size": vk.stat().st_size,
        },
    ]

    return {
        "version": version,
        "platform": "linux-x86_64",
        "backend": "llama.cpp",
        "archive": {
            "name": archive.name,
            "url": archive.as_uri(),
            "size": archive.stat().st_size,
            "sha256": digest(archive),
            "installed_size": sum(
                x["size"] for x in required
            ),
        },
        "required_files": required,
    }


with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    runtime_root = base / "runtime"

    r1 = make_runtime(
        base,
        "llama-test-r1",
        "one",
    )
    r2 = make_runtime(
        base,
        "llama-test-r2",
        "two",
    )

    manifest = {
        "schema_version": 1,
        "latest": "llama-test-r2",
        "runtimes": [r1, r2],
    }

    manifest_path = base / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest)
    )

    manager = RuntimeManager(runtime_root)

    manager.install(
        str(manifest_path),
        "llama-test-r1",
    )

    status = manager.status()

    assert status["current"] == "llama-test-r1"
    assert status["previous"] is None

    manager.install(
        str(manifest_path),
        "llama-test-r2",
    )

    status = manager.status()

    assert status["current"] == "llama-test-r2"
    assert status["previous"] == "llama-test-r1"

    manager.rollback()

    status = manager.status()

    assert status["current"] == "llama-test-r1"
    assert status["previous"] == "llama-test-r2"

    broken = json.loads(
        json.dumps(manifest)
    )

    broken["runtimes"][1]["archive"]["sha256"] = (
        "0" * 64
    )

    broken_path = base / "broken.json"
    broken_path.write_text(
        json.dumps(broken)
    )

    try:
        manager.install(
            str(broken_path),
            "llama-test-r2",
        )
        raise AssertionError(
            "Broken SHA unexpectedly succeeded"
        )
    except RuntimeInstallError:
        pass

    status = manager.status()

    assert status["current"] == "llama-test-r1"
    assert status["previous"] == "llama-test-r2"

print("RUNTIME INSTALL   PASS")
print("RUNTIME UPGRADE   PASS")
print("RUNTIME ROLLBACK  PASS")
print("SHA256 GUARD      PASS")
