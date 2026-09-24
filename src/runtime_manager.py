#!/usr/bin/env python3

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


class RuntimeErrorBase(RuntimeError):
    pass


class RuntimeManifestError(RuntimeErrorBase):
    pass


class RuntimeInstallError(RuntimeErrorBase):
    pass


def expand(value):
    return Path(os.path.expanduser(str(value))).resolve()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json_source(source):
    if source.startswith(("http://", "https://", "file://")):
        with urllib.request.urlopen(source, timeout=30) as r:
            return json.load(r)

    with open(expand(source), "r", encoding="utf-8") as f:
        return json.load(f)


class RuntimeLock:
    def __init__(self, root):
        self.path = root / ".runtime.lock"
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.path, "a+")
        fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
        self.fd.close()


class RuntimeManager:
    def __init__(self, root):
        self.root = expand(root)
        self.downloads = self.root / "downloads"
        self.versions = self.root / "versions"
        self.current_link = self.root / "current"
        self.previous_link = self.root / "previous"

        self.downloads.mkdir(parents=True, exist_ok=True)
        self.versions.mkdir(parents=True, exist_ok=True)

    def load_manifest(self, source):
        data = read_json_source(source)

        if data.get("schema_version") != 1:
            raise RuntimeManifestError(
                "Unsupported runtime manifest schema."
            )

        runtimes = data.get("runtimes")
        if not isinstance(runtimes, list) or not runtimes:
            raise RuntimeManifestError(
                "Runtime manifest has no runtimes."
            )

        return data

    def runtime_from_manifest(self, manifest, version=None):
        target = version or manifest.get("latest")

        for runtime in manifest["runtimes"]:
            if runtime.get("version") == target:
                return runtime

        raise RuntimeManifestError(
            f"Runtime version not found: {target}"
        )

    def _read_link(self, link):
        if not link.is_symlink():
            return None

        target = os.readlink(link)
        return Path(target).name

    def _set_link(self, link, version):
        tmp = self.root / (
            f".{link.name}.new-{os.getpid()}"
        )

        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

        os.symlink(
            str(Path("versions") / version),
            tmp,
        )
        os.replace(tmp, link)

    def _remove_link(self, link):
        try:
            link.unlink()
        except FileNotFoundError:
            pass

    def status(self):
        return {
            "current": self._read_link(self.current_link),
            "previous": self._read_link(self.previous_link),
            "installed": sorted(
                p.name
                for p in self.versions.iterdir()
                if p.is_dir()
            ),
        }

    def _download(self, url, destination, expected_size=None):
        part = destination.with_suffix(
            destination.suffix + ".part"
        )

        if url.startswith("file://"):
            src = Path(
                urllib.request.url2pathname(
                    urllib.request.urlparse(url).path
                )
            )
            shutil.copyfile(src, part)
            os.replace(part, destination)
            return

        existing = part.stat().st_size if part.exists() else 0

        headers = {}
        mode = "wb"

        if existing:
            headers["Range"] = f"bytes={existing}-"
            mode = "ab"

        request = urllib.request.Request(
            url,
            headers=headers,
        )

        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:
            if existing and response.status != 206:
                existing = 0
                mode = "wb"

            with open(part, mode) as out:
                shutil.copyfileobj(response, out)

        if expected_size is not None:
            actual = part.stat().st_size
            if actual != int(expected_size):
                raise RuntimeInstallError(
                    f"Archive size mismatch: "
                    f"expected {expected_size}, got {actual}"
                )

        os.replace(part, destination)

    def _safe_tar_extract(self, archive, destination):
        destination = destination.resolve()

        with tarfile.open(archive, "r:*") as tar:
            for member in tar.getmembers():
                member_path = (
                    destination / member.name
                ).resolve()

                if destination not in (
                    member_path,
                    *member_path.parents,
                ):
                    raise RuntimeInstallError(
                        "Unsafe path in runtime archive."
                    )

            tar.extractall(destination)

    def _extract(self, archive, destination):
        name = archive.name.lower()

        if name.endswith(".tar.zst"):
            if shutil.which("tar") is None:
                raise RuntimeInstallError(
                    "tar is required for .tar.zst runtime archives."
                )

            proc = subprocess.run(
                [
                    "tar",
                    "--zstd",
                    "-xf",
                    str(archive),
                    "-C",
                    str(destination),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            if proc.returncode != 0:
                raise RuntimeInstallError(proc.stdout)
            return

        self._safe_tar_extract(
            archive,
            destination,
        )

    def _verify_required_files(self, directory, runtime):
        required = runtime.get("required_files", [])

        if not required:
            raise RuntimeManifestError(
                "Runtime has no required_files list."
            )

        total = 0

        for item in required:
            rel = item.get("path")
            if not rel:
                raise RuntimeManifestError(
                    "required_files entry has no path."
                )

            path = directory / rel

            if not path.is_file():
                raise RuntimeInstallError(
                    f"Required runtime file missing: {rel}"
                )

            actual = path.stat().st_size
            expected = item.get("size")

            if expected is not None and int(expected) != actual:
                raise RuntimeInstallError(
                    f"Runtime file size mismatch for {rel}: "
                    f"expected {expected}, got {actual}"
                )

            total += actual

        installed_size = runtime.get(
            "archive",
            {},
        ).get("installed_size")

        if (
            installed_size is not None
            and int(installed_size) != total
        ):
            raise RuntimeInstallError(
                "Installed runtime size mismatch: "
                f"expected {installed_size}, got {total}"
            )

        return total

    def verify_version(self, runtime):
        version = runtime["version"]
        directory = self.versions / version

        if not directory.is_dir():
            raise RuntimeInstallError(
                f"Runtime not installed: {version}"
            )

        self._verify_required_files(
            directory,
            runtime,
        )

        return True

    def install(self, manifest_source, version=None):
        manifest = self.load_manifest(
            manifest_source
        )
        runtime = self.runtime_from_manifest(
            manifest,
            version,
        )

        runtime_version = runtime["version"]
        archive = runtime.get("archive", {})

        name = archive.get("name")
        url = archive.get("url")
        expected_sha = archive.get("sha256")
        expected_size = archive.get("size")

        if not all((name, url, expected_sha)):
            raise RuntimeManifestError(
                "Incomplete runtime archive metadata."
            )

        destination = self.downloads / name

        with RuntimeLock(self.root):
            self._download(
                url,
                destination,
                expected_size,
            )

            actual_sha = sha256_file(
                destination
            )

            if actual_sha.lower() != expected_sha.lower():
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass

                raise RuntimeInstallError(
                    "Runtime SHA256 mismatch."
                )

            staging = Path(
                tempfile.mkdtemp(
                    prefix=".staging-",
                    dir=self.root,
                )
            )

            try:
                self._extract(
                    destination,
                    staging,
                )

                self._verify_required_files(
                    staging,
                    runtime,
                )

                final = (
                    self.versions
                    / runtime_version
                )

                if final.exists():
                    shutil.rmtree(final)

                os.replace(staging, final)

                current = self._read_link(
                    self.current_link
                )

                if (
                    current
                    and current != runtime_version
                ):
                    self._set_link(
                        self.previous_link,
                        current,
                    )

                self._set_link(
                    self.current_link,
                    runtime_version,
                )

            except Exception:
                shutil.rmtree(
                    staging,
                    ignore_errors=True,
                )
                raise

        return self.status()

    def rollback(self):
        with RuntimeLock(self.root):
            current = self._read_link(
                self.current_link
            )
            previous = self._read_link(
                self.previous_link
            )

            if not previous:
                raise RuntimeInstallError(
                    "No previous runtime is available."
                )

            if not (
                self.versions / previous
            ).is_dir():
                raise RuntimeInstallError(
                    "Previous runtime directory is missing."
                )

            self._set_link(
                self.current_link,
                previous,
            )

            if current:
                self._set_link(
                    self.previous_link,
                    current,
                )
            else:
                self._remove_link(
                    self.previous_link
                )

        return self.status()
