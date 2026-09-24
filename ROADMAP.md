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

## Stage 3
- Model Manager
- model manifest
- PaddleOCR-VL
- HY-MT2-7B
- single-model residency
- automatic model switching
- idle unloading

## Stage 4
- Flameshot OCR client migration
- Local AI Runtime installation UI
- remove llama.cpp ownership from Flameshot
- preserve v2.4 OCR behavior

## Stage 5
- GNOME extension integration
- HY-MT2-7B shared backend
- 6800H memory validation

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
