#!/usr/bin/env python3

import json
import os
import stat
import sys
import tempfile
from pathlib import Path


sys.path.insert(
    0,
    str(
        Path(__file__).resolve()
        .parents[1]
        / "src"
    ),
)

from local_ai_runtime import RuntimeManager


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    runtime = (
        root
        / "runtime"
        / "llama"
    )

    version = (
        runtime
        / "fixture-r1"
        / "bin"
    )

    version.mkdir(
        parents=True
    )

    current = (
        runtime
        / "current"
    )

    current.symlink_to(
        runtime
        / "fixture-r1",
        target_is_directory=True,
    )

    vulkan = (
        version
        / "llama-server-vulkan"
    )

    cpu = (
        version
        / "llama-server-cpu"
    )

    vulkan.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--list-devices\" ]; then\n"
        "  echo 'Vulkan0: Fake GPU'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )

    cpu.write_text(
        "#!/bin/sh\nexit 0\n"
    )

    vulkan.chmod(
        vulkan.stat().st_mode
        | stat.S_IXUSR
    )

    cpu.chmod(
        cpu.stat().st_mode
        | stat.S_IXUSR
    )

    config = {
        "llama_server": "",
        "llama_runtime_root":
            str(runtime),
        "models": [],
    }

    manager = RuntimeManager(
        config
    )

    selected = (
        manager._auto_runtime_server()
    )

    # Keep the public "current" symlink path in normal operation.
    # Resolve both sides only for identity comparison in this test.
    assert (
        Path(selected).resolve()
        == vulkan.resolve()
    ), selected

    print(
        "VULKAN AUTOSELECT       PASS"
    )

    vulkan.write_text(
        "#!/bin/sh\n"
        "echo 'No devices'\n"
        "exit 1\n"
    )

    vulkan.chmod(
        vulkan.stat().st_mode
        | stat.S_IXUSR
    )

    selected = (
        manager._auto_runtime_server()
    )

    assert (
        Path(selected).resolve()
        == cpu.resolve()
    ), selected

    print(
        "CPU FALLBACK            PASS"
    )


print(
    "RUNTIME AUTOSELECT TEST: PASS"
)
