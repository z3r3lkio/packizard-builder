# FIH reference-backed profile

This profile records the first Packizard FIH/PFS correction driven by a package image that is known to pass the console image-validation path rather than by Packizard/LibProsperoPKG self-validation alone.

## Reference findings

The reference finalized debug image establishes the following field relationships:

- `FIH + 0x50` is the inner metadata-base block index (`MetaBase / 0x10000`).
- `FIH + 0xA0` is the inner mount `Ndblock * 0x10000`, not `FIH + 0x90 * 0x10000`.
- `FIH + 0x94` and `FIH + 0x98` are not mirrors for the nwonly layout. The observed values differ by exactly one.
- The pinned builder already computes `innerContentInodes` with `ParentInode >= 0`, which excludes `uroot`. The reference relationship is therefore consistent with:
  - `0x94 = content inodes below uroot`
  - `0x98 = content inodes including uroot = 0x94 + 1`
- `FIH + 0xA8` is a small descriptor-sized value rather than an inner-PFS-sized value. This supports the existing build path that places the `naps_pkg_layout.dat` length in `0xA8` and its SHA3-256 digest in `0xB0`; the older comments that call these the logical inner-PFS size/digest are misleading.

The pinned LibProsperoPKG revision currently writes the same nwonly inode count to both `0x94` and `0x98`. Packizard applies a deterministic source profile before building `Packizard.PkgBridge` so `0x98` includes the missing `uroot` inode while retaining upstream behavior for non-nwonly images.

## Safety properties

The profile is deliberately narrow:

- it modifies only the two nwonly FIH inode-count fields;
- it does not change NAPS generation, LZ4, PFS encryption, EKPFS/EEKPFS, image-key generation, or digest algorithms;
- the patch is idempotent;
- it refuses to apply if the pinned upstream source no longer matches the expected preimage, forcing an explicit review when the LibProsperoPKG pin changes.

## Acceptance criterion

A package built with this profile still needs console validation. The fix is considered confirmed only when a generated debug image proceeds beyond `sceNpDrmContentCheckImage()` / `CheckPfsImage()` and mounts `/app0`.
