# FIH / PFS image validation

Packizard can build PS5 finalized debug images that are structurally self-consistent and install correctly, while a console can still reject the image at launch time during `sceNpDrmContentCheckImage()` / `CheckPfsImage()`.

This document defines the diagnostic boundary for that failure class. It deliberately does **not** treat Packizard/LibProsperoPKG self-validation as proof of console acceptance.

## Current evidence

Observed launch failures stop in the package-image validation path before `/app0` is mounted and before the game executable is started:

- `sceNpDrmContentCheckImage -> 0x80f00800`
- `CheckPfsImage -> 0x80f00800`
- `AppSubcontainerCheckAndGetPkgHeaderInfo -> 0x80f00800`
- `PrepareProcessLaunchPkg -> 0x80f00800`

That makes FIH/PFS/CNT geometry and authentication metadata the current investigation target. NAPS and Packizard LZ4 are not changed by this diagnostic milestone.

## Pinned-engine semantic inconsistencies

The pinned LibProsperoPKG revision is `748eabf1b7d17819528cabf367d8e27109d8fce3`.

Two field interpretations are inconsistent inside that revision and must be resolved against a known-good debug image rather than by assumption:

1. `FIH + 0xA8` / `FIH + 0xB0`
   - `ProsperoPkgLayout` documents `0xA8` as the logical size of the inner PFS image and `0xB0` as the digest of that inner image.
   - `ProsperoPkgBuilder` currently supplies `naps_pkg_layout.dat` length and `SHA3-256(naps_pkg_layout.dat)` to those fields.
2. `FIH + 0x94` / `FIH + 0x98`
   - `ProsperoPkgLayout` describes them as outer-PFS metadata block counts.
   - `ProsperoFihBuilder` currently writes the threaded inner content-inode count into both fields on the nwonly path.

The new Packizard inspector therefore reports these values without silently choosing one interpretation.

## Inspector

Run:

```text
python scripts/inspect_pkg_image.py game.pkg
```

To compare a Packizard image to a known-good image:

```text
python scripts/inspect_pkg_image.py packizard.pkg --reference known-good.pkg
```

Optionally write JSON:

```text
python scripts/inspect_pkg_image.py packizard.pkg --reference known-good.pkg --output fih-compare.json
```

The report includes:

- FIH variant/version, PFS offset/size, embedded CNT offset;
- FIH geometry fields (`0x50`, `0x60`, `0x68`, `0x90`, `0x94`, `0x98`, `0x9C`, `0xA0`, `0xA8`, `0xF0`, `0xF8`);
- digest slots `0x30`, `0x70`, `0xB0`, `0xD0`;
- embedded CNT flags, content id/type, body geometry and PFS pointer fields;
- CNT entry metadata and SHA-256 for entry payloads, including image-key/digest entries;
- cross-container invariants and semantic warnings;
- field-by-field and entry-by-entry differences when a reference image is supplied.

## Acceptance criterion for the next correction

Do not change FIH authentication fields merely to satisfy Packizard's own parser. A correction should be backed by at least one known-good package comparison showing which field/preimage differs, followed by a generated image that passes the console package-image check and proceeds beyond `CheckPfsImage()`.
