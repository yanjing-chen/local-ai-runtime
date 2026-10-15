#!/usr/bin/env python3

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "src/local_ai_runtime.py").read_text(encoding="utf-8")
PREFERENCES = (ROOT / "src/preferences_api.py").read_text(encoding="utf-8")
RUNTIME_API = (ROOT / "src/runtime_api.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "config.example.json").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/build-cuda-runtime.yml").read_text(
    encoding="utf-8"
)
ENTRY_WORKFLOW = (ROOT / ".github/workflows/build-runtime.yml").read_text(
    encoding="utf-8"
)
DEV = (ROOT / "dev.sh").read_text(encoding="utf-8")
CUDA_MANIFEST = json.loads(
    (ROOT / "packaging/runtime/cuda-runtimes.json").read_text(
        encoding="utf-8"
    )
)

assert 'VERSION = "1.0.0-rc1"' in SERVICE
assert '"backend_preference": "auto"' in PREFERENCES
for backend in ("auto", "cuda", "vulkan", "cpu"):
    assert f'"{backend}"' in PREFERENCES
print("BACKEND PREFERENCE CONTRACT   PASS")

for route in (
    "/v1/runtime/backends",
    "/v1/runtime/cuda/status",
    "/v1/runtime/cuda/install",
    "/v1/runtime/cuda/rollback",
):
    assert route in SERVICE, route
assert "CudaRuntimeController" in SERVICE
assert "CudaRuntimeController" in RUNTIME_API
assert "cuda_runtime_root" in CONFIG
assert "cuda_runtime_manifest_url" in CONFIG
print("CUDA LIFECYCLE API            PASS")

for token in (
    'CUDA_RUNTIME_VERSION: "cuda-12.8-r3"',
    'LLAMA_CPP_REF: "828fdf282e195300c2965bd9511807e24ed53bdb"',
    'CUDA_ARCHS: "75-real;86-real;89-real;120-real;120-virtual"',
    "libcuda.so.1",
    "cuda-runtime-candidate.json",
):
    assert token in WORKFLOW, token
assert "create release" not in WORKFLOW.lower()
assert "workflow_call:" in WORKFLOW
assert "uses: ./.github/workflows/build-cuda-runtime.yml" in ENTRY_WORKFLOW
print("UNPUBLISHED CUDA CANDIDATE     PASS")

assert CUDA_MANIFEST["schema_version"] == 1
assert CUDA_MANIFEST["latest"] == "cuda-12.8-r3"
cuda_release = next(
    item
    for item in CUDA_MANIFEST["runtimes"]
    if item["version"] == "cuda-12.8-r3"
)
assert cuda_release["platform"] == "linux-x86_64"
assert cuda_release["backend"] == "cuda"
assert cuda_release["llama_cpp_ref"] == (
    "828fdf282e195300c2965bd9511807e24ed53bdb"
)
assert cuda_release["cuda_architectures"] == [
    "sm75", "sm86", "sm89", "sm120"
]
assert cuda_release["archive"]["size"] == 566681000
assert cuda_release["archive"]["sha256"] == (
    "3585432ed322c3264680d80ce04418d7d6ac209c831559e830ab0992f1eaa894"
)
assert cuda_release["archive"]["url"] == (
    "https://github.com/yanjing-chen/local-ai-runtime/releases/download/"
    "cuda-runtime-12.8-r3/"
    "Local-AI-Runtime-CUDA-cuda-12.8-r3-linux-x86_64.tar.zst"
)
required_paths = {
    item["path"] for item in cuda_release["required_files"]
}
for required in (
    "llama-server-cuda",
    "llama-server-cuda.bin",
    "lib/libcudart.so.12",
    "lib/libcublas.so.12",
    "lib/libcublasLt.so.12",
):
    assert required in required_paths, required
print("PUBLISHED CUDA MANIFEST       PASS")

for token in (
    "cuda_runtime_api_test.py",
    "backend_preference_test.py",
    "CUDA RUNTIME API      PASS",
    "BACKEND SELECTION     PASS",
):
    assert token in DEV, token
print("STAGE 7B REGRESSION GATES      PASS")

print()
print("LOCAL AI RUNTIME STAGE 7B CONTRACT: PASS")
