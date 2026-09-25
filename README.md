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
    hunyuan-ocr
    hy-mt2-7b

Only one large model is intended to remain resident at a time.

When a request for another model arrives, Local AI Runtime will:

1. finish the current request,
2. stop the existing llama-server,
3. release RAM / VRAM,
4. start llama-server with the requested model,
5. wait for `/health`,
6. forward the original request.

An idle timeout can unload the active model automatically.

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
    POST /v1/models/custom
    POST /v1/models/custom/remove

The registry is stored by default at:

    ~/.config/local-ai-runtime/custom-models.json

Updating or removing the active custom model unloads its llama-server process.
The next request starts the selected model with the new settings, preserving
the single-model residency guarantee.

## Current status

Stage 0 implements:

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

No model or llama.cpp runtime is installed by Stage 0 yet.

The current Flameshot OCR v2.4 installation is not modified.

## Development

Run:

    ./dev.sh test

The development smoke test uses port 18111 so it does not conflict with the current Flameshot OCR service on port 8111.
