#!/usr/bin/env python3

import json
import os
import re
import tempfile
import threading

from pathlib import Path


MODEL_ID_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,63}$"
)

MODEL_TYPES = {
    "chat",
    "translation",
    "ocr",
    "vision",
    "other",
}

CAPABILITY_KEYS = {
    "chat",
    "vision",
    "ocr",
    "translation",
    "streaming",
    "thinking",
    "temperature",
    "custom_prompt",
    "context_size",
}


class CustomModelError(RuntimeError):
    def __init__(
        self,
        message,
        status_code=400,
        error_type="custom_model_error",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


def expand(value):
    return Path(
        os.path.expanduser(str(value))
    ).resolve()


class CustomModelStore:
    def __init__(self, config):
        self.path = expand(
            config.get(
                "custom_model_registry",
                "~/.config/local-ai-runtime/custom-models.json",
            )
        )
        self.lock = threading.RLock()

    def _empty(self):
        return {
            "schema_version": 1,
            "models": [],
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
            raise CustomModelError(
                "Cannot read custom model registry: "
                f"{exc}",
                500,
                "custom_registry_error",
            ) from exc

        if data.get("schema_version") != 1:
            raise CustomModelError(
                "Unsupported custom model registry schema.",
                500,
                "custom_registry_error",
            )

        models = data.get("models")

        if not isinstance(models, list):
            raise CustomModelError(
                "Custom model registry has no models array.",
                500,
                "custom_registry_error",
            )

        return data

    def _write_unlocked(self, data):
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        descriptor, temporary = tempfile.mkstemp(
            prefix=".custom-models-",
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

    def list(self):
        with self.lock:
            data = self._load_unlocked()
            return [
                dict(item)
                for item in data["models"]
            ]

    def get(self, model_id):
        for item in self.list():
            if item.get("id") == model_id:
                return item

        raise CustomModelError(
            f"Unknown custom model: {model_id}",
            404,
            "model_not_found",
        )

    def _path(
        self,
        value,
        label,
        required,
    ):
        text = str(value or "").strip()

        if not text:
            if required:
                raise CustomModelError(
                    f"{label} is required."
                )
            return ""

        supplied = Path(
            os.path.expanduser(text)
        )

        if not supplied.is_absolute():
            raise CustomModelError(
                f"{label} must be an absolute path."
            )

        path = supplied.resolve()

        if not path.is_file():
            raise CustomModelError(
                f"{label} does not exist: {path}"
            )

        if path.suffix.lower() != ".gguf":
            raise CustomModelError(
                f"{label} must be a GGUF file."
            )

        return str(path)

    def normalize(self, payload):
        if not isinstance(payload, dict):
            raise CustomModelError(
                "Custom model payload must be an object."
            )

        model_id = str(
            payload.get("id", "")
        ).strip()

        if not MODEL_ID_PATTERN.fullmatch(model_id):
            raise CustomModelError(
                "Model id must use 1-64 lowercase letters, "
                "digits, dots, underscores or hyphens."
            )

        display_name = str(
            payload.get(
                "display_name",
                model_id,
            )
        ).strip()

        if (
            not display_name
            or len(display_name) > 128
        ):
            raise CustomModelError(
                "Display name must contain 1-128 characters."
            )

        model_type = str(
            payload.get(
                "type",
                "chat",
            )
        ).strip().lower()

        if model_type not in MODEL_TYPES:
            raise CustomModelError(
                "Unsupported model type: "
                f"{model_type}"
            )

        try:
            context_size = int(
                payload.get(
                    "context_size",
                    4096,
                )
            )
            gpu_layers = int(
                payload.get(
                    "gpu_layers",
                    99,
                )
            )

        except (TypeError, ValueError) as exc:
            raise CustomModelError(
                "Context size and GPU layers must be integers."
            ) from exc

        if not 512 <= context_size <= 1048576:
            raise CustomModelError(
                "Context size must be between 512 and 1048576."
            )

        if not 0 <= gpu_layers <= 999:
            raise CustomModelError(
                "GPU layers must be between 0 and 999."
            )

        raw_capabilities = payload.get(
            "capabilities",
            {},
        )

        if not isinstance(
            raw_capabilities,
            dict,
        ):
            raise CustomModelError(
                "Capabilities must be an object."
            )

        unknown = (
            set(raw_capabilities)
            - CAPABILITY_KEYS
        )

        if unknown:
            raise CustomModelError(
                "Unknown capabilities: "
                + ", ".join(
                    sorted(unknown)
                )
            )

        mmproj_path = self._path(
            payload.get("mmproj_path"),
            "MMProj path",
            False,
        )

        capabilities = {
            "chat": True,
            "vision": bool(mmproj_path),
            "ocr": model_type == "ocr",
            "translation": (
                model_type == "translation"
            ),
            "streaming": True,
            "thinking": False,
            "temperature": True,
            "custom_prompt": True,
            "context_size": True,
        }

        for key, value in raw_capabilities.items():
            if not isinstance(value, bool):
                raise CustomModelError(
                    f"Capability {key} must be boolean."
                )
            capabilities[key] = value

        default_prompt = str(
            payload.get(
                "default_prompt",
                "",
            )
        )

        if len(default_prompt) > 8192:
            raise CustomModelError(
                "Default prompt is too long."
            )

        return {
            "id": model_id,
            "display_name": display_name,
            "type": model_type,
            "model_path": self._path(
                payload.get("model_path"),
                "Model path",
                True,
            ),
            "mmproj_path": mmproj_path,
            "context_size": context_size,
            "gpu_layers": gpu_layers,
            "default_prompt": default_prompt,
            "capabilities": capabilities,
        }

    def upsert(
        self,
        payload,
        reserved_ids,
    ):
        entry = self.normalize(
            payload
        )

        if entry["id"] in reserved_ids:
            raise CustomModelError(
                "A catalog model already uses this id.",
                409,
                "model_id_conflict",
            )

        with self.lock:
            data = self._load_unlocked()
            existing = None
            kept = []

            for item in data["models"]:
                if item.get("id") == entry["id"]:
                    existing = item
                else:
                    kept.append(item)

            data["models"] = [
                *kept,
                entry,
            ]
            self._write_unlocked(data)

        return entry, existing is None

    def remove(self, model_id):
        with self.lock:
            data = self._load_unlocked()
            removed = None
            kept = []

            for item in data["models"]:
                if item.get("id") == model_id:
                    removed = item
                else:
                    kept.append(item)

            if removed is None:
                raise CustomModelError(
                    f"Unknown custom model: {model_id}",
                    404,
                    "model_not_found",
                )

            data["models"] = kept
            self._write_unlocked(data)

        return removed

    @staticmethod
    def as_model(entry):
        return {
            "id": entry["id"],
            "display_name": entry["display_name"],
            "version": "custom",
            "type": entry["type"],
            "source_kind": "custom",
            "model_path": entry["model_path"],
            "mmproj_path": entry["mmproj_path"],
            "context_size": entry["context_size"],
            "gpu_layers": entry["gpu_layers"],
            "default_prompt": entry["default_prompt"],
            "capabilities": dict(
                entry["capabilities"]
            ),
            "inference": {
                "extra_args": [
                    "-c",
                    str(entry["context_size"]),
                    "-ngl",
                    str(entry["gpu_layers"]),
                ]
            },
        }
