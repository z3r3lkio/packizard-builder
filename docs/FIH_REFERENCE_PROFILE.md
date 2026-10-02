# FIH/CNT reference-backed profile

This profile records Packizard image-validation corrections driven by package images that are known to pass the console image-validation path, rather than by Packizard/LibProsperoPKG self-validation alone.

## Reference findings

The known-good finalized debug image establishes the following FIH relationships:

- `FIH + 0x50` is the inner metadata-base block index (`MetaBase / 0x10000`).
- `FIH + 0xA0` is the inner mount `Ndblock * 0x10000`, not `FIH + 0x90 * 0x10000`.
- `FIH + 0x94` and `FIH + 0x98` are not mirrors for the nwonly layout. The observed values differ by exactly one.
- The pinned builder already computes `innerContentInodes` with `ParentInode >= 0`, which excludes `uroot`. The reference relationship is therefore consistent with:
  - `0x94 = content inodes below uroot`
  - `0x98 = content inodes including uroot = 0x94 + 1`
- `FIH + 0xA8` is a small descriptor-sized value rather than an inner-PFS-sized value. This supports the existing build path that places the `naps_pkg_layout.dat` length in `0xA8` and its SHA3-256 digest in `0xB0`.

The first console retest proved that the `0x94/0x98` split is not sufficient by itself: the corrected package still failed `sceNpDrmContentCheckImage()` / `CheckPfsImage()` with `0x80f00800`.

## CNT system-file class finding

A direct diagnostic-bundle comparison then exposed a stronger mismatch in the embedded CNT entry table.

The known-good package marks backend-authored system files as a distinct entry class:

| Entry | ID | Flags1 | Flags2 |
| --- | ---: | ---: | ---: |
| `license.dat` | `0x0400` | `0x80000000` | `0x00003000` |
| `license.info` | `0x0401` | `0x80000000` | `0x00004000` |
| `nptitle.dat` | `0x0402` | `0x80000000` | `0x00003000` |
| `npbind.dat` | `0x0403` | `0x80000000` | `0x00003000` |
| `uds/npbind.dat` | `0x2020` | `0x80000000` | `0x00003000` |
| `trophy2/npbind.dat` | `0x2021` | `0x80000000` | `0x00003000` |

The pinned LibProsperoPKG revision recognizes those fixed IDs but its generic `Flags1For` / `Flags2For` path classifies them as ordinary media/data (`0x08000000`, `0`). Packizard's profile corrects only that classification.

The profile does **not** synthesize `license.dat`, `license.info`, `nptitle.dat`, or `npbind.dat`. LibProsperoPKG itself treats these as backend-authored / backend-signed inputs; inventing payloads would replace evidence with fabricated authentication data.

## Safety properties

The profile is deliberately narrow:

- it corrects the nwonly FIH inode split (`0x94` / `0x98`);
- it corrects only CNT entry-class flags for known backend-authored system files;
- it does not change NAPS generation, LZ4, outer-PFS encryption, EKPFS/EEKPFS, IMAGE_KEY generation, payload bytes, or digest algorithms;
- every rewrite is idempotent;
- every rewrite requires an exact pinned-source preimage and fails closed when the upstream source changes.

## Acceptance criterion

The profile remains experimental until a package produced with it progresses beyond:

`PrepareProcessLaunchDir -> sceNpDrmContentCheckImage -> CheckPfsImage`

and successfully mounts `/app0`.

If `0x80f00800` remains after this CNT entry-class correction, the next comparison target is the remaining authentication path: outer-PFS ciphertext/superblock, CNT general digests and IMAGE_KEY/EEKPFS relationships.
