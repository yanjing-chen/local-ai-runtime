#!/usr/bin/env python3

import threading
import time
import uuid
from pathlib import Path

from runtime_manager import (
    RuntimeManager as LlamaRuntimeManager,
    RuntimeErrorBase,
)


DEFAULT_MANIFEST_URL = (
    "https://github.com/yanjing-chen/local-ai-runtime/"
    "releases/download/runtime-manifest/llama-runtimes.json"
)


class RuntimeApiError(RuntimeError):
    def __init__(
        self,
        message,
        status_code=400,
        error_type="runtime_error",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class LlamaRuntimeController:
    def __init__(self, config):
        root = config.get(
            "llama_runtime_root",
            str(
                Path.home()
                / ".local"
                / "share"
                / "local-ai-runtime"
                / "runtime"
                / "llama"
            ),
        )

        self.manifest_url = config.get(
            "llama_runtime_manifest_url",
            DEFAULT_MANIFEST_URL,
        )

        self.manager = LlamaRuntimeManager(root)

        self.lock = threading.Lock()

        self.cached_manifest = None
        self.manifest_checked_at = None
        self.manifest_error = None

        self.operation = {
            "state": "idle",
            "action": None,
            "job_id": None,
            "version": None,
            "phase": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }

    def _operation_copy(self):
        with self.lock:
            return dict(self.operation)

    def _set_operation(self, **kwargs):
        with self.lock:
            self.operation.update(kwargs)

    def refresh_manifest(self):
        try:
            manifest = self.manager.load_manifest(
                self.manifest_url
            )

            with self.lock:
                self.cached_manifest = manifest
                self.manifest_checked_at = time.time()
                self.manifest_error = None

            return manifest

        except Exception as exc:
            with self.lock:
                self.manifest_error = str(exc)
                self.manifest_checked_at = time.time()

            raise

    def status(self, refresh=False):
        if refresh:
            try:
                self.refresh_manifest()
            except Exception:
                pass

        local = self.manager.status()

        with self.lock:
            manifest = self.cached_manifest
            manifest_error = self.manifest_error
            manifest_checked_at = self.manifest_checked_at

        latest = None

        if manifest:
            latest = manifest.get("latest")

        current = local.get("current")

        return {
            "installed": bool(current),
            "current": current,
            "previous": local.get("previous"),
            "installed_versions": local.get(
                "installed",
                [],
            ),
            "manifest_url": self.manifest_url,
            "latest": latest,
            "update_available": bool(
                current
                and latest
                and current != latest
            ),
            "install_available": bool(
                latest and not current
            ),
            "manifest_checked_at": manifest_checked_at,
            "manifest_error": manifest_error,
            "operation": self._operation_copy(),
        }

    def start_install(self, requested_version=None):
        with self.lock:
            if self.operation["state"] == "running":
                raise RuntimeApiError(
                    "A runtime operation is already running.",
                    409,
                )

            job_id = str(uuid.uuid4())

            self.operation = {
                "state": "running",
                "action": "install",
                "job_id": job_id,
                "version": requested_version or "latest",
                "phase": "checking_manifest",
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }

        thread = threading.Thread(
            target=self._install_worker,
            args=(job_id, requested_version),
            name="llama-runtime-install",
            daemon=True,
        )
        thread.start()

        return self._operation_copy()

    def _install_worker(
        self,
        job_id,
        requested_version,
    ):
        try:
            manifest = self.refresh_manifest()

            if not requested_version or requested_version == "latest":
                target = manifest.get("latest")
                version_arg = None
            else:
                target = requested_version
                version_arg = requested_version

            if not target:
                raise RuntimeApiError(
                    "Runtime manifest does not define a latest version."
                )

            self._set_operation(
                version=target,
                phase="downloading_and_installing",
            )

            self.manager.install(
                self.manifest_url,
                version_arg,
            )

            self._set_operation(
                state="success",
                phase="complete",
                error=None,
                finished_at=time.time(),
            )

        except Exception as exc:
            self._set_operation(
                state="error",
                phase="failed",
                error=str(exc),
                finished_at=time.time(),
            )

    def rollback(self):
        with self.lock:
            if self.operation["state"] == "running":
                raise RuntimeApiError(
                    "A runtime operation is already running.",
                    409,
                )

        try:
            result = self.manager.rollback()
        except RuntimeErrorBase as exc:
            raise RuntimeApiError(
                str(exc),
                409,
            ) from exc

        self._set_operation(
            state="success",
            action="rollback",
            job_id=str(uuid.uuid4()),
            version=result.get("current"),
            phase="complete",
            error=None,
            started_at=time.time(),
            finished_at=time.time(),
        )

        return self.status(refresh=False)
