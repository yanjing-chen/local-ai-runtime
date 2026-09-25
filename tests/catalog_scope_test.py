#!/usr/bin/env python3

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
manifest_path = ROOT / "packaging" / "models" / "models.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

expected_ids = {
    "paddleocr-vl-1.6",
    "hy-mt2-7b",
}
actual_ids = {
    str(model.get("id", ""))
    for model in manifest.get("models", [])
}

assert manifest.get("schema_version") == 1, manifest
assert actual_ids == expected_ids, actual_ids

for model in manifest["models"]:
    method = model.get("install", {}).get("method", "direct")
    assert method == "direct", model

for relative in (
    "src",
    "packaging/models",
    "packaging/runtime",
    "tools/build_models_manifest.py",
    "config.example.json",
    "packaging/app/build-user-bundle.sh",
):
    target = ROOT / relative
    paths = (
        target.rglob("*")
        if target.is_dir()
        else (target,)
    )

    for path in paths:
        if not path.is_file() or "__pycache__" in path.parts:
            continue

        text = path.read_text(encoding="utf-8", errors="ignore").lower()

        assert "hunyuan" not in text, path

installer = (ROOT / "install-user.sh").read_text(encoding="utf-8")
assert 'rm -f "$LIB_DIR/hunyuanocr_installer.py"' in installer
assert "hunyuanocr_converter_root" not in installer
assert "model.safetensors" not in installer

assert not (ROOT / "src" / "hunyuanocr_installer.py").exists()
assert not (ROOT / "tests" / "hunyuanocr_recipe_test.py").exists()
assert not (ROOT / "tests" / "fake_hunyuanocr_converter.py").exists()

print("SUPPORTED CATALOG SCOPE PASS")
print("HUNYUANOCR PAYLOAD      NONE")
