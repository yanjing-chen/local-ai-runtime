#!/usr/bin/env python3

import stat
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_runtime import RuntimeManager
from preferences_api import RuntimePreferences


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    llama_root = root / "llama"
    cuda_root = root / "cuda"

    llama_version = llama_root / "versions" / "fixture" / "bin"
    cuda_version = cuda_root / "versions" / "fixture"

    executable(
        llama_version / "llama-server-cpu",
        "echo CPU\n",
    )
    executable(
        llama_version / "llama-server-vulkan",
        "if [ \"$1\" = \"--list-devices\" ]; then "
        "echo 'Vulkan0: Fake AMD GPU'; exit 0; fi\n",
    )
    executable(
        cuda_version / "llama-server-cuda",
        "if [ \"$1\" = \"--list-devices\" ]; then "
        "echo 'CUDA0: Fake NVIDIA GPU'; exit 0; fi\n",
    )

    (llama_root / "current").parent.mkdir(parents=True, exist_ok=True)
    (llama_root / "current").symlink_to(
        llama_root / "versions" / "fixture",
        target_is_directory=True,
    )
    (cuda_root / "current").parent.mkdir(parents=True, exist_ok=True)
    (cuda_root / "current").symlink_to(
        cuda_root / "versions" / "fixture",
        target_is_directory=True,
    )

    preferences_path = root / "preferences.json"
    config = {
        "llama_server": "",
        "llama_runtime_root": str(llama_root),
        "cuda_runtime_root": str(cuda_root),
        "preferences_file": str(preferences_path),
        "models": [],
    }
    manager = RuntimeManager(config)
    preferences = RuntimePreferences(config)

    status = preferences.status()
    assert status["backend_preference"] == "auto", status

    manager.configure_backend_preference("auto")
    selected, backend, fallback = manager._select_runtime_server()
    assert Path(selected).resolve() == (
        cuda_version / "llama-server-cuda"
    ).resolve(), selected
    assert backend == "cuda", backend
    assert fallback is None, fallback

    preferences.set_preload_model("fixture-model")
    preferences.set_backend_preference("vulkan")
    status = preferences.status()
    assert status["preload_model"] == "fixture-model", status
    assert status["backend_preference"] == "vulkan", status

    manager.configure_backend_preference("vulkan")
    selected, backend, fallback = manager._select_runtime_server()
    assert Path(selected).resolve() == (
        llama_version / "llama-server-vulkan"
    ).resolve(), selected
    assert backend == "vulkan", backend
    assert fallback is None, fallback

    (cuda_version / "llama-server-cuda").write_text(
        "#!/bin/sh\necho 'CUDA driver unavailable'\nexit 1\n",
        encoding="utf-8",
    )
    (cuda_version / "llama-server-cuda").chmod(0o755)

    manager.configure_backend_preference("cuda")
    selected, backend, fallback = manager._select_runtime_server()
    assert backend == "vulkan", backend
    assert "Falling back to vulkan" in fallback, fallback

    manager.configure_backend_preference("cpu")
    selected, backend, fallback = manager._select_runtime_server()
    assert Path(selected).resolve() == (
        llama_version / "llama-server-cpu"
    ).resolve(), selected
    assert backend == "cpu", backend
    assert fallback is None, fallback

print("BACKEND DEFAULT AUTO       PASS")
print("CUDA AUTOSELECTION        PASS")
print("MANUAL BACKEND SELECTION  PASS")
print("SAFE CUDA FALLBACK        PASS")
print("PREFERENCE PRESERVATION   PASS")
