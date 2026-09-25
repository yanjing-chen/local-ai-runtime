#!/usr/bin/env python3

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path


LLAMA_CPP_REF = "828fdf282e195300c2965bd9511807e24ed53bdb"
LLAMA_CPP_ARCHIVE_SHA256 = (
    "45fcb555a7fe3a4d2a56d7d3cf66b18a80cce1fbfafe8463b1171bedc9fec44f"
)
LLAMA_CPP_ARCHIVE_URL = (
    "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/"
    + LLAMA_CPP_REF
)

CONVERTER_REQUIREMENTS = (
    "--extra-index-url https://download.pytorch.org/whl/cpu\n"
    "numpy~=2.2.6\n"
    "sentencepiece>=0.1.98,<0.3.0\n"
    "transformers==4.57.6\n"
    "protobuf>=4.21.0,<5.0.0\n"
    "torch==2.11.0\n"
)


class HunyuanOcrInstallError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


class HunyuanOcrInstaller:
    def __init__(self, config, downloader, phase_callback):
        self.downloader = downloader
        self.phase_callback = phase_callback
        self.tool_root = Path(
            os.path.expanduser(
                str(
                    config.get(
                        "hunyuanocr_converter_root",
                        "~/.local/share/local-ai-runtime/tools/"
                        "hunyuanocr-converter/828fdf282",
                    )
                )
            )
        ).resolve()

        configured = config.get(
            "hunyuanocr_converter_command"
        )

        if isinstance(configured, list):
            self.converter_command = [
                str(item)
                for item in configured
            ]
        elif configured:
            self.converter_command = shlex.split(
                str(configured)
            )
        else:
            self.converter_command = None

    def _phase(self, phase, **extra):
        self.phase_callback(
            phase,
            **extra,
        )

    def _verified_download(self, item, destination):
        expected_sha = str(
            item.get("sha256", "")
        ).lower()

        if not expected_sha:
            raise HunyuanOcrInstallError(
                "Missing source SHA256 metadata."
            )

        if destination.is_file():
            expected_size = item.get("size")
            size_matches = (
                expected_size is None
                or destination.stat().st_size
                == int(expected_size)
            )

            if (
                size_matches
                and sha256_file(destination).lower()
                == expected_sha
            ):
                return

            destination.unlink()

        self.downloader(
            item["url"],
            destination,
            item.get("size"),
        )

        actual_sha = sha256_file(
            destination
        ).lower()

        if actual_sha != expected_sha:
            destination.unlink(
                missing_ok=True
            )
            raise HunyuanOcrInstallError(
                "Source SHA256 mismatch for "
                + str(item.get("name"))
            )

    def download_sources(self, model, cache_directory):
        install = model.get("install", {})
        source_files = install.get(
            "source_files",
            [],
        )

        if not source_files:
            raise HunyuanOcrInstallError(
                "HunyuanOCR install recipe has no source files."
            )

        cache_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        for index, item in enumerate(source_files, start=1):
            name = str(item.get("name", "")).strip()

            if not name or Path(name).name != name:
                raise HunyuanOcrInstallError(
                    f"Unsafe HunyuanOCR source filename: {name}"
                )

            self._phase(
                "downloading",
                current_file=name,
                file_index=index,
                file_count=len(source_files),
            )

            self._verified_download(
                item,
                cache_directory / name,
            )

        return cache_directory

    def _safe_extract_converter(self, archive, destination):
        temporary = Path(
            tempfile.mkdtemp(
                prefix=".extract-",
                dir=destination.parent,
            )
        )

        root_name = (
            "llama.cpp-"
            + LLAMA_CPP_REF
        )
        prefixes = (
            root_name + "/conversion/",
            root_name + "/gguf-py/",
        )
        exact = {
            root_name + "/convert_hf_to_gguf.py",
            root_name + "/LICENSE",
        }

        try:
            with tarfile.open(
                archive,
                "r:gz",
            ) as package:
                selected = []

                for member in package.getmembers():
                    if (
                        member.name in exact
                        or member.name.startswith(prefixes)
                    ):
                        target = (
                            temporary
                            / member.name
                        ).resolve()

                        if temporary.resolve() not in target.parents:
                            raise HunyuanOcrInstallError(
                                "Unsafe path in llama.cpp source archive."
                            )

                        selected.append(member)

                package.extractall(
                    temporary,
                    members=selected,
                )

            extracted = temporary / root_name

            if not (
                extracted
                / "convert_hf_to_gguf.py"
            ).is_file():
                raise HunyuanOcrInstallError(
                    "llama.cpp converter is missing from its archive."
                )

            if destination.exists():
                shutil.rmtree(destination)

            os.replace(
                extracted,
                destination,
            )

        finally:
            shutil.rmtree(
                temporary,
                ignore_errors=True,
            )

    def _prepare_converter_source(self):
        source = self.tool_root / "llama.cpp-converter"
        marker = source / ".source.json"

        if marker.is_file():
            try:
                metadata = json.loads(
                    marker.read_text(
                        encoding="utf-8"
                    )
                )

                if (
                    metadata.get("revision")
                    == LLAMA_CPP_REF
                    and (
                        source
                        / "convert_hf_to_gguf.py"
                    ).is_file()
                ):
                    return source
            except Exception:
                pass

        self.tool_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        archive = (
            self.tool_root
            / ("llama.cpp-" + LLAMA_CPP_REF + ".tar.gz")
        )

        self._phase(
            "preparing_converter_source",
            current_file=archive.name,
        )

        self._verified_download(
            {
                "name": archive.name,
                "url": LLAMA_CPP_ARCHIVE_URL,
                "sha256": LLAMA_CPP_ARCHIVE_SHA256,
            },
            archive,
        )

        self._safe_extract_converter(
            archive,
            source,
        )

        marker.write_text(
            json.dumps(
                {
                    "revision": LLAMA_CPP_REF,
                    "archive_sha256": LLAMA_CPP_ARCHIVE_SHA256,
                    "prepared_at": time.time(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        archive.unlink(
            missing_ok=True
        )

        return source

    def _prepare_python_environment(self):
        environment = self.tool_root / "python-env"
        requirements = self.tool_root / "requirements.txt"
        marker = environment / ".requirements.json"
        requirements_hash = hashlib.sha256(
            CONVERTER_REQUIREMENTS.encode("utf-8")
        ).hexdigest()

        if marker.is_file():
            try:
                metadata = json.loads(
                    marker.read_text(
                        encoding="utf-8"
                    )
                )

                python = environment / "bin" / "python"

                if (
                    metadata.get("sha256")
                    == requirements_hash
                    and python.is_file()
                ):
                    return python
            except Exception:
                pass

        self._phase(
            "preparing_python_environment"
        )

        if environment.exists():
            shutil.rmtree(environment)

        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "venv",
                    str(environment),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise HunyuanOcrInstallError(
                "Cannot create the isolated converter environment. "
                "Install the Ubuntu python3-venv package and retry."
            ) from exc

        requirements.write_text(
            CONVERTER_REQUIREMENTS,
            encoding="utf-8",
        )

        python = environment / "bin" / "python"

        self._phase(
            "installing_converter_dependencies"
        )

        try:
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--require-virtualenv",
                    "-r",
                    str(requirements),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise HunyuanOcrInstallError(
                "Failed to install isolated HunyuanOCR converter dependencies."
            ) from exc

        marker.write_text(
            json.dumps(
                {
                    "sha256": requirements_hash,
                    "prepared_at": time.time(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        return python

    def _run_command(self, command, log_path):
        log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            log_path,
            "a",
            encoding="utf-8",
        ) as log:
            log.write(
                "\n$ "
                + shlex.join(command)
                + "\n"
            )
            log.flush()

            subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )

    def convert(self, source_directory, output_directory, log_path):
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        model_out = output_directory / "hyocr-f16.gguf"
        mmproj_out = output_directory / "mmproj-hyocr-f16.gguf"

        if self.converter_command:
            command = list(self.converter_command)
            command.extend(
                [
                    "--source-dir",
                    str(source_directory),
                    "--model-out",
                    str(model_out),
                    "--mmproj-out",
                    str(mmproj_out),
                ]
            )

            self._phase(
                "converting_model"
            )
            self._run_command(
                command,
                log_path,
            )

        else:
            source = self._prepare_converter_source()
            python = self._prepare_python_environment()
            converter = source / "convert_hf_to_gguf.py"

            self._phase(
                "converting_model"
            )
            self._run_command(
                [
                    str(python),
                    str(converter),
                    "--outfile",
                    str(model_out),
                    "--outtype",
                    "f16",
                    str(source_directory),
                ],
                log_path,
            )

            self._phase(
                "converting_mmproj"
            )
            self._run_command(
                [
                    str(python),
                    str(converter),
                    "--outfile",
                    str(mmproj_out),
                    "--outtype",
                    "f16",
                    "--mmproj",
                    str(source_directory),
                ],
                log_path,
            )

        for path in (model_out, mmproj_out):
            if not path.is_file() or path.stat().st_size < 1024:
                raise HunyuanOcrInstallError(
                    "Converter did not create a valid output: "
                    + path.name
                )

        return model_out, mmproj_out

    def install(self, model, cache_directory, staging, log_path):
        source = self.download_sources(
            model,
            cache_directory,
        )

        converted = staging / ".converted"
        model_out, mmproj_out = self.convert(
            source,
            converted,
            log_path,
        )

        files = model.get("files", [])
        output_by_role = {
            "model": model_out,
            "mmproj": mmproj_out,
        }

        self._phase(
            "finalizing"
        )

        for item in files:
            role = item.get("role", "model")
            source_path = output_by_role.get(role)

            if source_path is None:
                raise HunyuanOcrInstallError(
                    f"Unsupported generated output role: {role}"
                )

            name = str(item.get("name", "")).strip()

            if not name or Path(name).name != name:
                raise HunyuanOcrInstallError(
                    f"Unsafe generated output filename: {name}"
                )

            target = staging / name
            os.replace(
                source_path,
                target,
            )

            minimum = int(
                item.get("min_size", 1024)
            )

            if target.stat().st_size < minimum:
                raise HunyuanOcrInstallError(
                    f"Generated output is too small: {name}"
                )

        shutil.rmtree(
            converted,
            ignore_errors=True,
        )

        license_source = source / "LICENSE"

        if license_source.is_file():
            shutil.copy2(
                license_source,
                staging / "LICENSE",
            )

        return {
            item["name"]: {
                "size": (staging / item["name"]).stat().st_size,
                "sha256": sha256_file(staging / item["name"]),
            }
            for item in files
        }
