#!/usr/bin/env python3

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from runtime_api import (
    CudaRuntimeController,
    LlamaRuntimeController,
    RuntimeApiError,
)

from model_api import (
    ModelController,
    ModelApiError,
)

from preferences_api import (
    RuntimePreferences,
    RuntimePreferenceError,
)


VERSION = "1.0.0"


def expand_path(value):
    if not value:
        return ""
    return str(Path(os.path.expanduser(value)).resolve())


class RuntimeManager:
    def __init__(self, config):
        self.config = config
        self.backend_host = config.get(
            "backend_host",
            "127.0.0.1",
        )
        self.backend_port = int(
            config.get(
                "backend_port",
                18180,
            )
        )
        self.default_llama_server = expand_path(
            config.get(
                "llama_server",
                "",
            )
        )

        self.llama_runtime_root = expand_path(
            config.get(
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
        )

        self.cuda_runtime_root = expand_path(
            config.get(
                "cuda_runtime_root",
                str(
                    Path.home()
                    / ".local"
                    / "share"
                    / "local-ai-runtime"
                    / "runtime"
                    / "cuda"
                ),
            )
        )

        self.startup_timeout = int(
            config.get(
                "startup_timeout_seconds",
                120,
            )
        )
        self.idle_timeout = RuntimePreferences.validate_idle_timeout(
            config.get("idle_unload_seconds", 600), stored=True,
        )

        self.models = {}

        for model in config.get(
            "models",
            [],
        ):
            model_id = model.get(
                "id",
                "",
            ).strip()

            if model_id:
                self.models[model_id] = model

        self.process = None
        self.current_model = None
        self.last_used = 0.0

        self.request_lock = threading.Lock()
        self.state_lock = threading.RLock()

        self.stop_event = threading.Event()
        self.idle_wakeup = threading.Event()

        self.preload_model = ""
        self.preload_state = "disabled"
        self.preload_error = None

        self.backend_preference = "auto"
        self.active_backend = None
        self.backend_fallback = None

        self.idle_thread = threading.Thread(
            target=self._idle_worker,
            name="local-ai-runtime-idle",
            daemon=True,
        )

        self.idle_thread.start()

    def backend_url(self, path):
        return (
            f"http://{self.backend_host}:"
            f"{self.backend_port}{path}"
        )

    def _backend_healthy(self):
        try:
            with urllib.request.urlopen(
                self.backend_url("/health"),
                timeout=1.0,
            ) as response:
                return 200 <= response.status < 300

        except Exception:
            return False

    def status(self):
        with self.state_lock:
            process_running = (
                self.process is not None
                and self.process.poll() is None
            )

            current_model = self.current_model
            idle_timeout = self.idle_timeout

            backend_pid = (
                self.process.pid
                if process_running
                else None
            )

        return {
            "runtime_version": VERSION,
            "configured_models": list(
                self.models.keys()
            ),
            "current_model": current_model,
            "backend_running": process_running,
            "backend_pid": backend_pid,
            "backend_healthy": (
                self._backend_healthy()
                if process_running
                else False
            ),
            "idle_unload_seconds": idle_timeout,
            "startup_preload": self.preload_status(),
            "backend_preference": self.backend_preference,
            "active_backend": self.active_backend,
            "backend_fallback": self.backend_fallback,
        }

    def preload_status(self):
        with self.state_lock:
            return {
                "enabled": bool(self.preload_model),
                "model": self.preload_model,
                "state": self.preload_state,
                "error": self.preload_error,
            }

    def configure_preload(self, model_id, state=None, error=None):
        with self.state_lock:
            self.preload_model = str(model_id or "").strip()
            self.preload_state = (
                state
                if state is not None
                else (
                    "configured"
                    if self.preload_model
                    else "disabled"
                )
            )
            self.preload_error = error

    def configure_backend_preference(self, backend):
        backend = str(backend or "auto").strip().lower()
        if backend not in (
            "auto",
            "cuda",
            "vulkan",
            "cpu",
        ):
            raise RuntimeError(
                "Invalid backend preference: "
                f"{backend}"
            )

        with self.state_lock:
            self.backend_preference = backend
            self.backend_fallback = None

    def set_model_profile(
        self,
        model_id,
        profile,
    ):
        with self.state_lock:
            self.models[
                model_id
            ] = dict(
                profile
            )

    def forget_model_profile(self, model_id):
        with self.state_lock:
            self.models.pop(
                model_id,
                None,
            )

    def stop_backend(self):
        with self.state_lock:
            process = self.process
            self.process = None
            self.current_model = None
            self.active_backend = None

        if process is None:
            return

        if process.poll() is None:
            process.terminate()

            try:
                process.wait(
                    timeout=8
                )

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(
                    timeout=5
                )

    def _managed_backend_paths(self):

        runtime_bin = (
            Path(self.llama_runtime_root)
            / "current"
            / "bin"
        )

        cuda_root = (
            Path(self.cuda_runtime_root)
            / "current"
        )

        cuda_candidates = (
            cuda_root / "llama-server-cuda",
            cuda_root / "bin" / "llama-server-cuda",
        )
        cuda = next(
            (
                path
                for path in cuda_candidates
                if path.is_file()
            ),
            cuda_candidates[0],
        )

        return {
            "cuda": cuda,
            "vulkan": runtime_bin / "llama-server-vulkan",
            "cpu": runtime_bin / "llama-server-cpu",
        }

    def _probe_backend(self, backend, path):
        result = {
            "backend": backend,
            "path": str(path),
            "installed": path.is_file(),
            "usable": False,
            "device": "",
            "error": None,
        }

        if not path.is_file():
            result["error"] = "Executable is not installed."
            return result

        if not os.access(path, os.X_OK):
            result["error"] = "Executable is not executable."
            return result

        if backend == "cpu":
            result["usable"] = True
            result["device"] = "CPU"
            return result

        try:
            probe = subprocess.run(
                [str(path), "--list-devices"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=15,
                check=False,
            )
            output = (probe.stdout or "").strip()
            lowered = output.lower()
            markers = (
                ("cuda", "nvidia")
                if backend == "cuda"
                else ("vulkan",)
            )
            result["usable"] = (
                probe.returncode == 0
                and any(marker in lowered for marker in markers)
            )
            result["device"] = output[:2048]
            if not result["usable"]:
                result["error"] = (
                    output[:2048]
                    or f"{backend} device probe failed."
                )

        except Exception as exc:
            result["error"] = str(exc)

        return result

    def backend_status(self):
        paths = self._managed_backend_paths()
        availability = {
            backend: self._probe_backend(backend, path)
            for backend, path in paths.items()
        }

        selected, effective, fallback = self._select_runtime_server(
            availability=availability
        )

        return {
            "preference": self.backend_preference,
            "effective_backend": effective,
            "active_backend": self.active_backend,
            "fallback": fallback,
            "executable": selected,
            "availability": availability,
        }

    def _select_runtime_server(self, availability=None):
        paths = self._managed_backend_paths()
        availability = availability or {
            backend: self._probe_backend(backend, path)
            for backend, path in paths.items()
        }

        orders = {
            "auto": ("cuda", "vulkan", "cpu"),
            "cuda": ("cuda", "vulkan", "cpu"),
            "vulkan": ("vulkan", "cpu"),
            "cpu": ("cpu",),
        }
        order = orders[self.backend_preference]

        for backend in order:
            item = availability[backend]
            if not item["usable"]:
                continue

            fallback = None
            if self.backend_preference != "auto" and backend != order[0]:
                requested = availability[order[0]]
                fallback = (
                    f"Requested {order[0]} backend is unavailable: "
                    f"{requested['error']} Falling back to {backend}."
                )

            return item["path"], backend, fallback

        return "", None, (
            "No usable managed llama.cpp backend is installed."
        )

    def _auto_runtime_server(self):
        runtime, _, _ = self._select_runtime_server()
        return runtime

    def _model_command(self, model):
        runtime = expand_path(
            model.get(
                "llama_server",
                "",
            )
        )

        if not runtime:
            runtime = self.default_llama_server

        backend = "custom"

        if not runtime:
            runtime, backend, fallback = self._select_runtime_server()
            self.backend_fallback = fallback

        if not runtime:
            raise RuntimeError(
                "No llama-server executable is available. "
                "Install a Local AI Runtime CPU/Vulkan or CUDA runtime first."
            )

        runtime_path = Path(runtime)

        if not runtime_path.is_file():
            raise RuntimeError(
                f"llama-server not found: {runtime}"
            )

        model_path = expand_path(
            model.get(
                "model_path",
                "",
            )
        )

        if (
            not model_path
            or not Path(model_path).is_file()
        ):
            raise RuntimeError(
                "Model file not found for "
                f"{model.get('id')}: {model_path}"
            )

        command = [
            runtime,
            "-m",
            model_path,
            "--host",
            self.backend_host,
            "--port",
            str(self.backend_port),
        ]

        mmproj = expand_path(
            model.get(
                "mmproj_path",
                "",
            )
        )

        if mmproj:
            if not Path(mmproj).is_file():
                raise RuntimeError(
                    f"MMProj file not found: {mmproj}"
                )

            command += [
                "--mmproj",
                mmproj,
            ]

        extra_args = model.get(
            "extra_args",
            [],
        )

        if not isinstance(
            extra_args,
            list,
        ):
            raise RuntimeError(
                "extra_args must be a JSON array "
                f"for {model.get('id')}"
            )

        command += [
            str(x)
            for x in extra_args
        ]

        return command, backend

    def ensure_model(self, model_id):
        if model_id not in self.models:
            raise KeyError(model_id)

        with self.state_lock:
            same_model = (
                self.current_model == model_id
                and self.process is not None
                and self.process.poll() is None
            )

        if (
            same_model
            and self._backend_healthy()
        ):
            self.last_used = time.monotonic()
            return

        self.stop_backend()

        model = self.models[model_id]
        command, backend = self._model_command(model)

        state_dir = (
            Path.home()
            / ".local"
            / "share"
            / "local-ai-runtime"
        )

        state_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        log_path = (
            state_dir
            / "llama-server.log"
        )

        log_file = open(
            log_path,
            "ab",
            buffering=0,
        )

        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        with self.state_lock:
            self.process = process
            self.current_model = model_id
            self.active_backend = backend

        deadline = (
            time.monotonic()
            + self.startup_timeout
        )

        while (
            time.monotonic()
            < deadline
        ):
            if process.poll() is not None:
                self.stop_backend()

                raise RuntimeError(
                    "llama-server exited while loading "
                    f"{model_id}. See {log_path}"
                )

            if self._backend_healthy():
                self.last_used = (
                    time.monotonic()
                )
                return

            time.sleep(0.25)

        self.stop_backend()

        raise RuntimeError(
            "Timed out loading model "
            f"{model_id}. See {log_path}"
        )

    def configure_idle_timeout(self, seconds):
        seconds = RuntimePreferences.validate_idle_timeout(seconds)
        # Serialize configuration changes with all active requests and the
        # idle worker. Changing the policy never unloads an active request.
        with self.request_lock:
            with self.state_lock:
                self.idle_timeout = seconds
        self.idle_wakeup.set()

    def _idle_worker(self):
        while not self.stop_event.is_set():
            # Wake immediately when the idle setting is changed; otherwise
            # poll every five seconds as in 0.8.0.
            self.idle_wakeup.wait(5)
            self.idle_wakeup.clear()
            if self.stop_event.is_set():
                return

            with self.state_lock:
                timeout = self.idle_timeout
                model_loaded = self.current_model is not None
                last_used = self.last_used

            if (not model_loaded or timeout == 0
                    or time.monotonic() - last_used < timeout):
                continue

            if not self.request_lock.acquire(blocking=False):
                continue
            try:
                # Recheck the *current* policy under the request lock: an
                # inference or preferences write might have happened since
                # the initial observation.
                with self.state_lock:
                    timeout = self.idle_timeout
                    should_unload = (
                        self.current_model is not None
                        and timeout > 0
                        and time.monotonic() - self.last_used >= timeout
                    )
                if should_unload:
                    self.stop_backend()
            finally:
                self.request_lock.release()

    def shutdown(self):
        self.stop_event.set()
        self.idle_wakeup.set()

        with self.request_lock:
            self.stop_backend()


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(
        self,
        fmt,
        *args,
    ):
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (
                self.address_string(),
                self.log_date_time_string(),
                fmt % args,
            )
        )

    @property
    def manager(self):
        return self.server.runtime_manager

    @property
    def llama_runtime(self):
        return (
            self.server
            .llama_runtime_controller
        )

    @property
    def cuda_runtime(self):
        return (
            self.server
            .cuda_runtime_controller
        )

    @property
    def model_controller(self):
        return (
            self.server
            .model_controller
        )

    @property
    def preferences(self):
        return self.server.runtime_preferences

    def send_json(
        self,
        status,
        payload,
    ):
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.send_header(
            "Connection",
            "close",
        )
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def read_json_body(
        self,
        allow_empty=False,
    ):
        try:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

        except ValueError:
            content_length = 0

        if content_length <= 0:
            if allow_empty:
                return {}, b""

            raise RuntimeApiError(
                "Request body is required.",
                400,
                "invalid_request_error",
            )

        raw = self.rfile.read(
            content_length
        )

        try:
            payload = json.loads(raw)

        except json.JSONDecodeError as exc:
            raise RuntimeApiError(
                "Invalid JSON.",
                400,
                "invalid_request_error",
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeApiError(
                "JSON body must be an object.",
                400,
                "invalid_request_error",
            )

        return payload, raw

    def do_GET(self):
        parsed = urlsplit(
            self.path
        )

        path = parsed.path
        query = parse_qs(
            parsed.query
        )

        if path == "/health":
            status = self.manager.status()

            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "local-ai-runtime",
                    **status,
                },
            )
            return

        if path == "/v1/runtime/status":
            self.send_json(
                200,
                self.manager.status(),
            )
            return

        if path == "/v1/runtime/preferences":
            self.send_json(
                200,
                {
                    **self.preferences.status(),
                    "startup_preload": self.manager.preload_status(),
                },
            )
            return

        if path == "/v1/runtime/backends":
            self.send_json(
                200,
                self.manager.backend_status(),
            )
            return

        if path == "/v1/runtime/llama/status":
            refresh = (
                query.get(
                    "refresh",
                    ["0"],
                )[0]
                in (
                    "1",
                    "true",
                    "yes",
                )
            )

            self.send_json(
                200,
                self.llama_runtime.status(
                    refresh=refresh
                ),
            )
            return

        if path == "/v1/runtime/cuda/status":
            refresh = (
                query.get(
                    "refresh",
                    ["0"],
                )[0]
                in (
                    "1",
                    "true",
                    "yes",
                )
            )

            self.send_json(
                200,
                self.cuda_runtime.status(
                    refresh=refresh
                ),
            )
            return

        if path == "/v1/models":
            refresh = (
                query.get(
                    "refresh",
                    ["0"],
                )[0]
                in (
                    "1",
                    "true",
                    "yes",
                )
            )

            self.send_json(
                200,
                self.model_controller.list_status(
                    refresh=refresh
                ),
            )
            return

        if path == "/v1/models/custom":
            self.send_json(
                200,
                self.model_controller.list_custom_status(),
            )
            return

        self.send_json(
            404,
            {
                "error": {
                    "message": "Not found",
                    "type": "not_found",
                }
            },
        )

    def do_POST(self):
        parsed = urlsplit(
            self.path
        )

        path = parsed.path

        try:
            if path == "/v1/runtime/preferences":
                payload, _ = self.read_json_body(
                    allow_empty=False
                )

                if not any(
                    key in payload
                    for key in (
                        "preload_model",
                        "backend_preference",
                        "idle_unload_seconds",
                    )
                ):
                    raise RuntimePreferenceError(
                        "preload_model, backend_preference or "
                        "idle_unload_seconds is required.",
                        400,
                        "invalid_request_error",
                    )

                backend_changed = False

                if "preload_model" in payload:
                    model_id = payload["preload_model"]

                    if isinstance(model_id, str) and model_id.strip():
                        self.model_controller.runtime_profile(
                            model_id.strip()
                        )

                    result = self.preferences.set_preload_model(
                        model_id
                    )
                    self.manager.configure_preload(
                        result["preload_model"],
                        "pending_restart"
                        if result["preload_enabled"]
                        else "disabled",
                    )

                if "backend_preference" in payload:
                    old_backend = self.manager.backend_preference
                    result = self.preferences.set_backend_preference(
                        payload["backend_preference"]
                    )
                    new_backend = result["backend_preference"]
                    backend_changed = new_backend != old_backend

                    if backend_changed:
                        with self.manager.request_lock:
                            self.manager.stop_backend()

                    self.manager.configure_backend_preference(
                        new_backend
                    )

                if "idle_unload_seconds" in payload:
                    result = self.preferences.set_idle_unload_seconds(
                        payload["idle_unload_seconds"]
                    )
                    self.manager.configure_idle_timeout(
                        result["idle_unload_seconds"]
                    )

                result = self.preferences.status()

                self.send_json(
                    200,
                    {
                        **result,
                        "applies_on_next_start": (
                            "preload_model" in payload
                        ),
                        "backend_changed": backend_changed,
                        "backend_applies_on_next_request": backend_changed,
                        "startup_preload": self.manager.preload_status(),
                    },
                )
                return

            if path == "/v1/models/inspect":
                payload, _ = self.read_json_body(
                    allow_empty=False
                )

                result = (
                    self.model_controller
                    .inspect_custom_model(payload)
                )

                self.send_json(
                    200,
                    result,
                )
                return

            if path == "/v1/models/custom":
                payload, _ = self.read_json_body(
                    allow_empty=False
                )

                model_id = str(
                    payload.get(
                        "id",
                        "",
                    )
                ).strip()

                with self.manager.request_lock:
                    status, created = (
                        self.model_controller
                        .upsert_custom(payload)
                    )

                    if (
                        model_id
                        and self.manager.current_model
                        == model_id
                    ):
                        self.manager.stop_backend()

                    self.manager.forget_model_profile(
                        model_id
                    )

                self.send_json(
                    201 if created else 200,
                    status,
                )
                return

            if path == "/v1/models/custom/remove":
                payload, _ = self.read_json_body(
                    allow_empty=False
                )

                model_id = str(
                    payload.get(
                        "model",
                        "",
                    )
                ).strip()

                if not model_id:
                    raise ModelApiError(
                        "Model id is required.",
                        400,
                        "invalid_request_error",
                    )

                with self.manager.request_lock:
                    removed = (
                        self.model_controller
                        .remove_custom(model_id)
                    )

                    if (
                        self.manager.current_model
                        == model_id
                    ):
                        self.manager.stop_backend()

                    self.manager.forget_model_profile(
                        model_id
                    )

                self.send_json(
                    200,
                    {
                        "id": model_id,
                        "deleted": True,
                        "files_removed": False,
                        "model_path": removed[
                            "model_path"
                        ],
                        "mmproj_path": removed.get(
                            "mmproj_path",
                            "",
                        ),
                    },
                )
                return

            if (
                path
                == "/v1/models/remove"
            ):
                payload, _ = (
                    self.read_json_body(
                        allow_empty=False
                    )
                )

                model_id = str(
                    payload.get(
                        "model",
                        "",
                    )
                ).strip()

                if not model_id:
                    raise ModelApiError(
                        "Model id is required.",
                        400,
                        "invalid_request_error",
                    )

                with self.manager.request_lock:
                    if (
                        self.manager.current_model
                        == model_id
                    ):
                        self.manager.stop_backend()

                    status, files_removed = (
                        self.model_controller
                        .uninstall(model_id)
                    )
                    self.manager.forget_model_profile(
                        model_id
                    )

                    preference = self.preferences.status()
                    preload_cleared = (
                        preference["preload_model"]
                        == model_id
                    )
                    if preload_cleared:
                        self.preferences.set_preload_model("")
                        self.manager.configure_preload(
                            "",
                            "disabled",
                        )

                self.send_json(
                    200,
                    {
                        "id": model_id,
                        "deleted": True,
                        "files_removed": files_removed,
                        "preload_cleared": preload_cleared,
                        "model": status,
                    },
                )
                return

            if (
                path
                == "/v1/models/install"
            ):
                payload, _ = (
                    self.read_json_body(
                        allow_empty=False
                    )
                )

                model_id = str(
                    payload.get(
                        "model",
                        "",
                    )
                ).strip()

                if not model_id:
                    raise ModelApiError(
                        "Model id is required.",
                        400,
                        "invalid_request_error",
                    )

                operation = (
                    self.model_controller
                    .start_install(
                        model_id
                    )
                )

                self.send_json(
                    202,
                    {
                        "accepted": True,
                        "operation": operation,
                    },
                )
                return

            if (
                path
                == "/v1/runtime/llama/install"
            ):
                payload, _ = (
                    self.read_json_body(
                        allow_empty=True
                    )
                )

                version = payload.get(
                    "version"
                )

                operation = (
                    self.llama_runtime
                    .start_install(
                        version
                    )
                )

                self.send_json(
                    202,
                    {
                        "accepted": True,
                        "operation": operation,
                    },
                )
                return

            if (
                path
                == "/v1/runtime/llama/rollback"
            ):
                self.read_json_body(
                    allow_empty=True
                )

                result = (
                    self.llama_runtime
                    .rollback()
                )

                self.send_json(
                    200,
                    result,
                )
                return

            if (
                path
                == "/v1/runtime/cuda/install"
            ):
                payload, _ = (
                    self.read_json_body(
                        allow_empty=True
                    )
                )

                operation = (
                    self.cuda_runtime
                    .start_install(
                        payload.get("version")
                    )
                )

                self.send_json(
                    202,
                    {
                        "accepted": True,
                        "operation": operation,
                    },
                )
                return

            if (
                path
                == "/v1/runtime/cuda/rollback"
            ):
                self.read_json_body(
                    allow_empty=True
                )

                with self.manager.request_lock:
                    self.manager.stop_backend()
                    result = self.cuda_runtime.rollback()

                self.send_json(
                    200,
                    result,
                )
                return

            if (
                path
                != "/v1/chat/completions"
            ):
                self.send_json(
                    404,
                    {
                        "error": {
                            "message": "Not found",
                            "type": "not_found",
                        }
                    },
                )
                return

            payload, raw_body = (
                self.read_json_body(
                    allow_empty=False
                )
            )

            model_id = str(
                payload.get(
                    "model",
                    "",
                )
            ).strip()

            if not model_id:
                raise RuntimeApiError(
                    "The request must explicitly "
                    "specify a model.",
                    400,
                    "invalid_request_error",
                )

            profile = (
                self.model_controller
                .runtime_profile(
                    model_id
                )
            )

            self.manager.set_model_profile(
                model_id,
                profile,
            )

            with self.manager.request_lock:
                self.manager.ensure_model(
                    model_id
                )

                self.manager.last_used = (
                    time.monotonic()
                )

                upstream_request = (
                    urllib.request.Request(
                        self.manager.backend_url(
                            "/v1/chat/completions"
                        ),
                        data=raw_body,
                        method="POST",
                        headers={
                            "Content-Type":
                            "application/json",
                        },
                    )
                )

                try:
                    upstream = (
                        urllib.request.urlopen(
                            upstream_request,
                            timeout=3600,
                        )
                    )

                except urllib.error.HTTPError as exc:
                    upstream = exc

                self.send_response(
                    upstream.status
                )

                content_type = (
                    upstream.headers.get(
                        "Content-Type",
                        "application/json",
                    )
                )

                media_type = (
                    content_type
                    .split(
                        ";",
                        1,
                    )[0]
                    .strip()
                    .lower()
                )

                event_stream = (
                    media_type
                    == "text/event-stream"
                )

                self.send_header(
                    "Content-Type",
                    content_type,
                )

                content_length_header = (
                    upstream.headers.get(
                        "Content-Length"
                    )
                )

                if (
                    content_length_header
                    and not event_stream
                ):
                    self.send_header(
                        "Content-Length",
                        content_length_header,
                    )

                if event_stream:
                    self.send_header(
                        "Cache-Control",
                        "no-cache",
                    )
                    self.send_header(
                        "X-Accel-Buffering",
                        "no",
                    )

                self.send_header(
                    "Connection",
                    "close",
                )
                self.end_headers()

                try:
                    if event_stream:
                        while True:
                            line = (
                                upstream.readline()
                            )

                            if not line:
                                break

                            self.wfile.write(
                                line
                            )
                            self.wfile.flush()

                    else:
                        while True:
                            chunk = upstream.read(
                                65536
                            )

                            if not chunk:
                                break

                            self.wfile.write(
                                chunk
                            )
                            self.wfile.flush()

                finally:
                    upstream.close()

                self.close_connection = True

                self.manager.last_used = (
                    time.monotonic()
                )

        except ModelApiError as exc:
            self.send_json(
                exc.status_code,
                {
                    "error": {
                        "message": str(exc),
                        "type": exc.error_type,
                    }
                },
            )

        except RuntimeApiError as exc:
            self.send_json(
                exc.status_code,
                {
                    "error": {
                        "message": str(exc),
                        "type": exc.error_type,
                    }
                },
            )

        except RuntimePreferenceError as exc:
            self.send_json(
                exc.status_code,
                {
                    "error": {
                        "message": str(exc),
                        "type": exc.error_type,
                    }
                },
            )

        except Exception as exc:
            self.send_json(
                503,
                {
                    "error": {
                        "message": str(exc),
                        "type": "runtime_error",
                    }
                },
            )


