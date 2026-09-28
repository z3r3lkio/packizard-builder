# Integrated PKG verbose telemetry

The integrated LibProsperoPKG path now reports the expensive inner-image stages instead of leaving the GUI apparently idle.

Expected log sequence for large AMPR/LZ4 builds:

```text
Preparing PS5 inner image (data-first)...
Inner image input: 464 files, 59.87 GiB. AMPR direct-I/O enabled; redundant staging copy skipped.
Inner preparation: classifying and encoding 464 payload files...
  [   1/464] RAW       2048.00 MiB  /ampr_assets-0000.pak
  [   2/464] KRAKEN      85.12 MiB  /some/loose/file.bin
       -> 47.31 MiB (55.6% of source) in 3.8s @ 22.4 MiB/s
...
Inner preparation complete: 464 files (... raw, ... Kraken), 59.87 GiB input -> ... GiB stored in ...s @ ... MiB/s.
Inner metadata: data region = ... blocks; building dirents, inodes and AFID tables...
Inner metadata plaintext ready: ... KiB, Ndblock=.... Assembling data-first image...
Inner image metadata: Kraken-encoding ... KiB metadata region...
Inner image metadata encoded: ... KiB -> ... KiB.
Inner image write starting: ... GiB planned across ... payloads.
Inner image write: 37.4% — ... GiB — ... MiB/s — ETA ... — /ampr_assets-0003.pak
Inner image write complete: ... GiB in ...
Inner image ready: ... GiB; generating NAPS metadata.
NAPS layout generated: ... bytes; calculating PlayGo/FIH metadata.
Preparing PS5 outer PFS (encrypted + signed)...
```

This keeps the existing bridge protocol: messages travel through the LibProsperoPKG logger already consumed by `Packizard.PkgBridge`, so no external PPR GUI process is required.
