#!/usr/bin/env bash
set -euo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )/../.." &&
    pwd
)"

OUT="${1:-$ROOT/dist}"

VERSION="$(
    sed -n \
        's/^VERSION = "\([^"]*\)"/\1/p' \
        "$ROOT/src/local_ai_runtime.py" \
        | head -n 1
)"

if [[ -z "$VERSION" ]]; then
    echo "Cannot determine version."
    exit 1
fi

NAME="Local-AI-Runtime-${VERSION}-linux-x86_64"
STAGING="$OUT/.staging-$NAME"

rm -rf "$STAGING"

mkdir -p \
    "$STAGING/$NAME/src" \
    "$OUT"

cp -a \
    "$ROOT/src/local_ai_runtime.py" \
    "$ROOT/src/runtime_manager.py" \
    "$ROOT/src/runtime_api.py" \
    "$ROOT/src/model_api.py" \
    "$ROOT/src/runtimectl.py" \
    "$STAGING/$NAME/src/"

cp -a \
    "$ROOT/config.example.json" \
    "$ROOT/install-user.sh" \
    "$ROOT/uninstall-user.sh" \
    "$ROOT/README.md" \
    "$ROOT/ROADMAP.md" \
    "$STAGING/$NAME/"

ARCHIVE="$OUT/$NAME.tar.gz"

rm -f \
    "$ARCHIVE" \
    "$ARCHIVE.sha256sum" \
    "$OUT/app-metadata.json"

tar \
    -C "$STAGING" \
    -czf "$ARCHIVE" \
    "$NAME"

(
    cd "$OUT"

    sha256sum \
        "$(basename "$ARCHIVE")" \
        > "$(basename "$ARCHIVE").sha256sum"
)

python3 - \
    "$VERSION" \
    "$ARCHIVE" \
    "$OUT/app-metadata.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path


version = sys.argv[1]
archive = Path(sys.argv[2])
output = Path(sys.argv[3])

h = hashlib.sha256()

with archive.open("rb") as f:
    for block in iter(
        lambda: f.read(
            1024 * 1024
        ),
        b"",
    ):
        h.update(block)

metadata = {
    "schema_version": 1,
    "version": version,
    "platform": "linux-x86_64",
    "archive": {
        "name": archive.name,
        "size": archive.stat().st_size,
        "sha256": h.hexdigest(),
    },
    "installer": {
        "path": "install-user.sh",
        "arguments": [
            "--start"
        ],
        "requires_root": False,
    },
}

output.write_text(
    json.dumps(
        metadata,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

print(
    json.dumps(
        metadata,
        indent=2,
    )
)
PY

rm -rf "$STAGING"

echo
echo "$ARCHIVE"
