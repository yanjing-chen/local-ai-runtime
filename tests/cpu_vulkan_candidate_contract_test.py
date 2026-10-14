#!/usr/bin/env python3
"""1.0-B4 regression tests; synthetic files, no network or Runtime installation."""
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/build-cpu-vulkan-v1-candidate.yml'
STAGER = ROOT / 'packaging/runtime/stage_llama_candidate.py'
BASELINE = ROOT / 'packaging/runtime/llama-runtimes.json'
source = WORKFLOW.read_text(encoding='utf-8')
assert 'workflow_dispatch' in source
assert 'v1.0-stage1b-cpu-vulkan-ci' in source and 'push:' in source
assert 'release:' not in source
assert 'uses: ./.github/workflows/build-cuda-runtime.yml' not in source
assert 'd81235049384534c167caea52b85a694f6103d14' in source
assert 'runs-on: ubuntu-24.04' in source
assert '-DGGML_VULKAN=OFF' in source and '-DGGML_VULKAN=ON' in source
assert '-DLLAMA_USE_PREBUILT_UI=OFF' in source
assert 'sha256sum' in source and 'actions/upload-artifact' in source
assert 'actions/create-release' not in source
print('B4 CI WORKFLOW CONTRACT       PASS')

with tempfile.TemporaryDirectory(prefix='runtime-b4-test-') as tmp:
    tmp = Path(tmp)
    archive = tmp / 'Local-AI-Runtime-llama-d8123504-r1-linux-x86_64.tar.gz'
    data = {'bin/llama-server-cpu': b'CPU-candidate', 'bin/llama-server-vulkan': b'VULKAN-candidate'}
    with tarfile.open(archive, 'w:gz') as tar:
        for key, value in data.items():
            info = tarfile.TarInfo(name='./'+key)
            info.size = len(value)
            tar.addfile(info, io.BytesIO(value))
    metadata = {
        'schema_version': 1,
        'version': 'llama-d8123504-r1',
        'platform': 'linux-x86_64',
        'backend': 'llama.cpp',
        'llama_cpp_ref': 'd81235049384534c167caea52b85a694f6103d14',
        'archive': {
            'name': archive.name,
            'size': archive.stat().st_size,
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'installed_size': sum(map(len, data.values())),
        },
        'required_files': [{'path': k,'size':len(v)} for k,v in data.items()],
    }
    meta_path = tmp / 'metadata.json'
    meta_path.write_text(json.dumps(metadata), encoding='utf-8')
    output = tmp / 'staged.json'
    args = [sys.executable, str(STAGER), '--base', str(BASELINE), '--metadata', str(meta_path),
            '--archive', str(archive), '--url', archive.as_uri(), '--output', str(output)]
    before = hashlib.sha256(BASELINE.read_bytes()).hexdigest()
    proc = subprocess.run(args, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    staged = json.loads(output.read_text(encoding='utf-8'))
    assert staged['latest'] == metadata['version']
    assert staged['runtimes'][0]['archive']['sha256'] == metadata['archive']['sha256']
    assert staged['runtimes'][1:] == json.loads(BASELINE.read_text(encoding='utf-8'))['runtimes']
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == before
    print('B4 STAGED MANIFEST           PASS')
    # Same output as shipped base is forbidden.
    bad_args = args.copy()
    bad_args[-1] = str(BASELINE)
    result = subprocess.run(bad_args, text=True, capture_output=True)
    assert result.returncode != 0
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == before
    # Tampered metadata archive hash must be rejected.
    metadata['archive']['sha256'] = '0' * 64
    meta_path.write_text(json.dumps(metadata), encoding='utf-8')
    result = subprocess.run(args, text=True, capture_output=True)
    assert result.returncode != 0
    print('B4 NEGATIVE GUARDS           PASS')
print('LOCAL AI RUNTIME 1.0-B4: PASS')
