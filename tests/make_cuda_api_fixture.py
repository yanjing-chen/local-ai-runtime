#!/usr/bin/env python3

import hashlib
import json
import sys
import tarfile
from pathlib import Path


root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
source = root / "fixture-src"
source.mkdir(parents=True, exist_ok=True)

cuda = source / "llama-server-cuda"
cuda.write_text(
    "#!/bin/sh\n"
    "if [ \"$1\" = \"--list-devices\" ]; then\n"
    "  echo 'CUDA0: Fixture NVIDIA GPU'\n"
    "fi\n",
    encoding="utf-8",
)
cuda.chmod(0o755)

archive = root / "fixture-cuda-runtime.tar.gz"
with tarfile.open(archive, "w:gz") as tar:
    tar.add(cuda, arcname="llama-server-cuda")

digest = hashlib.sha256(archive.read_bytes()).hexdigest()
manifest = {
    "schema_version": 1,
    "latest": "cuda-fixture-r1",
    "runtimes": [
        {
            "version": "cuda-fixture-r1",
            "display_version": "CUDA fixture r1",
            "platform": "linux-x86_64",
            "backend": "cuda",
            "archive": {
                "name": archive.name,
                "url": archive.as_uri(),
                "size": archive.stat().st_size,
                "sha256": digest,
                "installed_size": cuda.stat().st_size,
            },
            "required_files": [
                {
                    "path": "llama-server-cuda",
                    "size": cuda.stat().st_size,
                }
            ],
        }
    ],
}

manifest_path = root / "cuda-runtime-manifest.json"
manifest_path.write_text(
    json.dumps(manifest, indent=2) + "\n",
    encoding="utf-8",
)
print(manifest_path)