def load_config(path):
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as handle:
        config = json.load(handle)

    if not isinstance(
        config,
        dict,
    ):
        raise RuntimeError(
            "Configuration root must be an object."
        )

    if not isinstance(
        config.get(
            "models",
            [],
        ),
        list,
    ):
        raise RuntimeError(
            "'models' must be an array."
        )

    return config


def main():
    parser = argparse.ArgumentParser(
        prog="local-ai-runtime",
        description=(
            "Shared local llama.cpp runtime "
            "and model router"
        ),
    )

    parser.add_argument(
        "--config",
        default=str(
            Path.home()
            / ".config"
            / "local-ai-runtime"
            / "config.json"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    args = parser.parse_args()

    config_path = expand_path(
        args.config
    )

    try:
        config = load_config(
            config_path
        )

    except Exception as exc:
        print(
            "Failed to load configuration: "
            f"{exc}",
            file=sys.stderr,
        )
        return 2

    host = config.get(
        "listen_host",
        "127.0.0.1",
    )

    port = int(
        config.get(
            "listen_port",
            8111,
        )
    )

    manager = RuntimeManager(
        config
    )

    llama_runtime = (
        LlamaRuntimeController(
            config
        )
    )

    cuda_runtime = (
        CudaRuntimeController(
            config
        )
    )

    model_controller = (
        ModelController(
            config
        )
    )

    preferences = RuntimePreferences(
        config
    )

    preference_status = preferences.status()
    manager.configure_preload(
        preference_status["preload_model"]
    )
    manager.configure_backend_preference(
        preference_status["backend_preference"]
    )
    manager.configure_idle_timeout(
        preference_status["idle_unload_seconds"]
    )

    server = ThreadingHTTPServer(
        (
            host,
            port,
        ),
        ApiHandler,
    )

    server.runtime_manager = manager
    server.llama_runtime_controller = (
        llama_runtime
    )
    server.cuda_runtime_controller = (
        cuda_runtime
    )
    server.model_controller = (
        model_controller
    )
    server.runtime_preferences = preferences

    def request_shutdown(
        signum,
        frame,
    ):
        threading.Thread(
            target=server.shutdown,
            daemon=True,
        ).start()

    signal.signal(
        signal.SIGTERM,
        request_shutdown,
    )

    signal.signal(
        signal.SIGINT,
        request_shutdown,
    )

    print(
        f"Local AI Runtime {VERSION} "
        f"listening on "
        f"http://{host}:{port}",
        flush=True,
    )

    def preload_at_startup():
        model_id = preferences.status()[
            "preload_model"
        ]

        if not model_id:
            manager.configure_preload(
                "",
                "disabled",
            )
            return

        manager.configure_preload(
            model_id,
            "loading",
        )

        try:
            profile = model_controller.runtime_profile(
                model_id
            )
            manager.set_model_profile(
                model_id,
                profile,
            )

            with manager.request_lock:
                manager.ensure_model(
                    model_id
                )

            manager.configure_preload(
                model_id,
                "loaded",
            )

        except Exception as exc:
            manager.configure_preload(
                model_id,
                "error",
                str(exc),
            )
            print(
                "Startup model preload failed: "
                f"{exc}",
                file=sys.stderr,
                flush=True,
            )

    preload_thread = threading.Thread(
        target=preload_at_startup,
        name="local-ai-runtime-preload",
        daemon=True,
    )
    preload_thread.start()

    try:
        server.serve_forever()

    finally:
        manager.shutdown()
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
