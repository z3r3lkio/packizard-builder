# Integrated PKG engine tracking

Packizard does not execute the standalone PPR-PKG Builder GUI. The application ships its own `Packizard.PkgBridge` and builds that helper from the public LibProsperoPKG source snapshot selected by `ci/libprospero_pin.json`.

The pin records two independent version identities:

- `version` / `ref`: the public SvenGDK/LibProsperoPKG source version and exact commit used to compile Packizard's bridge;
- `ppr_gui_reference_version`: the PPR-PKG Builder/fpkg-gui behavior reference currently used when aligning Packizard defaults and UI semantics.

These must not be conflated. A new upstream source commit is promoted by a `feature/libprospero-*` PR to UAT, where the normal six-platform pipeline must produce a Golden Build. Runtime builds therefore never float to an untested `main` commit.

The current PPR GUI reference is **0.6.8**. Its known behavior changes are treated as compatibility requirements only where the public source API exposes the corresponding capability. Packizard must not claim parity for a private/binary-only feature until an auditable source/API implementation is available and covered by tests.

For Packizard 0.2.0, bootstrap first checks out the pinned 2.6.0 source and then applies the files in `ci/large_pkg_overrides/`. Folder inputs are spooled to disk and compressed in 256 KiB blocks; file-backed inner and outer images avoid whole-payload CLR arrays. Explicit in-memory inputs retain the small-image path below 64 MiB. Finalization uses streaming from 64 MiB when a file-based SI factory is available. Metadata tables still scale with the number of files and blocks, and temporary disk space is required for source copies, encoded payloads and intermediate images.

Build stages own their temporary files until they explicitly hand them to the next stage. Success and managed exception paths remove owned intermediates. An abrupt process termination can still leave temporary files.

After reconstruction, run `dotnet run --project ci/tests/StreamingRegression -- --large` from the repository root. These regressions compare compression, inner-image and outer-image bytes, check cleanup after injected failures, and exercise a single input larger than 2 GiB with bounded payload allocations. They do not replace the six-platform Golden Build or on-console acceptance testing.
