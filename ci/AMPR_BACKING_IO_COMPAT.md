# AMPR backing I/O compatibility patch

This feature branch carries a general compatibility patch for the AMPR runtime
used by Packizard. It is intentionally backend-oriented and contains no title
IDs, game-name checks, or per-title behavior.

## Why this patch

The current `drakmor/ampr_emu` runtime already has two important protections:

- exact synchronous reads for manifest/header data via `pread_exact()`, including
  retry of short `pread()` results;
- validation that each physical backing range stays inside the validated
  `payloadBegin..payloadEnd` extent before an AIO request is submitted.

The remaining compatibility gap is the physical backing AIO path. A mounted
filesystem can expose identical files and hashes while still differing in its
support or behavior for the kernel AIO interface. Today, an AIO submission,
completion, or short-read failure is propagated as a pack I/O failure.

The patch keeps AIO as the fast path and adds a generic fallback:

1. submit the normal backing AIO request;
2. if the backing AIO fails or completes short, retry the same physical
   `fd + offset + length` range using the runtime's existing exact `pread()`
   helper;
3. preserve cancellation semantics: explicit `ECANCELED` is not retried;
4. only report failure if both AIO and exact positional I/O fail.

For grouped physical-page reads, each failed/short request is retried
independently so a single transport failure does not poison sibling requests
that can be recovered synchronously.

## Scope

The change applies equally to:

- ordinary folder-backed games;
- ExFAT or other mounted-image backends;
- PFS-backed content;
- USB/storage layers;
- future mount implementations.

It is not specific to PPSA15595/Tokon. Tokon is only the first regression case
because the folder-backed LZ succeeds while an ExFAT image with the same
984 files, sizes and SHA-256 values reaches `eboot.bin` and aborts.

## Build

Run the **AMPR Backing I/O Compatibility Build** workflow manually on this
branch. The workflow pins the same public `ampr_emu` and PS5 payload SDK
revisions as upstream, applies `ci/ampr_emu_io_compat.patch`, and uploads
`libSceAmpr-io-compat-runtime-variants`.

The patch is pinned to:

- `drakmor/ampr_emu@cfa85df379f6eeeb165d7badf9b648e266fe77b7`
- `ps5-payload-dev/pacbrew-repo@19718edd6fd5e9447f38b7fb59ebbacc136b5421`

## Validation

Do not replace the bundled Packizard runtime until the patched SPRX has passed
console validation.

Minimum matrix:

| Case | Expected |
| --- | --- |
| Known-good folder LZ | no regression |
| Same content in ExFAT image | succeeds or produces a more specific backing-I/O failure |
| Second known-good LZ title | no regression |
| Second ExFAT title | no regression / improved compatibility |
| Explicit cancellation/shutdown | remains cancellable; no synchronous retry after ECANCELED |

If ExFAT starts working while folder LZ remains unchanged, the result strongly
supports an AIO/backend compatibility issue. If both still behave identically,
the next target is the mount layer's stat/mmap/read semantics rather than the
AMPR packed-data bytes.
