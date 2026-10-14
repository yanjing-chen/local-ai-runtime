#!/usr/bin/env python3
"""Prepare a candidate manifest, never modify the shipped release manifest.

This is a staged, explicit action after ubuntu-24.04 CI produces its artifact.
The candidate archive and metadata are verified, and old entries are preserved.
The staged output is not published or installed by this tool.
"""

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path

PINNED_REF = 'd81235049384534c167caea52b85a694f6103d14'
PINNED_VERSION = 'llama-d8123504-r1'
NEEDED = ('bin/llama-server-cpu', 'bin/llama-server-vulkan')


def check_and_stage(base_file, metadata_file, archive_file, url, output_file):
    base_file, metadata_file, archive_file, output_file = (
        Path(p).expanduser().resolve() for p in
        (base_file, metadata_file, archive_file, output_file)
    )
    if base_file == output_file:
        raise ValueError('Cannot overwrite the published base manifest')
    if not url.startswith(('https://', 'file://')):
        raise ValueError('URL must be HTTPS or explicit local file:// URL')
    old = json.loads(base_file.read_text(encoding='utf-8'))
    meta = json.loads(metadata_file.read_text(encoding='utf-8'))
    if old.get('schema_version') != 1 or not isinstance(old.get('runtimes'), list):
        raise ValueError('Invalid baseline llama manifest')
    if meta.get('schema_version') != 1 or meta.get('version') != PINNED_VERSION:
        raise ValueError('Unexpected candidate version')
    if meta.get('llama_cpp_ref') != PINNED_REF:
        raise ValueError('Unexpected llama.cpp commit')
    if meta.get('platform') != 'linux-x86_64' or meta.get('backend') != 'llama.cpp':
        raise ValueError('Unexpected candidate platform or backend')
    details = meta['archive']
    if archive_file.name != details.get('name') or not archive_file.is_file():
        raise ValueError('Archive filename mismatch or missing archive')
    if archive_file.stat().st_size != details.get('size'):
        raise ValueError('Candidate archive byte size mismatch')
    checksum = hashlib.sha256()
    with archive_file.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            checksum.update(block)
    if checksum.hexdigest() != details.get('sha256'):
        raise ValueError('Candidate archive SHA256 mismatch')
    sizes = {item['path']: item['size'] for item in meta['required_files']}
    if set(sizes) != set(NEEDED) or any(type(sizes[n]) is not int or sizes[n] <= 0 for n in NEEDED):
        raise ValueError('Unexpected required files or invalid sizes')
    if details.get('installed_size') != sum(sizes.values()):
        raise ValueError('Installed size mismatch')
    with tarfile.open(archive_file, 'r:gz') as tar:
        members = {}
        for member in tar.getmembers():
            name = member.name.removeprefix('./')
            if name.startswith('/') or '..' in name.split('/') or member.issym() or member.islnk():
                raise ValueError('Unsafe candidate archive member')
            if name in members:
                raise ValueError('Duplicate archive member')
            members[name] = member
        for name in NEEDED:
            member = members.get(name)
            if member is None or not member.isfile() or member.size != sizes[name]:
                raise ValueError(f'Required file missing or wrong size: {name}')

    if any(r.get('version') == PINNED_VERSION for r in old['runtimes']):
        raise ValueError('Candidate version already exists in base manifest')
    candidate = dict(meta)
    candidate['display_version'] = 'llama.cpp v0.6.0 / d8123504 (CPU/Vulkan)'
    candidate['archive'] = {**details, 'url': url}
    staged = dict(old)
    staged['latest'] = PINNED_VERSION
    staged['runtimes'] = [candidate, *old['runtimes']]
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(staged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('STAGED_MANIFEST=PASS')
    print(f'STAGED_PATH={output_file}')
    print(f'PINNED_VERSION={PINNED_VERSION}')
    print('BASE_MANIFEST=UNTOUCHED')
    print('PUBLISHED_RELEASE=NOT_CREATED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        check_and_stage(args.base, args.metadata, args.archive, args.url, args.output)
    except (ValueError, OSError, KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f'STAGED_MANIFEST=FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
