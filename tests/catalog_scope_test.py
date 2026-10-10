#!/usr/bin/env python3

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
manifest_path = ROOT / "packaging" / "models" / "models.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

expected_ids = {
    "paddleocr-vl-1.6",
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
assert '"$ROOT/src/preferences_api.py"' in installer
assert "systemctl --user enable \\\n" in installer
assert "systemctl --user restart \\\n" in installer
assert "enable --now" not in installer
assert "hunyuanocr_converter_root" not in installer
assert "model.safetensors" not in installer

runtime_source = (ROOT / "src" / "local_ai_runtime.py").read_text(
    encoding="utf-8"
)
model_api = (ROOT / "src" / "model_api.py").read_text(encoding="utf-8")
assert 'path\n                == "/v1/models/remove"' in runtime_source
assert "Custom model removal only unregisters external files." in model_api
assert "MODEL_ID_PATTERN.fullmatch(model_id)" in model_api
assert "Unsafe managed model directory." in model_api

assert not (ROOT / "src" / "hunyuanocr_installer.py").exists()
assert not (ROOT / "tests" / "hunyuanocr_recipe_test.py").exists()
assert not (ROOT / "tests" / "fake_hunyuanocr_converter.py").exists()

bundle = (ROOT / "packaging/app/build-user-bundle.sh").read_text(
    encoding="utf-8"
)
assert '"$ROOT/src/preferences_api.py"' in bundle

print("SUPPORTED CATALOG SCOPE PASS")
print("HUNYUANOCR PAYLOAD      NONE")
