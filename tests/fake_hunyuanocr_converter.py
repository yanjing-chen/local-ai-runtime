#!/usr/bin/env python3

import argparse
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--source-dir", required=True)
parser.add_argument("--model-out", required=True)
parser.add_argument("--mmproj-out", required=True)
args = parser.parse_args()

source = Path(args.source_dir)
model = Path(args.model_out)
mmproj = Path(args.mmproj_out)

required = {
    "LICENSE",
    "config.json",
    "model.safetensors",
    "tokenizer.json",
}

missing = sorted(
    name
    for name in required
    if not (source / name).is_file()
)

if missing:
    raise SystemExit(
        "missing source files: "
        + ", ".join(missing)
    )

model.parent.mkdir(parents=True, exist_ok=True)
model.write_bytes(
    b"GGUF-MODEL\n"
    + (source / "model.safetensors").read_bytes()
    + b"x" * 2048
)
mmproj.write_bytes(
    b"GGUF-MMPROJ\n"
    + (source / "config.json").read_bytes()
    + b"y" * 2048
)
