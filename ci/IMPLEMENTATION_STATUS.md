# Packizard 0.2.0 integration status

This feature branch replaces the external PPR-PKG Builder launcher with an integrated package engine and is intended to merge into UAT only after the six-platform Golden Build passes.

Implemented scope:

- integrated `Packizard.PkgBridge` on .NET 10;
- pinned, auditable public LibProsperoPKG source snapshot;
- PPR-PKG Builder/fpkg-gui 0.6.8 behavior reference tracked separately;
- automatic Compress → LZ4 → PKG chaining;
- manual/advanced Build PKG page backed by the same engine;
- structural post-build package validation;
- native bridge packaging for Windows, Linux and macOS on x64 and ARM64;
- complete high-resolution Packizard artwork in the sidebar;
- Packizard-first credits with compact upstream acknowledgements;
- daily upstream-main detection through feature PRs rather than runtime floating updates.

Promotion criteria: unit/UI tests, bridge compile/probe, all six packages, per-platform SHA-256 validation, Golden Build.
