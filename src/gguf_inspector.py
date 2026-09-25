#!/usr/bin/env python3

import os
import re
import struct

from pathlib import Path


MAX_METADATA_ITEMS = 1_000_000
MAX_ARRAY_ITEMS = 5_000_000
MAX_STRING_BYTES = 16 * 1024 * 1024
MAX_RETURN_STRING = 4096
MAX_MM_PROJ_CANDIDATES = 64

VALUE_FORMATS = {
    0: "B",
    1: "b",
    2: "H",
    3: "h",
    4: "I",
    5: "i",
    6: "f",
    7: "B",
    10: "Q",
    11: "q",
    12: "d",
}

PUBLIC_METADATA_KEYS = {
    "general.name",
    "general.architecture",
    "general.basename",
    "general.finetune",
    "general.version",
    "general.size_label",
    "general.file_type",
    "general.languages",
    "general.license",
    "general.description",
    "clip.projector_type",
    "clip.has_text_encoder",
    "clip.has_vision_encoder",
    "clip.has_audio_encoder",
}

QUANTIZATION_SUFFIX = re.compile(
    r"(?:[-_.](?:q\d(?:_[a-z0-9]+)*|iq\d(?:_[a-z0-9]+)*|"
    r"f16|f32|bf16|fp16|fp32|gguf))+$",
    re.IGNORECASE,
)

TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

IGNORED_MATCH_TOKENS = {
    "gguf",
    "model",
    "mmproj",
    "projector",
    "q2",
    "q3",
    "q4",
    "q5",
    "q6",
    "q8",
    "km",
    "ks",
    "kl",
    "f16",
    "f32",
    "bf16",
    "fp16",
    "fp32",
}

OCR_MARKERS = {
    "ocr",
    "paddleocr",
    "dotsocr",
    "deepseekocr",
    "glmocr",
}

TRANSLATION_MARKERS = {
    "translation",
    "translate",
    "translator",
    "hymt",
    "nllb",
    "madlad",
    "opusmt",
}


