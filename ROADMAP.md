# Local AI Runtime Roadmap

## Stage 0 — complete
- Independent user-level service
- OpenAI-compatible API
- llama-server supervisor
- systemd --user integration

## Stage 1 — current
- Versioned llama.cpp runtime manager
- CPU / Vulkan runtime packaging
- resumable runtime downloads
- SHA-256 verification
- required-file verification
- current / previous runtime links
- runtime upgrade
- runtime rollback
- GitHub Actions runtime build

## Stage 2
- Publish verified runtime Release
- fixed remote runtime manifest
- one-click runtime installation API
- runtime update checks

## Stage 3
- Model Manager
- PaddleOCR-VL
- HY-MT2-7B
- model manifest
- single-model residency
- automatic model switching
- idle unloading

## Stage 4
- Flameshot OCR client migration
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
