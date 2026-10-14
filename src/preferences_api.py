#!/usr/bin/env python3

import json
import os
import tempfile
import threading

from pathlib import Path


class RuntimePreferenceError(RuntimeError):
    def __init__(
        self,
        message,
        status_code=400,
        error_type="runtime_preference_error",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


def expand(value):
    return Path(
        os.path.expanduser(str(value))
    ).resolve()


class RuntimePreferences:
    """Persistent user choices that must survive Runtime upgrades.

    Preferences live outside config.json so install-user.sh can continue to
    treat that file as an administrator/user-managed launch configuration.
    """

    def __init__(self, config):
        self.path = expand(
            config.get(
                "preferences_file",
                "~/.config/local-ai-runtime/preferences.json",
            )
        )
        self.lock = threading.RLock()
        # Keep the existing launch configuration as the default for users
        # who have not explicitly set a persistent idle preference.
        self.default_idle_unload_seconds = self.validate_idle_timeout(
            config.get("idle_unload_seconds", 600),
            stored=True,
        )

    @staticmethod
    def validate_idle_timeout(value, stored=False):
        # bool is a subclass of int; accepting True/False would make a
        # settings UI mistake silently turn into a one-second timeout.
        if type(value) is not int or not 0 <= value <= 86400:
            raise RuntimePreferenceError(
                "idle_unload_seconds must be an integer from 0 to 86400 "
                "(0 disables automatic unloading).",
                500 if stored else 400,
                "runtime_preference_store_error" if stored
                else "invalid_request_error",
            )
        return value

    @staticmethod
    def _empty():
        return {
            "schema_version": 1,
            "preload_model": "",
            "backend_preference": "auto",
        }

    def _load_unlocked(self):
        if not self.path.exists():
            return self._empty()

        try:
            data = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            raise RuntimePreferenceError(
                "Cannot read Runtime preferences: "
                f"{exc}",
                500,
                "runtime_preference_store_error",
            ) from exc

        if not isinstance(data, dict):
            raise RuntimePreferenceError(
                "Runtime preferences must be a JSON object.",
                500,
                "runtime_preference_store_error",
            )

        if data.get("schema_version") != 1:
            raise RuntimePreferenceError(
                "Unsupported Runtime preference schema.",
                500,
                "runtime_preference_store_error",
            )

        preload_model = data.get(
            "preload_model",
            "",
        )
        if not isinstance(preload_model, str):
            raise RuntimePreferenceError(
                "preload_model must be a string.",
                500,
                "runtime_preference_store_error",
            )

        data["preload_model"] = (
            preload_model.strip()
        )

        backend_preference = data.get(
            "backend_preference",
            "auto",
        )
        if backend_preference not in (
            "auto",
            "cuda",
            "vulkan",
            "cpu",
        ):
            raise RuntimePreferenceError(
                "backend_preference must be auto, cuda, vulkan or cpu.",
                500,
                "runtime_preference_store_error",
            )

        data["backend_preference"] = backend_preference
        if "idle_unload_seconds" in data:
            data["idle_unload_seconds"] = self.validate_idle_timeout(
                data["idle_unload_seconds"], stored=True,
            )
        return data

    def _write_unlocked(self, data):
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        descriptor, temporary = tempfile.mkstemp(
            prefix=".preferences-",
            suffix=".json.tmp",
            dir=self.path.parent,
        )

        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    data,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.chmod(
                temporary,
                0o600,
            )
            os.replace(
                temporary,
                self.path,
            )

        finally:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass

    def status(self):
        with self.lock:
            data = self._load_unlocked()

        model_id = data["preload_model"]
        return {
            "preload_enabled": bool(model_id),
            "preload_model": model_id,
            "backend_preference": data["backend_preference"],
            "idle_unload_seconds": data.get(
                "idle_unload_seconds", self.default_idle_unload_seconds
            ),
        }

    def set_preload_model(self, model_id):
        if not isinstance(model_id, str):
            raise RuntimePreferenceError(
                "preload_model must be a string.",
                400,
                "invalid_request_error",
            )

        model_id = model_id.strip()

        if len(model_id) > 128:
            raise RuntimePreferenceError(
                "preload_model is too long.",
                400,
                "invalid_request_error",
            )

        with self.lock:
            data = self._load_unlocked()
            data["preload_model"] = model_id
            self._write_unlocked(data)

        return self.status()

    def set_backend_preference(self, backend):
        if not isinstance(backend, str):
            raise RuntimePreferenceError(
                "backend_preference must be a string.",
                400,
                "invalid_request_error",
            )

        backend = backend.strip().lower()
        if backend not in (
            "auto",
            "cuda",
            "vulkan",
            "cpu",
        ):
            raise RuntimePreferenceError(
                "backend_preference must be auto, cuda, vulkan or cpu.",
                400,
                "invalid_request_error",
            )

        with self.lock:
            data = self._load_unlocked()
            data["backend_preference"] = backend
            self._write_unlocked(data)

        return self.status()

    def set_idle_unload_seconds(self, seconds):
        seconds = self.validate_idle_timeout(seconds)
        with self.lock:
            data = self._load_unlocked()
            data["idle_unload_seconds"] = seconds
            self._write_unlocked(data)
        return self.status()
