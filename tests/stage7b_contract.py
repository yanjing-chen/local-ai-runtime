#!/usr/bin/env python3

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

assert 'VERSION = "0.8.0"' in SERVICE
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
