#!/usr/bin/env python3

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


OUTPUT = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "packaging/models/models.json"
)


MODELS = [
    {
        "id": "paddleocr-vl-1.6",
        "display_name": "PaddleOCR-VL 1.6",
        "version": "1.6",
        "type": "ocr",
        "repo": "PaddlePaddle/PaddleOCR-VL-1.6-GGUF",
        "files": [
            {
                "role": "model",
                "filename": "PaddleOCR-VL-1.6-GGUF.gguf",
            },
            {
                "role": "mmproj",
                "filename": "PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
            },
        ],
        "default_prompt": "OCR:",
        "capabilities": {
            "chat": False,
            "vision": True,
            "ocr": True,
            "translation": False,
            "custom_prompt": True,
            "streaming": True,
            "thinking": False,
            "temperature": True,
            "context_size": True,
        },
        "inference": {
            "extra_args": [
                "-c",
                "4096",
                "-ngl",
                "99",
            ]
        },
    },
    {
        "id": "hy-mt2-7b",
        "display_name": "Hy-MT2 7B Q4_K_M",
        "version": "Q4_K_M",
        "type": "translation",
        "repo": "tencent/Hy-MT2-7B-GGUF",
        "files": [
            {
                "role": "model",
                "filename": "Hy-MT2-7B-Q4_K_M.gguf",
            },
        ],
        "default_prompt": "",
        "capabilities": {
            "chat": True,
            "vision": False,
            "ocr": False,
            "translation": True,
            "custom_prompt": True,
            "streaming": True,
            "thinking": False,
            "temperature": True,
            "context_size": True,
        },
        "inference": {
            "extra_args": [
                "-c",
                "4096",
                "-ngl",
                "99",
            ]
        },
    },
]


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "local-ai-runtime-manifest-builder/1.0"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        return json.load(response)


def repo_metadata(repo):
    encoded = urllib.parse.quote(
        repo,
        safe="/",
    )

    url = (
        "https://huggingface.co/api/models/"
        + encoded
        + "?blobs=true"
    )

    data = get_json(url)

    revision = data.get(
        "sha"
    )

    if not revision:
        raise RuntimeError(
            f"No repository revision returned for {repo}"
        )

    siblings = {}

    for item in data.get(
        "siblings",
        [],
    ):
        filename = item.get(
            "rfilename"
        )

        if filename:
            siblings[
                filename
            ] = item

    return (
        revision,
        siblings,
    )


def file_metadata(
    repo,
    revision,
    siblings,
    filename,
):
    item = siblings.get(
        filename
    )

    if item is None:
        raise RuntimeError(
            f"{filename} not found in {repo}"
        )

    lfs = item.get(
        "lfs"
    ) or {}

    sha256 = (
        lfs.get("sha256")
        or lfs.get("oid")
    )

    size = (
        lfs.get("size")
        or item.get("size")
    )

    if (
        not sha256
        or not size
    ):
        raise RuntimeError(
            "Missing verified LFS metadata for "
            f"{repo}/{filename}\n"
            f"Metadata: {json.dumps(item, indent=2)}"
        )

    if sha256.startswith(
        "sha256:"
    ):
        sha256 = sha256.split(
            ":",
            1,
        )[1]

    quoted_filename = urllib.parse.quote(
        filename,
        safe="",
    )

    url = (
        f"https://huggingface.co/{repo}/resolve/"
        f"{revision}/{quoted_filename}?download=true"
    )

    return {
        "name": filename,
        "url": url,
        "size": int(size),
        "sha256": sha256,
    }


manifest = {
    "schema_version": 1,
    "models": [],
}

for specification in MODELS:
    repo = specification[
        "repo"
    ]

    revision, siblings = (
        repo_metadata(
            repo
        )
    )

    files = []

    for requested in specification[
        "files"
    ]:
        metadata = file_metadata(
            repo,
            revision,
            siblings,
            requested[
                "filename"
            ],
        )

        metadata[
            "role"
        ] = requested[
            "role"
        ]

        files.append(
            metadata
        )

    entry = {
        "id":
        specification["id"],

        "display_name":
        specification[
            "display_name"
        ],

        "version":
        specification[
            "version"
        ],

        "type":
        specification[
            "type"
        ],

        "source": {
            "provider":
            "Hugging Face",

            "repository":
            repo,

            "revision":
            revision,
        },

        "files":
        files,

        "default_prompt":
        specification[
            "default_prompt"
        ],

        "capabilities":
        specification[
            "capabilities"
        ],

        "inference":
        specification[
            "inference"
        ],
    }

    manifest[
        "models"
    ].append(
        entry
    )


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.write_text(
    json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

print(
    OUTPUT.read_text(
        encoding="utf-8"
    )
)
