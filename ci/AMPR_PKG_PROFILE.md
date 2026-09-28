# AMPR/LZ4 integrated PKG compatibility profile

Packizard uses one integrated LibProsperoPKG engine for both the manual **Build PKG** page and the optional **Create PKG after LZ4 compression** stage. The compact repository reconstructs that runtime tree in CI; `ci/bootstrap_source.py` applies this profile after the pinned large-package overrides.

## Activation

The profile is automatic and only activates when the prepared source root contains:

- `ampr_assets.index`
- `ampr_emu.index`
- at least one root-level `ampr_assets-*.pak`

Non-AMPR sources retain the normal LibProsperoPKG behavior.

## Inner-PFS policy

For an AMPR tree the builder:

1. keeps CNT-backed `sce_sys` files in the inner PFS as well as generating their normal CNT metadata;
2. stores root-level AMPR volumes and indexes verbatim instead of adding a second Kraken layer;
3. stores `sce_module/**`, `sce_sys/**`, `eboot.bin`, and `eboot.bin.bak` verbatim;
4. leaves other files, including `Media/**`, on the normal classifier/Kraken path.

The CNT, PPR/NAPS, outer-PFS and FullDebug/FIH pipeline remains the same integrated package engine.

## Why the profile is scoped

Runtime testing with PPSA09806 established that simply restoring the 19 CNT-backed `sce_sys` files to `/app0` does not by itself stop the Shell/common-dialog close flow. The raw AMPR-root policy is therefore kept as an AMPR-only compatibility profile rather than changing global package behavior.

## Validation target

For PPSA09806, the next package should show all 82 source files in the inner tree and the nine `ampr_assets-*.pak` volumes as stored/raw rather than Kraken-compressed. On-console acceptance still requires runtime validation with the same payload set used by the known-good direct LZ mount.
