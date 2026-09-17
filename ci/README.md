# CI overlay

This directory is the compact source-of-truth used to reconstruct Packizard Builder in GitHub Actions.

`bootstrap_source.py` applies the pinned Lazy_AMPR base overlay, the packaging hardening already validated in UAT, the Packizard 0.2 integrated-PKG incremental overlay, the selected LibProsperoPKG source pin and the Packizard branding asset.

Do not bypass `feature/* -> UAT -> Golden Build -> main` when changing these files.