class GgufInspectionError(RuntimeError):
    def __init__(
        self,
        message,
        status_code=400,
        error_type="gguf_inspection_error",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


def _expand_gguf_path(value, label):
    text = str(value or "").strip()

    if not text:
        raise GgufInspectionError(
            f"{label} is required."
        )

    supplied = Path(
        os.path.expanduser(text)
    )

    if not supplied.is_absolute():
        raise GgufInspectionError(
            f"{label} must be an absolute path."
        )

    path = supplied.resolve()

    if not path.is_file():
        raise GgufInspectionError(
            f"{label} does not exist: {path}"
        )

    if path.suffix.lower() != ".gguf":
        raise GgufInspectionError(
            f"{label} must be a GGUF file."
        )

    return path


class _Reader:
    def __init__(self, path):
        self.path = path
        self.size = path.stat().st_size
        self.handle = path.open("rb")

    def close(self):
        self.handle.close()

    def read(self, count):
        if count < 0:
            raise GgufInspectionError(
                "Invalid GGUF byte count."
            )

        data = self.handle.read(count)

        if len(data) != count:
            raise GgufInspectionError(
                "GGUF file is truncated."
            )

        return data

    def unpack(self, fmt):
        size = struct.calcsize("<" + fmt)
        return struct.unpack(
            "<" + fmt,
            self.read(size),
        )[0]

    def skip(self, count):
        target = self.handle.tell() + count

        if count < 0 or target > self.size:
            raise GgufInspectionError(
                "GGUF file is truncated."
            )

        self.handle.seek(count, os.SEEK_CUR)

    def string(self, keep=True):
        length = self.unpack("Q")

        if length > MAX_STRING_BYTES:
            raise GgufInspectionError(
                "GGUF metadata string is too large."
            )

        if not keep:
            self.skip(length)
            return None

        raw = self.read(length)

        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GgufInspectionError(
                "GGUF metadata contains invalid UTF-8."
            ) from exc

        if len(value) > MAX_RETURN_STRING:
            return value[:MAX_RETURN_STRING]

        return value

    def value(self, value_type, keep, depth=0):
        if depth > 8:
            raise GgufInspectionError(
                "GGUF metadata arrays are nested too deeply."
            )

        if value_type in VALUE_FORMATS:
            value = self.unpack(
                VALUE_FORMATS[value_type]
            )

            if value_type == 7:
                if value not in (0, 1):
                    raise GgufInspectionError(
                        "GGUF metadata contains an invalid boolean."
                    )
                value = bool(value)

            return value if keep else None

        if value_type == 8:
            return self.string(keep=keep)

        if value_type != 9:
            raise GgufInspectionError(
                f"Unsupported GGUF metadata value type: {value_type}"
            )

        item_type = self.unpack("I")
        length = self.unpack("Q")

        if length > MAX_ARRAY_ITEMS:
            raise GgufInspectionError(
                "GGUF metadata array is too large."
            )

        fixed_format = VALUE_FORMATS.get(item_type)

        if not keep and fixed_format:
            self.skip(
                struct.calcsize("<" + fixed_format)
                * length
            )
            return None

        values = [] if keep else None
        return_limit = min(length, 128)

        for index in range(length):
            retain_item = keep and index < return_limit
            item = self.value(
                item_type,
                retain_item,
                depth + 1,
            )

            if retain_item:
                values.append(item)

        return values


def read_gguf_metadata(path):
    path = _expand_gguf_path(
        path,
        "Model path",
    )
    reader = _Reader(path)

    try:
        if reader.read(4) != b"GGUF":
            raise GgufInspectionError(
                "File does not have a GGUF header."
            )

        version = reader.unpack("I")

        if version not in (2, 3):
            raise GgufInspectionError(
                f"Unsupported GGUF version: {version}"
            )

        tensor_count = reader.unpack("Q")
        metadata_count = reader.unpack("Q")

        if metadata_count > MAX_METADATA_ITEMS:
            raise GgufInspectionError(
                "GGUF contains too many metadata entries."
            )

        metadata = {}
        keys = set()
        has_chat_template = False

        for _ in range(metadata_count):
            key = reader.string(keep=True)

            try:
                key.encode("ascii")
            except UnicodeEncodeError as exc:
                raise GgufInspectionError(
                    "GGUF metadata key is not ASCII."
                ) from exc

            keys.add(key)
            keep = (
                key in PUBLIC_METADATA_KEYS
                or key.endswith(".context_length")
            )
            value_type = reader.unpack("I")
            value = reader.value(
                value_type,
                keep=keep,
            )

            if keep:
                metadata[key] = value

            if (
                key == "tokenizer.chat_template"
                or key.startswith(
                    "tokenizer.chat_template."
                )
            ):
                has_chat_template = True

        return {
            "path": str(path),
            "file_size": path.stat().st_size,
            "gguf_version": version,
            "tensor_count": tensor_count,
            "metadata_count": metadata_count,
            "metadata": metadata,
            "metadata_keys": keys,
            "has_chat_template": has_chat_template,
        }

    finally:
        reader.close()


def _tokens(value):
    return {
        token
        for token in TOKEN_SPLIT.split(
            str(value).lower()
        )
        if token
        and token not in IGNORED_MATCH_TOKENS
        and not token.isdigit()
    }


def _projector_metadata(info):
    metadata = info["metadata"]
    keys = info["metadata_keys"]
    architecture = str(
        metadata.get(
            "general.architecture",
            "",
        )
    ).lower()
    return (
        architecture == "clip"
        or "clip.has_vision_encoder" in keys
        or "clip.projector_type" in keys
    )


def _candidate_score(model_info, candidate_info):
    model_path = Path(model_info["path"])
    candidate_path = Path(candidate_info["path"])
    score = 0
    reasons = []

    if _projector_metadata(candidate_info):
        score += 60
        reasons.append("projector_metadata")

    lowered = candidate_path.stem.lower()

    if "mmproj" in lowered:
        score += 30
        reasons.append("mmproj_filename")
    elif "projector" in lowered:
        score += 20
        reasons.append("projector_filename")

    model_name = model_info["metadata"].get(
        "general.name",
        model_path.stem,
    )
    candidate_name = candidate_info["metadata"].get(
        "general.name",
        candidate_path.stem,
    )
    shared = _tokens(model_path.stem) | _tokens(model_name)
    shared &= (
        _tokens(candidate_path.stem)
        | _tokens(candidate_name)
    )

    if shared:
        score += min(len(shared), 6) * 5
        reasons.append("shared_model_name")

    return score, reasons


def discover_mmproj(model_info):
    model_path = Path(model_info["path"])
    candidates = []
    warnings = []
    siblings = sorted(
        model_path.parent.glob("*.gguf"),
        key=lambda item: item.name.lower(),
    )

    if len(siblings) > MAX_MM_PROJ_CANDIDATES + 1:
        warnings.append(
            "Only the first 64 same-directory GGUF files were checked."
        )

    for path in siblings:
        resolved = path.resolve()

        if resolved == model_path:
            continue

        if len(candidates) >= MAX_MM_PROJ_CANDIDATES:
            break

        try:
            info = read_gguf_metadata(resolved)
        except GgufInspectionError:
            continue

        filename_hint = bool(
            re.search(
                r"(?:mmproj|projector)",
                resolved.stem,
                re.IGNORECASE,
            )
        )

        if not (
            filename_hint
            or _projector_metadata(info)
        ):
            continue

        score, reasons = _candidate_score(
            model_info,
            info,
        )
        candidates.append(
            {
                "path": str(resolved),
                "display_name": info["metadata"].get(
                    "general.name",
                    resolved.stem,
                ),
                "architecture": info["metadata"].get(
                    "general.architecture",
                    "",
                ),
                "projector_type": info["metadata"].get(
                    "clip.projector_type",
                    "",
                ),
                "score": score,
                "reasons": reasons,
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["path"].lower(),
        )
    )

    selected = ""
    confidence = "none"

    if candidates:
        top = candidates[0]
        tied = (
            len(candidates) > 1
            and candidates[1]["score"]
            >= top["score"] - 5
        )

        if tied:
            warnings.append(
                "Several MMProj candidates are similarly likely; choose one manually."
            )
        elif (
            top["score"] >= 60
            and "shared_model_name" in top["reasons"]
        ):
            selected = top["path"]
            confidence = (
                "high"
                if top["score"] >= 90
                else "medium"
            )
        else:
            warnings.append(
                "A possible MMProj was found but was not selected automatically."
            )

    return {
        "path": selected,
        "auto_matched": bool(selected),
        "confidence": confidence,
        "candidates": candidates,
        "warnings": warnings,
    }


def _slug(value):
    value = QUANTIZATION_SUFFIX.sub(
        "",
        str(value).strip(),
    )
    value = re.sub(
        r"[^a-z0-9._-]+",
        "-",
        value.lower(),
    )
    value = re.sub(r"[-_.]{2,}", "-", value)
    value = value.strip("-_.")[:64]
    return value or "custom-model"


def _unique_id(base, reserved_ids):
    reserved = {
        str(item).lower()
        for item in reserved_ids
    }

    if base not in reserved:
        return base

    for suffix in range(2, 1000):
        tail = f"-{suffix}"
        candidate = base[: 64 - len(tail)] + tail

        if candidate not in reserved:
            return candidate

    raise GgufInspectionError(
        "Cannot create a unique suggested model id."
    )


def _classify(text, has_mmproj):
    joined = "".join(
        TOKEN_SPLIT.split(text.lower())
    )

    if any(marker in joined for marker in OCR_MARKERS):
        return "ocr"

    if any(
        marker in joined
        for marker in TRANSLATION_MARKERS
    ):
        return "translation"

    if has_mmproj:
        return "vision"

    return "chat"


def _native_context(metadata):
    values = []

    for key, value in metadata.items():
        if not key.endswith(".context_length"):
            continue

        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        ):
            values.append(value)

    return max(values) if values else None


