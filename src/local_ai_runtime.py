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
    LlamaRuntimeController,
    RuntimeApiError,
)

from model_api import (
    ModelController,
    ModelApiError,
)


VERSION = "0.2.0"


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
        self.startup_timeout = int(
            config.get(
                "startup_timeout_seconds",
                120,
            )
        )
        self.idle_timeout = int(
            config.get(
                "idle_unload_seconds",
                600,
            )
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
        self.state_lock = threading.Lock()

        self.stop_event = threading.Event()

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
            "idle_unload_seconds": self.idle_timeout,
        }

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

    def stop_backend(self):
        with self.state_lock:
            process = self.process
            self.process = None
            self.current_model = None

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

    def _model_command(self, model):
        runtime = expand_path(
            model.get(
                "llama_server",
                "",
            )
        )

        if not runtime:
            runtime = self.default_llama_server

        if not runtime:
            raise RuntimeError(
                "No llama-server executable is configured."
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

        return command

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
        command = self._model_command(model)

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

    def _idle_worker(self):
        while not self.stop_event.wait(5):
            if self.idle_timeout <= 0:
                continue

            with self.state_lock:
                model_loaded = (
                    self.current_model
                    is not None
                )

            if not model_loaded:
                continue

            if (
                time.monotonic()
                - self.last_used
                < self.idle_timeout
            ):
                continue

            if self.request_lock.acquire(
                blocking=False
            ):
                try:
                    if (
                        self.current_model
                        is not None
                        and time.monotonic()
                        - self.last_used
                        >= self.idle_timeout
                    ):
                        self.stop_backend()

                finally:
                    self.request_lock.release()

    def shutdown(self):
        self.stop_event.set()

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
    def model_controller(self):
        return (
            self.server
            .model_controller
        )

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

                self.send_header(
                    "Content-Type",
                    content_type,
                )

                content_length_header = (
                    upstream.headers.get(
                        "Content-Length"
                    )
                )

                if content_length_header:
                    self.send_header(
                        "Content-Length",
                        content_length_header,
                    )

                self.send_header(
                    "Connection",
                    "close",
                )
                self.end_headers()

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

    model_controller = (
        ModelController(
            config
        )
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
    server.model_controller = (
        model_controller
    )

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
