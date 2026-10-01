# Third-party notices

Packizard Builder contains or builds against third-party components that retain their own copyright and license terms. Packizard's application source, engine integration, UI and build pipeline are maintained directly in this repository; third-party notices below apply only to the components identified here.

## AMPR-compatible runtime/tooling components

Packizard retains selected compatibility components and interfaces originating from the public `drakmor/ampr_emu` project while the Packizard-owned engine and runtime migration is completed.

- upstream repository: https://github.com/drakmor/ampr_emu
- license file: `external/ampr_emu/LICENSE`

The upstream license and bundled dependency license files must remain with redistributed copies of those components.

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
