# Packizard Builder

Packizard Builder is an integrated desktop workflow for PS5 application backups and homebrew packaging. It combines the AMPR/LZ4 compression flow inherited from Lazy_AMPR with an in-app PKG build flow powered by **LibProsperoPKG**.

## What changed in 0.2.0

- **PKG creation is integrated.** Packizard no longer launches `LibProsperoPkg.Gui` / PPR-PKG Builder as a second application.
- **Compress → PKG in one job.** The Compress page has a **Create PKG after LZ4 compression** option. When enabled, the successful AMPR output becomes the source for the PKG stage automatically.
- **Build PKG remains available.** It is now the manual/advanced UI for the same integrated engine, not an external-program launcher.
- **Packizard.PkgBridge.** A small first-party .NET helper is bundled with every release and calls `ProsperoPackageBuilder.Build(...)` in-process inside the helper. Python/PySide communicates with the helper over a structured JSON event stream.
- **Native builds on six targets.** Windows x64/ARM64, Linux x64/ARM64, macOS Intel x64 and Apple Silicon ARM64 all bundle a bridge built for the same target architecture.
- **Branding and credits.** The sidebar uses the complete Packizard lizard artwork at higher resolution. The Credits page identifies **Packizard** as the integrator and keeps upstream acknowledgements compact at the bottom.

## Integrated PKG engine

The current PPR-PKG Builder reference version is **0.6.8**. Packizard mirrors its documented defaults where the public LibProsperoPKG API exposes the same behavior (notably application DRM `standard`) and verifies finished packages with the upstream structural acceptance validator. The exact 0.6.8 GUI binary is not launched or bundled.

Packizard tracks the latest **validated public upstream main snapshot** of:

- `SvenGDK/LibProsperoPKG`
- validated upstream snapshot: **v2.6.0**
- pinned commit: `748eabf1b7d17819528cabf367d8e27109d8fce3`

The pin is deliberate: a Golden Build must be reproducible. The reference GUI version and the public source version use different version schemes, so Packizard records them separately rather than pretending that `2.6.0` and `0.6.8` are the same release. A scheduled GitHub Actions workflow checks the upstream `main` branch and opens a `feature/libprospero-*` PR against `UAT` whenever its commit changes. The candidate snapshot is only promoted after the complete test/build matrix passes. This keeps Packizard on the newest public upstream code that has passed Packizard UAT without silently changing the package engine underneath an existing Golden Build.

The source pin is stored in:

- `bridge/LIBPROSPERO_VERSION`
- `bridge/LIBPROSPERO_REF`

The helper project is under `bridge/Packizard.PkgBridge/` and references the pinned upstream source checkout at build time.

## Compress → PKG

1. Load the game/application folder in **Compress**.
2. Configure LZ4/AMPR as usual.
3. Enable **Create PKG after LZ4 compression**.
4. Review the PKG metadata/options shown underneath the tick.
5. Start processing.
6. Packizard completes the AMPR/LZ4 output first. Only after that stage succeeds does it run the integrated PKG engine against the compressed output.

If compression fails or is cancelled, the PKG stage is not started.

## Build PKG

The dedicated page builds directly from an already prepared source folder and exposes the options provided by the validated LibProsperoPKG snapshot, including package mode, debug/metadata output, application type, DRM metadata override, fake-signing, license-free debug mode, title/content metadata and passcode.

No external GUI is spawned.

## Development build prerequisites

- Python 3.12+
- dependencies from `requirements-build.txt`
- .NET 10 SDK
- Git (to fetch the pinned LibProsperoPKG source for a local bridge build)

Prepare a bridge for the current machine with, for example:

```bash
python scripts/prepare_pkg_bridge.py --rid linux-x64
```

Supported release RIDs are:

- `win-x64`
- `win-arm64`
- `linux-x64`
- `linux-arm64`
- `osx-x64`
- `osx-arm64`

The normal platform build scripts call this step automatically.

## Branch and release policy

Development follows:

```text
feature/* -> PR -> UAT -> six-platform Golden Build -> PR -> main
```

`main` is the release branch. New work starts from `UAT`, is implemented in a `feature/*` branch, and is merged back to `UAT` by PR. A promotion from `UAT` to `main` is only appropriate after the Golden Build job verifies all six platform artifacts and their SHA-256 manifests.

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```

The CI verification job also compiles and probes `Packizard.PkgBridge`, so a LibProsperoPKG API break is detected before the platform matrix is allowed to build release artifacts.

## Upstream projects and attribution

Packizard is the integrator of this application. It builds on upstream work, including:

- Lazy_AMPR by Nazky and contributors: https://github.com/Nazky/Lazy_AMPR
- AMPR emulation/tooling by drakmor: https://github.com/drakmor/ampr_emu
- LibProsperoPKG by SvenGDK: https://github.com/SvenGDK/LibProsperoPKG
- related PS5 packaging research/tooling by drakmor: https://github.com/drakmor/LibProsperoPKG

See `THIRD_PARTY_NOTICES.md` for redistribution and license details.

## License notes

The bundled AMPR tooling and LibProsperoPKG carry their own upstream licenses. The tracked LibProsperoPKG v2.6.0 snapshot is GPL-3.0-or-later. Release packages preserve its license and this repository ships the Packizard bridge source used to invoke it. Keep all upstream license files and notices with redistributed builds.
