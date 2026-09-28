# Packizard AMPR/LZ4 PKG compatibility profile

Packizard uses one integrated LibProsperoPKG engine for both **Build PKG** and **Compress → PKG**. A source tree is treated as a Packizard AMPR/LZ4 tree when it contains the AMPR indexes plus at least one root `ampr_assets-*.pak` volume.

For those trees the reconstructed engine applies a compatibility policy without changing the already-working LZ4 data itself:

- root AMPR index/volume files, `eboot.bin`, `sce_module/**` and `sce_sys/**` compatibility payloads are stored verbatim instead of being re-wrapped in Kraken;
- inherited `sce_sys/playgo*` data is not copied into the rebuilt inner image;
- source `playgo*` files are also excluded from the CNT/media pass, so original-package scenario/chunk metadata cannot be mixed with the regenerated PlayGo tables;
- the packaged `param.json` clears `versionFileUri` in memory while preserving the source file and `attribute3`;
- non-AMPR package builds keep the normal LibProsperoPKG behavior.

## Large-title I/O and progress

AMPR volumes are immutable on-disk inputs, so the package path now passes their real source paths directly into the inner-image assembler. It no longer clones the complete AMPR tree into temporary files before writing the image. This removes a full redundant read/write pass that was especially visible on 50–150+ GiB titles.

The disk-backed inner-image writer reports progress through the existing LibProsperoPKG logger, which `Packizard.PkgBridge` already forwards to Packizard. The log includes:

- input file count and total GiB;
- percentage and GiB written;
- effective MiB/s;
- estimated time remaining;
- current `/app0` path;
- explicit completion timing before NAPS/outer-PFS processing continues.

Example:

```text
Inner image input: 37 files, 114.62 GiB. AMPR direct-I/O enabled; redundant staging copy skipped.
Inner image write: 37.4% — 42.87 / 114.62 GiB — 286.3 MiB/s — ETA 00:04:17 — /ampr_assets-0003.pak
Inner image write complete: 114.62 GiB in 00:06:51.
Inner image ready: 114.63 GiB; generating NAPS metadata.
```

Progress reporting is throttled so the GUI remains responsive and the log is not flooded. The original two-argument `BuildToFile(payloads, outputPath)` API remains available; Packizard uses the callback overload only when it wants telemetry.
