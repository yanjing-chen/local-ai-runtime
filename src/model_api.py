#!/usr/bin/env python3

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ModelApiError(RuntimeError):
    def __init__(
        self,
        message,
        status_code=400,
        error_type="model_error",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


def expand(value):
    return Path(
        os.path.expanduser(str(value))
    ).resolve()


def sha256_file(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


class ModelController:
    def __init__(self, config):
        self.root = expand(
            config.get(
                "model_root",
                "~/.local/share/local-ai-runtime/models",
            )
        )

        self.manifest_url = str(
            config.get(
                "model_manifest_url",
                "",
            )
        ).strip()

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.downloads = (
            self.root
            / ".downloads"
        )

        self.downloads.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.lock = threading.RLock()

        self.manifest = None
        self.manifest_error = None
        self.manifest_checked_at = None

        self.operations = {}

    def _read_json_source(self, source):
        if source.startswith(
            (
                "http://",
                "https://",
                "file://",
            )
        ):
            with urllib.request.urlopen(
                source,
                timeout=30,
            ) as response:
                return json.load(response)

        with open(
            expand(source),
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    def refresh_manifest(self):
        if not self.manifest_url:
            with self.lock:
                self.manifest = {
                    "schema_version": 1,
                    "models": [],
                }
                self.manifest_error = None
                self.manifest_checked_at = time.time()

            return self.manifest

        try:
            data = self._read_json_source(
                self.manifest_url
            )

            if data.get("schema_version") != 1:
                raise ModelApiError(
                    "Unsupported model manifest schema."
                )

            models = data.get(
                "models"
            )

            if not isinstance(
                models,
                list,
            ):
                raise ModelApiError(
                    "Model manifest has no models array."
                )

            seen = set()

            for model in models:
                model_id = str(
                    model.get(
                        "id",
                        "",
                    )
                ).strip()

                if not model_id:
                    raise ModelApiError(
                        "Model entry has no id."
                    )

                if model_id in seen:
                    raise ModelApiError(
                        f"Duplicate model id: {model_id}"
                    )

                seen.add(
                    model_id
                )

            with self.lock:
                self.manifest = data
                self.manifest_error = None
                self.manifest_checked_at = time.time()

            return data

        except Exception as exc:
            with self.lock:
                self.manifest_error = str(exc)
                self.manifest_checked_at = time.time()

            raise

    def _ensure_manifest(self):
        with self.lock:
            manifest = self.manifest

        if manifest is None:
            return self.refresh_manifest()

        return manifest

    def _model_entry(self, model_id):
        manifest = self._ensure_manifest()

        for model in manifest.get(
            "models",
            [],
        ):
            if model.get("id") == model_id:
                return model

        raise ModelApiError(
            f"Unknown model: {model_id}",
            404,
            "model_not_found",
        )

    def _model_directory(self, model):
        return (
            self.root
            / model["id"]
            / str(
                model.get(
                    "version",
                    "default",
                )
            )
        )

    def _file_target(
        self,
        directory,
        item,
    ):
        name = str(
            item.get(
                "name",
                "",
            )
        ).strip()

        if (
            not name
            or Path(name).name != name
        ):
            raise ModelApiError(
                f"Unsafe model filename: {name}"
            )

        return directory / name

    def is_installed(self, model):
        directory = self._model_directory(
            model
        )

        if not directory.is_dir():
            return False

        try:
            for item in model.get(
                "files",
                [],
            ):
                target = self._file_target(
                    directory,
                    item,
                )

                if not target.is_file():
                    return False

                expected_size = item.get(
                    "size"
                )

                if (
                    expected_size is not None
                    and target.stat().st_size
                    != int(expected_size)
                ):
                    return False

            return bool(
                model.get(
                    "files",
                    []
                )
            )

        except Exception:
            return False

    def _download(
        self,
        url,
        destination,
        expected_size=None,
    ):
        part = Path(
            str(destination)
            + ".part"
        )

        parsed = urllib.parse.urlparse(
            url
        )

        if parsed.scheme == "file":
            source = Path(
                urllib.request.url2pathname(
                    parsed.path
                )
            )

            shutil.copyfile(
                source,
                part,
            )

        else:
            existing = (
                part.stat().st_size
                if part.exists()
                else 0
            )

            headers = {}
            mode = "wb"

            if existing:
                headers["Range"] = (
                    f"bytes={existing}-"
                )
                mode = "ab"

            request = urllib.request.Request(
                url,
                headers=headers,
            )

            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                if (
                    existing
                    and response.status != 206
                ):
                    mode = "wb"

                with open(
                    part,
                    mode,
                ) as out:
                    shutil.copyfileobj(
                        response,
                        out,
                    )

        if expected_size is not None:
            actual = (
                part.stat().st_size
            )

            if (
                actual
                != int(expected_size)
            ):
                raise ModelApiError(
                    "Model file size mismatch: "
                    f"expected {expected_size}, "
                    f"got {actual}"
                )

        os.replace(
            part,
            destination,
        )

    def install(
        self,
        model_id,
    ):
        model = self._model_entry(
            model_id
        )

        files = model.get(
            "files",
            [],
        )

        if not files:
            raise ModelApiError(
                f"Model has no files: {model_id}"
            )

        final = self._model_directory(
            model
        )

        staging = Path(
            tempfile.mkdtemp(
                prefix=(
                    f".{model_id}-staging-"
                ),
                dir=self.root,
            )
        )

        try:
            for item in files:
                name = item.get(
                    "name"
                )

                url = item.get(
                    "url"
                )

                expected_sha = str(
                    item.get(
                        "sha256",
                        "",
                    )
                ).lower()

                if (
                    not name
                    or not url
                    or not expected_sha
                ):
                    raise ModelApiError(
                        "Incomplete model file metadata."
                    )

                target = self._file_target(
                    staging,
                    item,
                )

                self._download(
                    url,
                    target,
                    item.get(
                        "size"
                    ),
                )

                actual_sha = sha256_file(
                    target
                )

                if (
                    actual_sha.lower()
                    != expected_sha
                ):
                    raise ModelApiError(
                        "Model SHA256 mismatch "
                        f"for {name}"
                    )

            metadata = {
                "id": model["id"],
                "version": model.get(
                    "version"
                ),
                "installed_at": time.time(),
            }

            (
                staging
                / ".installed.json"
            ).write_text(
                json.dumps(
                    metadata,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            final.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if final.exists():
                shutil.rmtree(
                    final
                )

            os.replace(
                staging,
                final,
            )

        except Exception:
            shutil.rmtree(
                staging,
                ignore_errors=True,
            )
            raise

        return self.model_status(
            model_id
        )

    def uninstall(
        self,
        model_id,
    ):
        model = self._model_entry(
            model_id
        )

        directory = (
            self._model_directory(
                model
            )
        )

        if directory.exists():
            shutil.rmtree(
                directory
            )

        parent = directory.parent

        try:
            parent.rmdir()
        except OSError:
            pass

        return self.model_status(
            model_id
        )

    def model_status(
        self,
        model_id,
    ):
        model = self._model_entry(
            model_id
        )

        operation = (
            self.operations.get(
                model_id,
                {
                    "state": "idle",
                    "action": None,
                    "job_id": None,
                    "error": None,
                },
            )
        )

        return {
            "id": model["id"],
            "display_name": model.get(
                "display_name",
                model["id"],
            ),
            "version": model.get(
                "version"
            ),
            "type": model.get(
                "type",
                "unknown",
            ),
            "installed": self.is_installed(
                model
            ),
            "capabilities": model.get(
                "capabilities",
                {},
            ),
            "operation": dict(
                operation
            ),
        }

    def list_status(
        self,
        refresh=False,
    ):
        if refresh:
            try:
                self.refresh_manifest()
            except Exception:
                pass

        manifest = self._ensure_manifest()

        data = []

        for model in manifest.get(
            "models",
            [],
        ):
            data.append(
                self.model_status(
                    model["id"]
                )
            )

        return {
            "object": "list",
            "data": data,
            "manifest_url": self.manifest_url,
            "manifest_error": self.manifest_error,
            "manifest_checked_at":
            self.manifest_checked_at,
        }

    def start_install(
        self,
        model_id,
    ):
        self._model_entry(
            model_id
        )

        with self.lock:
            existing = self.operations.get(
                model_id
            )

            if (
                existing
                and existing.get("state")
                == "running"
            ):
                raise ModelApiError(
                    "A model operation is already running.",
                    409,
                    "operation_in_progress",
                )

            job_id = str(
                uuid.uuid4()
            )

            self.operations[model_id] = {
                "state": "running",
                "action": "install",
                "job_id": job_id,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }

        thread = threading.Thread(
            target=self._install_worker,
            args=(
                model_id,
            ),
            name=(
                "model-install-"
                + model_id
            ),
            daemon=True,
        )

        thread.start()

        return dict(
            self.operations[
                model_id
            ]
        )

    def _install_worker(
        self,
        model_id,
    ):
        try:
            self.install(
                model_id
            )

            with self.lock:
                self.operations[
                    model_id
                ].update(
                    {
                        "state": "success",
                        "error": None,
                        "finished_at":
                        time.time(),
                    }
                )

        except Exception as exc:
            with self.lock:
                self.operations[
                    model_id
                ].update(
                    {
                        "state": "error",
                        "error": str(exc),
                        "finished_at":
                        time.time(),
                    }
                )

    def runtime_profile(
        self,
        model_id,
    ):
        model = self._model_entry(
            model_id
        )

        if not self.is_installed(
            model
        ):
            raise ModelApiError(
                f"Model is not installed: {model_id}",
                409,
                "model_not_installed",
            )

        directory = (
            self._model_directory(
                model
            )
        )

        model_path = None
        mmproj_path = None

        for item in model.get(
            "files",
            [],
        ):
            role = item.get(
                "role",
                "model",
            )

            target = self._file_target(
                directory,
                item,
            )

            if role == "model":
                model_path = str(
                    target
                )

            elif role == "mmproj":
                mmproj_path = str(
                    target
                )

        if not model_path:
            raise ModelApiError(
                f"Model file role is missing: {model_id}"
            )

        inference = model.get(
            "inference",
            {},
        )

        return {
            "id": model_id,
            "model_path": model_path,
            "mmproj_path": (
                mmproj_path
                or ""
            ),
            "extra_args": list(
                inference.get(
                    "extra_args",
                    [],
                )
            ),
            "default_prompt": model.get(
                "default_prompt",
                "",
            ),
            "capabilities": model.get(
                "capabilities",
                {},
            ),
        }
