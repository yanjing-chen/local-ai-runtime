#!/usr/bin/env python3
"""Runtime 1.0-A: persistence, live API, concurrency and true idle eviction.

All tests use a temporary directory and isolated loopback ports. The normal
8111 service, llama.cpp binaries and user model registry are never touched.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_runtime import RuntimeManager
from preferences_api import RuntimePreferences, RuntimePreferenceError


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def api(url, method="GET", payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, method=method, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.04)
    return predicate()


class DummyProcess:
    pid = 123456
    def __init__(self):
        self.stopped = False
        self.terminated = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.terminated = True
        self.stopped = True

    def wait(self, timeout):
        return 0


def preference_and_manager_test(base):
    path = base / "preferences-direct.json"
    config = {"preferences_file": str(path), "idle_unload_seconds": 39,
              "models": []}
    pref = RuntimePreferences(config)
    assert pref.status()["idle_unload_seconds"] == 39
    assert not path.exists(), "GET must not create files"
    pref.set_preload_model("hello")
    assert pref.status()["idle_unload_seconds"] == 39
    for bad in (-1, 86401, 1.5, "10", True, False, None, {}, []):
        try:
            pref.set_idle_unload_seconds(bad)
        except RuntimePreferenceError as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"Expected rejection: {bad!r}")
        assert pref.status()["idle_unload_seconds"] == 39
    assert pref.set_idle_unload_seconds(86400)["idle_unload_seconds"] == 86400
    pref.set_idle_unload_seconds(0)
    assert json.loads(path.read_text())["preload_model"] == "hello"
    assert path.stat().st_mode & 0o777 == 0o600
    assert RuntimePreferences(config).status()["idle_unload_seconds"] == 0
    path.write_text('{"schema_version":1,"idle_unload_seconds":true}')
    try:
        pref.status()
    except RuntimePreferenceError as exc:
        assert exc.status_code == 500
    else:
        raise AssertionError("corrupt persisted value must not be accepted")
    print("PREFERENCE DEFAULT/VALIDATION/ATOMIC PERSISTENCE PASS", flush=True)

    config = {"models": [], "idle_unload_seconds": 600}
    manager = RuntimeManager(config)
    try:
        process = DummyProcess()
        with manager.state_lock:
            manager.process = process
            manager.current_model = "fake"
            manager.last_used = time.monotonic() - 20
        manager.configure_idle_timeout(0)
        time.sleep(0.2)
        assert not process.terminated, "0 must disable idle unloading"
        manager.configure_idle_timeout(30)
        time.sleep(0.2)
        assert not process.terminated
        manager.configure_idle_timeout(1)
        assert wait(lambda: process.terminated, 2), "new timeout must wake worker"
        assert manager.current_model is None
        print("LIVE EVICTION / ZERO DISABLE PASS", flush=True)
    finally:
        manager.shutdown()

    manager = RuntimeManager(config)
    try:
        process = DummyProcess()
        with manager.state_lock:
            manager.process = process
            manager.current_model = "fake"
            manager.last_used = time.monotonic() - 50
        manager.request_lock.acquire()
        try:
            done = threading.Event()
            thread = threading.Thread(
                target=lambda: (manager.configure_idle_timeout(1), done.set()),
                daemon=True,
            )
            thread.start()
            time.sleep(0.25)
            assert not done.is_set(), "policy update waits for active request"
            assert not process.terminated, "must never unload active inference"
        finally:
            manager.request_lock.release()
        assert done.wait(2)
        assert wait(lambda: process.terminated, 2)
        thread.join(timeout=2)
        print("ACTIVE REQUEST LOCK SAFETY PASS", flush=True)
    finally:
        manager.shutdown()


def live_api_test(base):
    config_path = base / "isolated-config.json"
    prefs_path = base / "isolated-preferences.json"
    port = free_port()
    backend_port = free_port()
    while backend_port == port:
        backend_port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    config = {
        "listen_host": "127.0.0.1", "listen_port": port,
        "backend_host": "127.0.0.1", "backend_port": backend_port,
        "llama_server": "", "llama_runtime_root": str(base / "unused-llama"),
        "cuda_runtime_root": str(base / "unused-cuda"),
        "llama_runtime_manifest_url": "", "cuda_runtime_manifest_url": "",
        "model_root": str(base / "models"),
        "custom_model_registry": str(base / "custom.json"),
        "preferences_file": str(prefs_path), "model_manifest_url": "",
        "idle_unload_seconds": 27, "startup_timeout_seconds": 5,
        "models": [],
    }
    config_path.write_text(json.dumps(config))

    def launch():
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "local_ai_runtime.py"),
             "--config", str(config_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True,
        )
        assert wait(lambda: process.poll() is None and is_ready(), 6), (
            process.stderr.read() if process.poll() is not None else "not ready"
        )
        return process

    def is_ready():
        try:
            status, _ = api(base_url + "/health", timeout=0.4)
            return status == 200
        except Exception:
            return False

    def stop(process):
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        process.stderr.close()

    process = launch()
    try:
        status, baseline = api(base_url + "/v1/runtime/preferences")
        assert status == 200 and baseline["idle_unload_seconds"] == 27
        assert baseline["preload_enabled"] is False
        assert not prefs_path.exists()
        for bad in (True, "60", 3.5, -4, 86401, None):
            code, response = api(
                base_url + "/v1/runtime/preferences", "POST",
                {"idle_unload_seconds": bad},
            )
            assert code == 400 and response["error"]["type"] == "invalid_request_error", (bad, response)
            assert not prefs_path.exists()
        code, response = api(base_url + "/v1/runtime/preferences", "POST", {})
        assert code == 400
        code, response = api(
            base_url + "/v1/runtime/preferences", "POST",
            {"idle_unload_seconds": 0},
        )
        assert code == 200 and response["idle_unload_seconds"] == 0, response
        assert response["applies_on_next_start"] is False
        assert prefs_path.stat().st_mode & 0o777 == 0o600
        code, runtime = api(base_url + "/v1/runtime/status")
        assert code == 200 and runtime["idle_unload_seconds"] == 0
        assert not runtime["backend_running"]
        code, response = api(base_url + "/v1/runtime/preferences", "POST", {
            "idle_unload_seconds": 2, "backend_preference": "auto",
            "preload_model": "",
        })
        assert code == 200 and response["idle_unload_seconds"] == 2
        assert response["preload_enabled"] is False
        assert response["backend_preference"] == "auto"
        assert api(base_url + "/health")[1]["idle_unload_seconds"] == 2
        print("HTTP VALIDATION/LIVE STATUS/COMBINED PREFERENCES PASS", flush=True)
    finally:
        stop(process)
    process = launch()
    try:
        _, result = api(base_url + "/v1/runtime/preferences")
        assert result["idle_unload_seconds"] == 2
        _, health = api(base_url + "/health")
        assert health["idle_unload_seconds"] == 2
        assert not health["backend_running"]
        print("PREFERENCE SURVIVES REAL SERVICE RESTART PASS", flush=True)
    finally:
        stop(process)


# Run this supplement under the same temporary directory as the main suite.
# It exercises an actual SSE stream and the idle preference POST concurrently.
def streaming_inference_test(base):
    config_path = base / "stream-config.json"
    port, backend_port = free_port(), free_port()
    while port == backend_port:
        backend_port = free_port()
    url = f"http://127.0.0.1:{port}"
    fixture_dir = base / "stream-fixture"
    manifest = subprocess.check_output(
        [sys.executable, str(ROOT / "tests" / "make_model_fixture.py"),
         str(fixture_dir)], text=True,
    ).strip()
    cfg = {
        "listen_host": "127.0.0.1", "listen_port": port,
        "backend_host": "127.0.0.1", "backend_port": backend_port,
        "llama_server": str(ROOT / "tests" / "fake_llama_server.py"),
        "llama_runtime_root": str(base / "unused-llama-stream"),
        "cuda_runtime_root": str(base / "unused-cuda-stream"),
        "llama_runtime_manifest_url": "", "cuda_runtime_manifest_url": "",
        "model_root": str(base / "installed-models"),
        "model_manifest_url": manifest,
        "custom_model_registry": str(base / "custom-stream.json"),
        "preferences_file": str(base / "preferences-stream.json"),
        "startup_timeout_seconds": 5, "idle_unload_seconds": 60,
        "models": [],
    }
    config_path.write_text(json.dumps(cfg))
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "src" / "local_ai_runtime.py"),
         "--config", str(config_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        def ready():
            try:
                return api(url + "/health", timeout=0.2)[0] == 200
            except Exception:
                return False
        assert wait(ready, 5), "stream test daemon did not start"
        code, result = api(url + "/v1/models/install", "POST", {"model": "model-a"})
        assert code == 202, result
        def installed():
            try:
                _, info = api(url + "/v1/models")
                return any(item["id"] == "model-a" and item["installed"]
                           for item in info["data"])
            except Exception:
                return False
        assert wait(installed, 7), "fixture model did not install"

        first_event = threading.Event()
        completed = threading.Event()
        stream_failure = []

        def stream():
            try:
                req = urllib.request.Request(
                    url + "/v1/chat/completions", method="POST",
                    data=json.dumps({"model": "model-a", "stream": True,
                                     "messages": [{"role":"user", "content":"test"}]}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    assert response.headers.get_content_type() == "text/event-stream"
                    for line in response:
                        if line.startswith(b"data:"):
                            first_event.set()
                        if line.startswith(b"data: [DONE]"):
                            completed.set()
                            break
            except Exception as exc:
                stream_failure.append(exc)
                first_event.set()

        stream_thread = threading.Thread(target=stream, daemon=True)
        stream_thread.start()
        assert first_event.wait(5), "no first streaming event"
        assert not stream_failure, stream_failure
        assert not completed.is_set(), "stream finished before concurrency test"
        _, before = api(url + "/v1/runtime/status")
        assert before["backend_running"] and before["current_model"] == "model-a"
        old_pid = before["backend_pid"]

        updated = threading.Event()
        update_error = []
        def change():
            try:
                status, response = api(
                    url + "/v1/runtime/preferences", "POST",
                    {"idle_unload_seconds": 1}, timeout=8,
                )
                assert status == 200 and response["idle_unload_seconds"] == 1
            except Exception as exc:
                update_error.append(exc)
            finally:
                updated.set()
        change_thread = threading.Thread(target=change, daemon=True)
        change_thread.start()
        time.sleep(0.2)
        assert not updated.is_set(), "idle setting should wait for stream"
        _, during = api(url + "/v1/runtime/status")
        assert during["backend_pid"] == old_pid and during["backend_running"]
        assert completed.wait(8), "stream did not finish"
        assert updated.wait(8), "configuration update blocked after stream"
        assert not stream_failure and not update_error, (stream_failure, update_error)
        assert wait(lambda: api(url + "/v1/runtime/status")[1]["current_model"] is None,
                    7), "idle eviction failed after stream completion"
        assert api(url + "/health")[0] == 200, "idle eviction stopped the API"
        stream_thread.join(timeout=2)
        change_thread.join(timeout=2)
        print("LIVE SSE SAFE UPDATE / POST-STREAM EVICTION PASS", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="local-ai-runtime-v1a-") as td:
        base = Path(td)
        preference_and_manager_test(base)
        live_api_test(base)
        streaming_inference_test(base)
    print("LOCAL AI RUNTIME 1.0-A: PASS", flush=True)
