# Third-party notices

Packizard Builder is derived from the user-supplied Lazy_AMPR 0.0.1 source snapshot and retains its upstream credits.

## AMPR tooling

`external/ampr_emu` originates from Drakmor's `ampr_emu` project and is distributed under GPL-3.0. Its license and the licenses of bundled dependencies must remain with redistributed builds.

- https://github.com/drakmor/ampr_emu

## PPR-PKG Builder / LibProsperoPkg.Gui

Packizard launches PPR-PKG Builder as a separate external application. The source repository intentionally does not track the PPR executable or `libScePubTools.dll`.

A local build tree may contain the exact `fpkg-gui-0.6.7.zip` contents supplied by the user under `tools/ppr_pkg_builder/`. That uploaded archive identifies `LibProsperoPkg.Gui` version 0.6.7 and contains Windows x86-64 binaries. No standalone redistribution license was present in the supplied ZIP, so Packizard does not claim redistribution rights for those binaries. They should only be bundled where the operator has the necessary rights.

Relevant public source references:

- https://github.com/drakmor/LibProsperoPKG
- https://github.com/SvenGDK/LibProsperoPKG
- https://github.com/drakmor/ppr-patch

Packizard does not replace PPR-PKG Builder with a different PKG implementation and does not copy its package-building implementation into Packizard's Python code.
