# Packizard Builder

Packizard Builder is a PySide6 desktop application based on the uploaded Lazy_AMPR workflow, reworked with Packizard branding and an integrated PS5 debug PKG builder.

## Integrations

- Drakmor `ampr_emu` workflow for AMPR/LZ4 packing and extraction.
- SvenGDK `LibProsperoPKG` v2.5 native ABI for prepared-folder PKG building (`lpp_build_package_ex`) and decrypted-backup to debug fPKG conversion (`lpp_convert_backup`).
- Packizard artwork supplied by the project owner.

The native PKG binaries are not committed. `scripts/fetch_pkg_engine.py` downloads the official v2.5 release for the current platform and verifies its pinned SHA-256 before extraction.

Supported engine targets: Windows x64/ARM64, Linux x64/ARM64 and macOS ARM64.

## Upstream

- https://github.com/drakmor/ampr_emu
- https://github.com/SvenGDK/LibProsperoPKG
- https://github.com/SvenGDK/LibProsperoPKG/releases/tag/v2.5

See `THIRD_PARTY_NOTICES.md` before redistributing bundled binaries.