def inspect_gguf(
    model_path,
    mmproj_path="",
    auto_match_mmproj=True,
    reserved_ids=(),
):
    model_info = read_gguf_metadata(model_path)

    if _projector_metadata(model_info):
        raise GgufInspectionError(
            "The selected model appears to be an MMProj file, not a base model.",
            400,
            "mmproj_selected_as_model",
        )

    warnings = []

    if str(mmproj_path or "").strip():
        explicit_path = _expand_gguf_path(
            mmproj_path,
            "MMProj path",
        )

        if explicit_path == Path(model_info["path"]):
            raise GgufInspectionError(
                "Model path and MMProj path must be different files."
            )

        explicit_info = read_gguf_metadata(
            explicit_path
        )

        if not _projector_metadata(explicit_info):
            warnings.append(
                "The selected MMProj has no recognized projector metadata; verify it manually."
            )

        mmproj = {
            "path": str(explicit_path),
            "auto_matched": False,
            "confidence": "explicit",
            "candidates": [],
            "warnings": [],
        }
    elif auto_match_mmproj:
        mmproj = discover_mmproj(model_info)
        warnings.extend(mmproj.pop("warnings"))
    else:
        mmproj = {
            "path": "",
            "auto_matched": False,
            "confidence": "none",
            "candidates": [],
        }

    metadata = model_info["metadata"]
    model_file = Path(model_info["path"])

    if not metadata.get("general.architecture"):
        warnings.append(
            "GGUF has no general.architecture metadata; verify compatibility manually."
        )

    display_name = str(
        metadata.get(
            "general.name",
            model_file.stem,
        )
    ).strip()[:128]
    model_id = _unique_id(
        _slug(display_name or model_file.stem),
        reserved_ids,
    )
    classification_text = " ".join(
        [
            display_name,
            model_file.stem,
            str(metadata.get("general.basename", "")),
            str(metadata.get("general.finetune", "")),
            str(metadata.get("general.description", "")),
        ]
    )
    model_type = _classify(
        classification_text,
        bool(mmproj["path"]),
    )
    native_context = _native_context(metadata)
    suggested_context = 4096

    if native_context:
        suggested_context = max(
            512,
            min(native_context, 4096),
        )

        if native_context > suggested_context:
            warnings.append(
                "The suggested context is capped at 4096 for a conservative memory default."
            )

    capabilities = {
        "chat": model_type in {
            "chat",
            "translation",
            "vision",
        },
        "vision": bool(mmproj["path"]),
        "ocr": model_type == "ocr",
        "translation": model_type == "translation",
        "streaming": True,
        "thinking": False,
        "temperature": True,
        "custom_prompt": True,
        "context_size": True,
    }
    default_prompt = "OCR:" if model_type == "ocr" else ""

    return {
        "object": "gguf.inspection",
        "model_path": model_info["path"],
        "file_size": model_info["file_size"],
        "gguf_version": model_info["gguf_version"],
        "tensor_count": model_info["tensor_count"],
        "metadata_count": model_info["metadata_count"],
        "architecture": metadata.get(
            "general.architecture",
            "",
        ),
        "metadata": metadata,
        "native_context_size": native_context,
        "has_chat_template": model_info[
            "has_chat_template"
        ],
        "mmproj": mmproj,
        "suggested": {
            "id": model_id,
            "display_name": display_name,
            "type": model_type,
            "model_path": model_info["path"],
            "mmproj_path": mmproj["path"],
            "context_size": suggested_context,
            "gpu_layers": 99,
            "default_prompt": default_prompt,
            "capabilities": capabilities,
        },
        "warnings": warnings,
    }
