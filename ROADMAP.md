# Local AI Runtime Roadmap

## Stage 0 — complete
- Independent user-level service
- OpenAI-compatible API
- llama-server supervisor
- systemd --user integration

## Stage 1 — complete
- Versioned llama.cpp runtime manager
- CPU / Vulkan runtime packaging
- SHA-256 verification
- current / previous runtime links
- runtime upgrade and rollback
- GitHub Actions runtime build

## Stage 2A — complete
- Published verified CPU/Vulkan runtime
- fixed remote runtime manifest
- live GitHub download verification
- live install verification

## Stage 2B — complete
- runtime status API
- asynchronous runtime installation API
- update detection
- rollback API
- backend suitable for a graphical Install button

## Stage 3A — complete
- Model Manager foundation
- model manifest support
- model installation and SHA-256 verification
- automatic model switching
- single-model residency
- same-model process reuse

## Stage 3B — complete
- official PaddleOCR-VL-1.6 catalog entry
- official Tencent Hy-MT2-7B Q4_K_M catalog entry
- immutable Hugging Face revision pinning
- verified upstream file sizes and SHA-256 metadata
- public models manifest

## Stage 3C
- real PaddleOCR-VL installation
- real Hy-MT2-7B installation
- Vulkan inference
- OCR -> translation model switching
- RAM / VRAM validation

## Stage 3D — complete
- production user-level Local AI Runtime bundle
- automatic managed Vulkan runtime discovery
- CPU fallback
- systemd --user install/start support
- fixed application manifest for GUI installers

## Stage 4
- Flameshot OCR client migration
- Local AI Runtime installation UI
- remove llama.cpp ownership from Flameshot
- preserve v2.4 OCR behavior

## Stage 5
- GNOME extension integration
- HY-MT2-7B shared backend
- 6800H memory validation
- SSE streaming proxy regression test

## Stage 6C — Runtime foundation complete
- persistent custom GGUF model registry
- optional MMProj path
- context size and GPU layer settings
- capability declarations
- safe active-model unload on update or removal
- external model files are never removed
- Flameshot model-management UI remains the next Stage 6C step

## Stage 6
- HunyuanOCR
- per-model Prompt
- Streaming
- Thinking
- Temperature
- Context Size

## Stage 7
- CUDA Runtime Manager integration
- CUDA 12.8-r2 multi-architecture
