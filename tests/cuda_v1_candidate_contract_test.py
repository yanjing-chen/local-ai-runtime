#!/usr/bin/env python3
"""Local AI Runtime 1.0-C fast CI candidate contract. No network, no services."""
from pathlib import Path
import json
import re
r=Path(__file__).resolve().parents[1]
c=(r/'.github/workflows/build-cuda-v1-candidate.yml').read_text()
old=(r/'.github/workflows/build-cuda-runtime.yml').read_text()
manifest=(r/'packaging/runtime/cuda-runtimes.json').read_text()
assert 'v1.0-stage1c-cuda-ci' in c and 'workflow_dispatch:' in c
assert 'd81235049384534c167caea52b85a694f6103d14' in c
assert 'nvidia/cuda:12.8.1-devel-ubuntu24.04' in c
assert '75-real;86-real;89-real;120-real;120-virtual' in c
assert 'runs-on: ubuntu-24.04' in c
assert '-DGGML_CUDA=ON' in c and '-DGGML_VULKAN=OFF' in c
assert 'DLLAMA_BUILD_UI=OFF' in c and 'DLLAMA_USE_PREBUILT_UI=OFF' in c
assert 'libcuda.so.1' in c and 'ldd-after-bundle' in c
assert 'sha256sum' in c and 'upload-artifact@v4' in c
assert 'contents: read' in c and 'create-release' not in c and 'gh release' not in c
assert 'build-cuda-runtime.yml' not in c
assert 'cuda-d8123504-r1' in c
assert 'lib/libcublasLt.so.12' in c
m=json.loads(manifest)
assert m['latest']=='cuda-12.8-r3'
assert all(x['version']!='cuda-d8123504-r1' for x in m['runtimes'])
assert '828fdf282e195300c2965bd9511807e24ed53bdb' in old
print('CUDA_V1_CANDIDATE_CONTRACT=PASS')
print('LEGACY_CUDA_WORKFLOW=UNCHANGED')
print('PUBLISHED_CUDA_MANIFEST=UNCHANGED')
