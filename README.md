# Packizard Builder

Packizard Builder is a PySide6 desktop front end for two related PS5 workflows:

- build/extract AMPR LZ4 asset packs using Drakmor's `ampr_emu` tooling;
- prepare the source path and open the **official PPR-PKG Builder / LibProsperoPkg.Gui** application for PKG creation.

The interface is derived from the uploaded Lazy_AMPR 0.0.1 source and reworked around the Packizard branding. The supplied Packizard artwork is used in the sidebar and as the application icon.

## PKG workflow

Packizard does **not** build the PKG through a private ctypes bridge and does not silently switch to another FPKG implementation. The `Convert to PKG` page delegates that job to the external PPR-PKG Builder application selected by the user — the Drakmor & SvenGDK tool shown in the project reference image (`LibProsperoPKG v0.6.7 — package tool`).

This separation is deliberate:

1. select your copy of `LibProsperoPkg.Gui.exe` / PPR-PKG Builder in Packizard;
2. select a source folder or `.gp5` project and, optionally, an output directory;
3. Packizard reads `param.json` only for a metadata preview and opens PPR-PKG Builder;
4. the source path is copied to the clipboard;
5. configure DRM, SDK, image mode, PFS, Kraken, PlayGo, `libScePubTools.dll` and the other package options in PPR-PKG Builder itself, then press **Build PKG** there.

No undocumented command-line flags are sent to PPR-PKG Builder. The executable is not tracked in this repository. A local source tree may contain a user-supplied copy under `tools/ppr_pkg_builder/`; Windows builds bundle that staged directory automatically. Configure an external copy from the UI or with:

```text
PACKIZARD_PPR_PKG=C:\path\to\LibProsperoPkg.Gui.exe
```

Packizard also looks for the application under `tools/ppr_pkg_builder/`.

## What changed from Lazy_AMPR 0.0.1

- Rebranded the desktop application as **Packizard Builder**.
- Added the supplied Packizard artwork to the sidebar and application resources.
- Updated the light/dark palette to a blue/cyan Packizard theme.
- Renamed the main AMPR entry point from `One Shot` to `Compress` and `Toml list` to `Profiles`.
- Added a dedicated **Convert to PKG** workflow.
- Added folder / GP5 selection and metadata preview from `param.json`.
- Added persistent selection and detection of PPR-PKG Builder.
- Removed the former direct `LibProsperoPkg` native-ABI package builder so the project cannot accidentally produce a PKG through a different path.
- Preserved migration of the original Lazy_AMPR settings and TOML profiles.

## Run from source

Python 3.12 is the validated target inherited from Lazy_AMPR.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

For PKG creation, run Packizard on Windows and select the PPR-PKG Builder executable you intend to use.

## Cross-platform build pipeline

The GitHub repository is kept as a lightweight overlay. CI reconstructs the complete source from the pinned Lazy_AMPR commit `033a85bf2cbc343ed8da81dcef55faac8ba7628a`, applies the compressed Packizard overlay under `ci/`, and injects the Packizard logo before building. The downloadable source snapshot remains self-contained and does not require that bootstrap step.

`.github/workflows/package.yml` builds six native Packizard artifacts on GitHub-hosted runners:

| OS | Intel / x64 | ARM64 |
| --- | --- | --- |
| Windows | `windows-2025` | `windows-11-arm` |
| Linux | `ubuntu-24.04` | `ubuntu-24.04-arm` |
| macOS | `macos-15-intel` | `macos-15` |

Windows outputs are ZIP archives, Linux outputs are AppImage + `tar.gz`, and macOS outputs are ad-hoc signed `.app` bundles inside ZIP archives. Tagged builds (`v*`) collect all six targets into a GitHub Release with a combined SHA-256 manifest.

The supplied `fpkg-gui-0.6.7.zip` is a Windows x86-64/.NET 9 application. It cannot become a native Linux or macOS binary merely by repackaging it. Packizard itself is built natively for all six targets; the exact PPR-PKG Builder remains a Windows tool. A Windows ARM64 Packizard build can launch the x64 PPR executable through Windows x64 emulation when the required x64 .NET 9 Desktop runtime is available.

Because the PPR archive includes third-party binaries and no redistribution license was present in the supplied ZIP, the repository keeps `tools/ppr_pkg_builder/` gitignored. For private CI builds that are authorized to redistribute that archive, set repository variables `FPKG_GUI_ARCHIVE_URL` and `FPKG_GUI_ARCHIVE_SHA256`; the workflow verifies the hash before staging it. For the uploaded 0.6.7 archive the SHA-256 is `7e38d255929e00cdc9e9ec80cdaf44da9f038289f85eb06098331b52b6989896`.

## Tests

```bash
python -m unittest discover -s tests -v
```

The test suite verifies AMPR behavior, state migration and the PPR-PKG Builder launcher/path resolution. It does not claim to validate a PKG produced by an external application that is not present in the test environment.

## Upstream references

- Drakmor, `ampr_emu`: https://github.com/drakmor/ampr_emu
- Drakmor, `ppr-patch`: https://github.com/drakmor/ppr-patch
- Drakmor, `LibProsperoPKG`: https://github.com/drakmor/LibProsperoPKG
- SvenGDK, `LibProsperoPKG` mirror/reference: https://github.com/SvenGDK/LibProsperoPKG

The exact PPR-PKG Builder binary is external to this repository and is not redistributed by Packizard Builder.

## Licensing and attribution

`external/ampr_emu` is distributed under GPL-3.0. Keep its license and the licenses of all bundled dependencies with redistributed builds. PPR-PKG Builder is launched as a separate external program; Packizard does not copy its implementation into this repository.

The original Lazy_AMPR credits are retained in the application: Nazky, Deckerr97, Pippo and Drakmor. SvenGDK is also credited for the PKG tooling referenced by the requested workflow.
