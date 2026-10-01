# Upstream base

Packizard Builder 0.2.0 is derived from the user-supplied `Lazy_AMPR-0.0.1.zip` baseline corresponding to the early Lazy_AMPR repository state used by this project.

Packizard-specific integration includes the desktop UI, state migration, build/release tooling, AMPR workflow orchestration, the integrated PKG page and post-compression PKG pipeline, and `Packizard.PkgBridge`.

The PKG engine is no longer an external GUI launcher. Packizard.PkgBridge is built against the pinned validated LibProsperoPKG main snapshot declared in `bridge/LIBPROSPERO_VERSION` and `bridge/LIBPROSPERO_REF`.

Upstream references:

- https://github.com/Nazky/Lazy_AMPR
- https://github.com/drakmor/ampr_emu
- https://github.com/SvenGDK/LibProsperoPKG
