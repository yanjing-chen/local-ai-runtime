#!/usr/bin/env python3

import hashlib
import json
import sys
from pathlib import Path


root = Path(
    sys.argv[1]
).resolve()

root.mkdir(
    parents=True,
    exist_ok=True,
)


def sha(path):
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


models = []

for model_id in (
    "model-a",
    "model-b",
):
    source = (
        root
        / f"{model_id}.gguf"
    )

    source.write_bytes(
        (
            f"fixture-{model_id}\n"
        ).encode()
    )

    models.append(
        {
            "id": model_id,
            "display_name": (
                "Fixture "
                + model_id
            ),
            "version": "1",
            "type": "text",
            "files": [
                {
                    "role": "model",
                    "name": source.name,
                    "url": source.as_uri(),
                    "size":
                    source.stat().st_size,
                    "sha256":
                    sha(source),
                }
            ],
            "default_prompt": "",
            "capabilities": {
                "custom_prompt": True,
                "streaming": True,
                "thinking": False,
                "temperature": True,
                "context_size": True,
            },
            "inference": {
                "extra_args": []
            },
        }
    )

manifest = {
    "schema_version": 1,
    "models": models,
}

path = (
    root
    / "models.json"
)

path.write_text(
    json.dumps(
        manifest,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

print(
    path
)
