# Third-party notices

Packizard Builder is the integration application. It includes or builds against upstream components that retain their own copyright and license terms.

## Lazy_AMPR / AMPR

Packizard is derived from the user-supplied Lazy_AMPR 0.0.1 source baseline and retains the AMPR workflow and associated upstream attribution.

Relevant projects:

- https://github.com/Nazky/Lazy_AMPR
- https://github.com/drakmor/ampr_emu

`external/ampr_emu/LICENSE` and bundled dependency license files must remain present in redistributed builds.

## LibProsperoPKG

Packizard Builder 0.2.0 integrates **LibProsperoPKG v2.6.0** through the first-party `Packizard.PkgBridge` helper.

- upstream repository: https://github.com/SvenGDK/LibProsperoPKG
- pinned main snapshot: `v2.6.0`
- pinned commit: `748eabf1b7d17819528cabf367d8e27109d8fce3`
- upstream license: **GPL-3.0-or-later**

The helper is compiled from source against that pinned upstream revision for each release architecture. Release packages copy the upstream `LICENSE` alongside the application under `licenses/LibProsperoPKG/` (or the corresponding macOS Resources directory).

Packizard does not bundle or launch the standalone PPR-PKG Builder GUI. The current reference GUI version is `0.6.8`; PKG creation is performed through the integrated bridge built from the separately versioned, pinned public LibProsperoPKG source snapshot.

## Acknowledgements

Thanks to Nazky, Deckerr97, Pippo, drakmor, SvenGDK and the contributors to the upstream projects whose work and research underpin these workflows.
