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

## Stage 3C — complete
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

## Stage 4 — complete
- Flameshot OCR client migration
- Local AI Runtime installation UI
- remove llama.cpp ownership from Flameshot
- preserve v2.4 OCR behavior

## Stage 5 — complete
- GNOME extension integration
- HY-MT2-7B shared backend
- 6800H memory validation
- SSE streaming proxy regression test

## Stage 6C — complete
- persistent custom GGUF model registry
- optional MMProj path
- context size and GPU layer settings
- capability declarations
- safe active-model unload on update or removal
- external model files are never removed
- Flameshot model-management UI

## Stage 6D-1 / 6D-2 — complete
- llama.cpp b11103 CPU/Vulkan runtime
- HunyuanOCR flags
- runtime update and rollback
- PaddleOCR and HY-MT2 regressions on Ryzen 7 6800H

## Stage 6D-3 — Runtime installer complete
- official Tencent HunyuanOCR 1.5 source checkpoint
- immutable revision and SHA-256 pinning
- explicit Tencent license acceptance
- resumable source downloads
- isolated local F16 GGUF and MMProj conversion
- pinned upstream llama.cpp b11103 converter
- no redistribution of Tencent model weights
- DFlash deliberately deferred to preserve one-model residency

## Stage 6D remaining
- HunyuanOCR 1.5 real conversion and OCR validation on Ryzen 7 6800H
- Flameshot HunyuanOCR selection and license UI
- per-model Prompt
- Streaming
- Thinking
- Temperature
- Context Size

## Stage 7
- CUDA Runtime Manager integration
- CUDA 12.8-r2 multi-architecture
