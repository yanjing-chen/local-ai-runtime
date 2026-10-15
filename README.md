# Local AI Runtime

Shared local llama.cpp runtime and model router for Linux.

The goal is to provide one user-level AI backend that can be shared by:

- Flameshot OCR
- GNOME translation / rewriting extensions
- other OpenAI-compatible local applications

## Design

Public API:

    http://127.0.0.1:8111

The client explicitly selects a model using the OpenAI `model` field.

Examples:

    paddleocr-vl-1.6

Only one large model is intended to remain resident at a time.

When a request for another model arrives, Local AI Runtime will:

1. finish the current request,
2. stop the existing llama-server,
3. release RAM / VRAM,
4. start llama-server with the requested model,
5. wait for `/health`,
6. forward the original request.

An idle timeout can unload the active model automatically.

## Runtime 1.0-A development: live idle-unload preference

The API service keeps running when no model is loaded. Models are unloaded
by the idle worker after a configurable interval since the last completed
request. Existing `config.json` `idle_unload_seconds` values remain the
fallback until the user explicitly changes their preference.

    GET  /v1/runtime/preferences
    POST /v1/runtime/preferences

Example: `{"idle_unload_seconds":300}`. Allowed values are integers from 0
(disable automatic unloading) to 86400 (24 hours). `600` is the default
when neither the saved preference nor the launch config overrides it.
Values are persisted in `preferences.json` with the existing atomic-write
mechanism and apply without restarting the service; a changed timeout wakes
the idle worker immediately. Active inference requests, including SSE streams,
are protected by the request lock. This is a shared setting: any client
editing it changes the timeout for every client of the same Runtime process.

The development version is `1.0.0-dev`; this stage does not publish or install
Runtime 1.0.0 or update the llama.cpp binaries.

## Optional startup preload

Local AI Runtime 0.7 keeps the HTTP service available while leaving
llama-server and all models unloaded by default. The first OCR, translation,
or chat request automatically starts the requested model, so clients continue
to work when startup preload is disabled.

A client may configure one installed model to load after the next Runtime
start:

    GET  /v1/runtime/preferences
    POST /v1/runtime/preferences

Example request body:

    {"preload_model":"paddleocr-vl-1.6"}

Use an empty string to disable startup preload. Changing this preference does
not interrupt the currently active model. Read-only health, status, model-list,
and inspection requests never load a model.

The preference is stored separately from the launch configuration at:

    ~/.config/local-ai-runtime/preferences.json

## Acceleration backends (0.8 development)

Local AI Runtime 0.8 owns backend selection for all clients. The persistent
preference may be `auto`, `cuda`, `vulkan`, or `cpu`; `auto` tries CUDA first,
then Vulkan, then CPU. A requested unavailable accelerator falls back safely
without changing the stored preference.

    GET  /v1/runtime/backends
    POST /v1/runtime/preferences

Example request body:

    {"backend_preference":"cuda"}

Changing the preference unloads an active model and applies to the next model
request. CPU/Vulkan and CUDA runtime files have separate versioned roots. CUDA
installation and rollback are also exposed through the Runtime API:

    GET  /v1/runtime/cuda/status?refresh=1
    POST /v1/runtime/cuda/install
    POST /v1/runtime/cuda/rollback

CUDA user-space libraries are downloaded only when requested. The NVIDIA
driver and its `libcuda.so.1` remain host requirements. No client package owns
or bundles these files.

The validated `cuda-12.8-r3` package targets NVIDIA architectures sm75, sm86,
sm89 and sm120. It is published independently from client packages through the
Runtime CUDA manifest and was validated on an RTX 3050 Laptop GPU (sm86).

Streaming chat completions are forwarded as Server-Sent Events without
waiting for the complete response. Clients can use the standard OpenAI
`"stream": true` request field.

## Custom GGUF models

Local AI Runtime 0.4 adds a persistent custom model registry. Custom models
reference existing local GGUF files; registering or removing an entry never
copies or deletes those files.

Supported settings include:

- model GGUF path
- optional multimodal projector (MMProj) GGUF path
- context size
- GPU layer count
- model type, default prompt and capability flags

API routes:

    GET  /v1/models/custom
    POST /v1/models/inspect
    POST /v1/models/custom
    POST /v1/models/custom/remove
    POST /v1/models/remove

`POST /v1/models/inspect` reads a local GGUF header without loading the
model. It suggests an id, display name, model type, conservative context
size and capability flags. For multimodal models it checks GGUF files in
the same directory and selects an MMProj only when one candidate is clearly
matched by projector metadata and model-name hints. Ambiguous candidates are
returned for manual selection. Every suggested value remains editable.

The registry is stored by default at:

    ~/.config/local-ai-runtime/custom-models.json

Updating or removing the active custom model unloads its llama-server process.
The next request starts the selected model with the new settings, preserving
the single-model residency guarantee.

## Supported catalog models

The supported public catalog intentionally stays small:

- PaddleOCR-VL 1.6 for OCR and vision
- other GGUF models may be registered as custom local models

Other compatible local models can be registered through the custom GGUF API.
Local AI Runtime never copies or removes the external files used by a custom
model entry.

## Current status

The current Runtime implements:

- user-level HTTP service
- `/health`
- `/v1/models`
- `/v1/runtime/status`
- `/v1/chat/completions`
- explicit model routing
- llama-server process supervisor
- single-model switching foundation
- idle model unloading
- systemd user-service installer
- automated smoke tests
- managed CPU / Vulkan llama.cpp runtime updates and rollback
- verified model installation
- persistent custom GGUF registration
- automatic GGUF metadata inspection and MMProj discovery
- real-time SSE streaming
- optional persistent startup preload, disabled by default
- persistent automatic/CUDA/Vulkan/CPU backend preference
- independently installed, verified and rollback-capable CUDA runtime

Model and llama.cpp runtime installation remain separate from client
applications. Removing Flameshot OCR does not remove this shared Runtime.

## Development

Run:

    ./dev.sh test

The development smoke test uses port 18111 so it does not conflict with the current Flameshot OCR service on port 8111.

## Runtime 1.0-B4 CPU/Vulkan candidate (development only)

The isolated workflow `.github/workflows/build-cpu-vulkan-v1-candidate.yml`
builds pinned llama.cpp `d81235049384534c167caea52b85a694f6103d14`
(`v0.6.0`) on Ubuntu 24.04. It never triggers CUDA builds or creates
a GitHub Release. Existing `build-runtime.yml`, `build-cuda-runtime.yml`,
and the published `packaging/runtime/llama-runtimes.json` are preserved.

The tested candidate version is `llama-d8123504-r1`. Once the Ubuntu 24.04
archive and `runtime-metadata.json` are retrieved from the CI artifact,
`packaging/runtime/stage_llama_candidate.py` can validate both files
and generate a *separate* manifest with the old versions retained. The
script does not publish, install, or overwrite the current manifest.

8845HS testing: 3 repeated PaddleOCR-VL 1.6 runs passed for CPU and Vulkan
(Radeon 780M). Old b11103 direct comparison, long-document OCR and HY-MT2
translation remain unverified; do not describe this candidate as released.

## 1.0.0-rc1 staging (unpublished)

This local release candidate includes dynamic idle unload preferences, a validated
CPU/Vulkan candidate and an independently validated CUDA candidate. Model files
and inference backends remain separately installable and rollback-capable.
The stage1d candidate is **not** an upgrade of an installed Runtime. The
published 0.8.0 application and legacy CPU/Vulkan/CUDA manifest entries remain
unchanged until the release and migration tests are complete.
