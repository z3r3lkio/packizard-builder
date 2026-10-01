# Third-party notices

Packizard Builder contains or builds against third-party components that retain their own copyright and license terms. Packizard's application source, engine integration, UI and build pipeline are maintained directly in this repository; third-party notices below apply only to the components identified here.

## PS5 runtime compatibility implementation

The Packizard PS5 Runtime is maintained in-repository under `packizard_runtime/ps5/packizard_ps5_runtime`. Its current sceAmpr ABI compatibility implementation contains source derived from the public `drakmor/ampr_emu` project, so the corresponding GPL attribution and license are retained with that source and redistributed runtime component.

- upstream project: https://github.com/drakmor/ampr_emu
- retained license: `packizard_runtime/ps5/packizard_ps5_runtime/LICENSE`

The old duplicate `external/ampr_emu` source tree is not part of the Packizard build and has been removed. The `libSceAmpr.sprx` filename is retained solely because games expect that compatibility ABI name.

## Auto-Backpork

Packizard includes Auto-Backpork tooling under `external/Auto-Backpork/`. Its source, notices and dependency terms remain attributable to their respective upstream authors.

## LibProsperoPKG

Packizard Builder integrates **LibProsperoPKG v2.6.0** through the first-party `Packizard.PkgBridge` helper.

- upstream repository: https://github.com/SvenGDK/LibProsperoPKG
- pinned snapshot: `v2.6.0`
- pinned commit: `748eabf1b7d17819528cabf367d8e27109d8fce3`
- upstream license: **GPL-3.0-or-later**

The bridge is compiled from source against that pinned revision for each release architecture. Release packages preserve the upstream `LICENSE` under the application license resources.

Packizard does not bundle or launch the standalone PPR-PKG Builder GUI. The current reference GUI version is `0.6.8`; package creation is performed through the integrated bridge.

## Acknowledgements

Packizard acknowledges Nazky, Deckerr97, Pippo, drakmor, SvenGDK and other public PS5 tooling contributors whose research informed earlier and current workflows. These acknowledgements do not imply that Packizard's current build depends on another application repository.
