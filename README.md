# Packizard Builder

Packizard Builder is a PySide6 desktop front end for the AMPR workflow plus an integration point for the **PPR-PKG Builder / LibProsperoPkg.Gui** application shown in the project reference image.

## PKG conversion

PKG creation is delegated exclusively to the external PPR-PKG Builder selected by the user. Packizard no longer calls `LibProsperoPkg` directly through ctypes and has no alternate PKG-builder fallback.

Workflow:

1. Select your copy of `LibProsperoPkg.Gui.exe` / PPR-PKG Builder (the requested reference is `LibProsperoPKG v0.6.7 — package tool`, © Drakmor & SvenGDK).
2. Select a source folder or `.gp5` project in Packizard.
3. Packizard reads `param.json` only for a metadata preview, copies the source path to the clipboard and opens PPR-PKG Builder.
4. Configure DRM, SDK, image mode, PFS, Kraken, PlayGo, `libScePubTools.dll` and the remaining options in PPR-PKG Builder itself, then press **Build PKG** there.

No undocumented command-line flags are sent to the external application. Its executable is not redistributed by this repository. You can select it from the UI or set:

```text
PACKIZARD_PPR_PKG=C:\path\to\LibProsperoPkg.Gui.exe
```

Packizard also scans `tools/ppr_pkg_builder/` for the external application.

## Base and upstream references

The source snapshot is derived from the user-supplied Lazy_AMPR 0.0.1 project and keeps its AMPR workflow.

- Drakmor / `ampr_emu`: https://github.com/drakmor/ampr_emu
- Drakmor / `ppr-patch`: https://github.com/drakmor/ppr-patch
- SvenGDK / `LibProsperoPKG`: https://github.com/SvenGDK/LibProsperoPKG

The exact PPR-PKG Builder binary is external to this repository and is not redistributed by Packizard Builder.
