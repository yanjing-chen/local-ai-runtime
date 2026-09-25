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


HUNYUANOCR_15 = {
    "id": "hunyuanocr-1.5",
    "display_name": "HunyuanOCR 1.5 F16",
    "version": "1.5-f16",
    "type": "ocr",
    "source": {
        "provider": "Hugging Face",
        "repository": "tencent/HunyuanOCR",
        "revision": "47644ecc4fc854efa4f505155158831f36773ee4",
    },
    "license": {
        "name": "Tencent Hunyuan Community License Agreement",
        "url": "https://huggingface.co/tencent/HunyuanOCR/blob/47644ecc4fc854efa4f505155158831f36773ee4/LICENSE",
        "requires_acceptance": True,
    },
    "files": [
        {
            "name": "hyocr-f16.gguf",
            "role": "model",
            "generated": True,
            "min_size": 100000000,
        },
        {
            "name": "mmproj-hyocr-f16.gguf",
            "role": "mmproj",
            "generated": True,
            "min_size": 100000000,
        },
    ],
    "install": {
        "method": "hunyuanocr_hf_to_gguf",
        "converter": {
            "project": "ggml-org/llama.cpp",
            "revision": "828fdf282e195300c2965bd9511807e24ed53bdb",
            "build": "b11103",
            "outtype": "f16",
        },
        "source_files": [
            {
                "name": "LICENSE",
                "size": 16277,
                "sha256": "745adaa59575d2a98b64fd6d3452537b477a6b6edc126f742fc055313cc3d3e0",
            },
            {
                "name": "chat_template.jinja",
                "size": 994,
                "sha256": "be3371395b9e67a8f981d86543eb5a93d132a1dc3f54058a2d75b4ed1efc73fe",
            },
            {
                "name": "config.json",
                "size": 2233,
                "sha256": "14aeb192e94fbe9c3ec71fb7ed003955397be08eb4b345dd7b923549798b60ba",
            },
            {
                "name": "generation_config.json",
                "size": 139,
                "sha256": "e9f4d443b97de6cb40767d12b5fc045a5ca3fb6d2f911124fce307bfbe1ad585",
            },
            {
                "name": "model.safetensors",
                "size": 2239932512,
                "sha256": "632a1e082c4dd5a3284cf1ffcdba2fdaa06f435762c58c2f34aff0f3bd6c0249",
            },
            {
                "name": "preprocessor_config.json",
                "size": 579,
                "sha256": "e17baf5f25f542380a3a8231fefa08f359d86db1ac088feb12ecb8b06ddb01c3",
            },
            {
                "name": "special_tokens_map.json",
                "size": 836,
                "sha256": "71442c8c43669f4cedd669f1700f89a741773c49aef55783fbd533f72f050c92",
            },
            {
                "name": "tokenizer.json",
                "size": 9527297,
                "sha256": "3e2ab46bcc5ed8bce013b245c6daecf19fa1d2a18f48a9c88a1f571dcbf7dfd3",
            },
            {
                "name": "tokenizer_config.json",
                "size": 166592,
                "sha256": "804e8a7fb5a129afb19f6ad88c51c5d3c1aa643b6abb9536d10bcdcf633b4d74",
            },
            {
                "name": "video_preprocessor_config.json",
                "size": 916,
                "sha256": "f0b9fba99cdc7d556adb3a9023f961534d46c1b7c84b31c6684d8562cd866b79",
            },
        ],
    },
    "default_prompt": "OCR:",
    "capabilities": {
        "chat": False,
        "vision": True,
        "ocr": True,
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


hunyuan = json.loads(
    json.dumps(HUNYUANOCR_15)
)
hunyuan_repo = hunyuan["source"]["repository"]
hunyuan_revision = hunyuan["source"]["revision"]

for item in hunyuan["install"]["source_files"]:
    quoted = urllib.parse.quote(
        item["name"],
        safe="",
    )
    item["url"] = (
        f"https://huggingface.co/{hunyuan_repo}/resolve/"
        f"{hunyuan_revision}/{quoted}?download=true"
    )

manifest["models"].append(
    hunyuan
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
