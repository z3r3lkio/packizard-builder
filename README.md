# Packizard Builder

Packizard Builder is a self-contained desktop workflow for PS5 application backups, Packizard Engine compression and integrated PKG creation.

## Architecture

Packizard now builds directly from source stored in this repository. The build no longer reconstructs the application from another project or applies an overlay at CI time.

The application is split into three first-class components:

- **Packizard Engine** — scanning, profiling, packing, container/index handling and verification.
- **Packizard PS5 Runtime** — the runtime implementation used to read Packizard-packed assets on the target system.
- **Packizard PKG integration** — the first-party `Packizard.PkgBridge` wrapper around the pinned LibProsperoPKG source snapshot.

Windows releases are built as a single `Packizard-Builder.exe`. Worker programs, runtime resources and the PKG bridge are embedded in the executable and extracted only into PyInstaller's private runtime directory when required.

## Compress → PKG

1. Load the game/application folder in **Compress**.
2. Select the Packizard compression level and profile.
3. Optionally enable **Create PKG after Packizard compression**.
4. Review the PKG metadata/options.
5. Start processing.
6. Packizard completes the Packizard Engine output first and only then invokes the integrated PKG engine.

If compression fails or is cancelled, the PKG stage does not start.

## Integrated PKG engine

Packizard integrates **LibProsperoPKG v2.6.0** through `Packizard.PkgBridge`.

- upstream repository: `SvenGDK/LibProsperoPKG`
- pinned release snapshot: `v2.6.0`
- pinned commit: `748eabf1b7d17819528cabf367d8e27109d8fce3`
- reference PPR-PKG Builder GUI version: `0.6.8`

The GUI application is not launched or bundled. PKG work is performed by the Packizard bridge against the pinned public library source. The pin is upgraded only after the candidate revision passes Packizard UAT and the complete build matrix.

The source pin is stored in:

- `bridge/LIBPROSPERO_VERSION`
- `bridge/LIBPROSPERO_REF`

## Development prerequisites

- Python 3.12+
- dependencies from `requirements-build.txt`
- .NET 10 SDK
- Git, used to fetch the pinned LibProsperoPKG source for bridge builds

Prepare the bridge manually when needed:

```bash
python scripts/prepare_pkg_bridge.py --rid linux-x64
```

Supported release RIDs are `win-x64`, `win-arm64`, `linux-x64`, `linux-arm64`, `osx-x64` and `osx-arm64`.

## Build

Windows:

```powershell
python -m venv .venv312
.\.venv312\Scripts\python -m pip install -r requirements-build.txt
.\build_windows.ps1 -Architecture x64
```

The Windows release archive contains one application executable: `Packizard-Builder.exe`.

Linux and macOS use `build_linux.sh` and `build_macos.sh` respectively.

## Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
```

CI also compiles and probes `Packizard.PkgBridge` and builds the platform release matrix before a Golden Build can pass.

## Branch and release policy

```text
feature/* -> PR -> UAT -> Golden Build -> PR -> main
```

`main` is the release branch. New work starts from `UAT`, is implemented on a `feature/*` branch and returns to `UAT` through a pull request. Promotion from `UAT` to `main` requires a successful Golden Build.

## Third-party components

Packizard retains the licenses and notices for third-party components that remain part of the source or release build, including:

- AMPR-compatible runtime/tooling components from `drakmor/ampr_emu` where still retained for compatibility;
- Auto-Backpork tooling and its upstream dependencies;
- LibProsperoPKG by SvenGDK.

See `THIRD_PARTY_NOTICES.md` and the license files shipped with the corresponding components.
