#!/usr/bin/env python3

import hashlib
import json
import sys
import tarfile
from pathlib import Path


root = Path(
    sys.argv[1]
).resolve()

root.mkdir(
    parents=True,
    exist_ok=True,
)

src = root / "fixture-src"

(src / "bin").mkdir(
    parents=True,
    exist_ok=True,
)

cpu = (
    src
    / "bin"
    / "llama-server-cpu"
)

vk = (
    src
    / "bin"
    / "llama-server-vulkan"
)

cpu.write_text(
    "#!/bin/sh\necho fixture-cpu\n"
)

vk.write_text(
    "#!/bin/sh\necho fixture-vulkan\n"
)

cpu.chmod(
    0o755
)

vk.chmod(
    0o755
)

archive = (
    root
    / "fixture-runtime.tar.gz"
)

with tarfile.open(
    archive,
    "w:gz",
) as tar:
    tar.add(
        src / "bin",
        arcname="bin",
    )

h = hashlib.sha256()

with archive.open(
    "rb"
) as f:
    for block in iter(
        lambda: f.read(
            1024 * 1024
        ),
        b"",
    ):
        h.update(
            block
        )

required = [
    {
        "path":
        "bin/llama-server-cpu",
        "size":
        cpu.stat().st_size,
    },
    {
        "path":
        "bin/llama-server-vulkan",
        "size":
        vk.stat().st_size,
    },
]

manifest = {
    "schema_version": 1,
    "latest": "fixture-r1",
    "runtimes": [
        {
            "version":
            "fixture-r1",
            "display_version":
            "Fixture r1",
            "platform":
            "linux-x86_64",
            "backend":
            "llama.cpp",
            "archive": {
                "name":
                archive.name,
                "url":
                archive.as_uri(),
                "size":
                archive.stat().st_size,
                "sha256":
                h.hexdigest(),
                "installed_size":
                sum(
                    x["size"]
                    for x in required
                ),
            },
            "required_files":
            required,
        }
    ],
}

manifest_path = (
    root
    / "runtime-manifest.json"
)

manifest_path.write_text(
    json.dumps(
        manifest,
        indent=2,
    )
)

print(
    manifest_path
)
