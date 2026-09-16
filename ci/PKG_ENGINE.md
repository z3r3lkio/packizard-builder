# Integrated PKG engine tracking

Packizard does not execute the standalone PPR-PKG Builder GUI. The application ships its own `Packizard.PkgBridge` and builds that helper from the public LibProsperoPKG source snapshot selected by `ci/libprospero_pin.json`.

The pin records two independent version identities:

- `version` / `ref`: the public SvenGDK/LibProsperoPKG source version and exact commit used to compile Packizard's bridge;
- `ppr_gui_reference_version`: the PPR-PKG Builder/fpkg-gui behavior reference currently used when aligning Packizard defaults and UI semantics.

These must not be conflated. A new upstream source commit is promoted by a `feature/libprospero-*` PR to UAT, where the normal six-platform pipeline must produce a Golden Build. Runtime builds therefore never float to an untested `main` commit.

The current PPR GUI reference is **0.6.8**. Its known behavior changes are treated as compatibility requirements only where the public source API exposes the corresponding capability. Packizard must not claim parity for a private/binary-only feature until an auditable source/API implementation is available and covered by tests.
