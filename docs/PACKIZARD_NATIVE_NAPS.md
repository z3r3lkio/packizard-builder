# Packizard-native NAPS design

Packizard owns the NAPS path used by the integrated PKG builder. The goal is not to patch individual
`u2c` overflows after they occur; the planner makes an unencodable topology impossible by construction
and refuses lossy fallbacks.

## Why the old topology failed

Real game trees exposed several independent failure modes:

- ordinary file boundaries created too many DATA/CblockInfo records inside a small logical window;
- a compressed file was at one point collapsed into one descriptor even though the encoder worked in
  256 KiB blocks;
- `u2c` was derived from descriptor start offsets rather than logical interval coverage;
- RUN bases inflated CblockInfo indexes and therefore the one-byte local `u2c` deltas;
- physical compressed size leaked into logical mount geometry;
- padding could overlap the final partial DATA interval;
- zero-length files could manufacture descriptors;
- 24-bit/40-bit fields could previously be masked instead of rejected explicitly.

The two observed real-package signatures were:

```text
u2c delta 524   (real U-block 96431)
u2c delta 19945 (real U-block 8463)
```

The second is the decisive dense-tree case: roughly twenty thousand CblockInfo indexes appeared inside
one 8-U-block window. No correct byte cast, modulo or wider temporary fixes that layout; the topology
itself had to change.

## Native pipeline

```text
filesystem / AFID logical order
        |
        v
PackizardNativeDataStream
        |
        |-- ordinary files coalesce across file boundaries
        |-- <= 256 KiB coding blocks
        |-- raw/module payloads are explicit codec barriers
        |-- exact logical + physical geometry recorded once
        v
PackizardNativeNapsEngine
        |
        |-- logical interval plan
        |-- RUN scheduling (first/gap/storage transition/periodic re-anchor)
        |-- DATA -> padding -> metadata -> terminator coverage
        |-- one CblockInfo plan
        |-- interval-based U-block lookup
        |-- per-group u2c budget analysis
        v
PackizardNativeNapsValidator
        |
        |-- header widths
        |-- fidx 40-bit range/monotonicity
        |-- u2c base/delta targets
        |-- CblockInfo field widths
        v
PackizardNativeNapsWriter
        |
        |-- Packizard-owned binary header
        |-- outer digest / shuffle sections
        |-- fidx
        |-- uint24 base + seven uint8 deltas
        |-- 9-byte CblockInfo packing
        v
naps_pkg_layout.dat
```

`ProsperoNwonlyNapsGenerator`, `ProsperoNapsLayoutBuilder` and the upstream NAPS serializer are not used
by the native package path. LibProsperoPkg remains the generic PKG/PFS/crypto substrate and its NAPS
model types can still be used as DTOs or by tests to parse the bytes Packizard emitted.

## Canonical DATA blocks

The key rule is that a normal filesystem boundary is **not** a compression-block boundary.

For example, 20,000 files of 64 bytes contain only 1,280,000 logical bytes. Packizard emits about five
256 KiB DATA blocks, not 20,000 blocks. A canonical block records the first/last file it intersects for
diagnostics, but NAPS sees the logical byte stream rather than the object count.

Raw or signed-module content remains a codec barrier. That preserves verbatim bytes and known physical
alignment rules without reintroducing one-block-per-normal-file behavior.

## Logical intervals, not descriptor starts

Every real STD descriptor carries an interval:

```text
[LogicalStart, LogicalEnd)
```

For each U-block start `u * 0x40000`, the planner selects the STD interval that actually contains that
byte. This handles:

- a DATA block that begins before an U-block boundary and crosses it;
- a short raw barrier inside an otherwise canonical stream;
- one padding descriptor covering several U-blocks;
- metadata blocks at their exact logical positions.

The old approximation, "first STD whose start is >= target", can skip the descriptor that already
covers the target and is no longer used.

## u2c contract

One `u2c` record represents eight logical U-blocks:

```text
uint24 base
uint8  delta[7]
```

For every group Packizard computes the exact selected CblockInfo indexes before serialization and
requires:

```text
base <= 0xFFFFFF
0 <= target[i] - base <= 255
selected indexes are monotonic
selected targets are inside CblockInfo[]
```

No truncation, `% 256`, clamping or wrapping is permitted. A violation is a planner bug/topology
problem and produces a diagnostic containing group, U-block range, base/max indexes, region names and
RUN/STD counts.

A final partial group zero-fills nonexistent delta slots. When `NumUBlocks` is an exact multiple of
8, the format's trailing group maps to the terminator explicitly.

## Logical versus physical geometry

Two coordinate systems remain separate throughout the build:

- **logical**: file offsets, DATA end, metadata base, mount size, U-block coverage;
- **physical**: encoded DATA offsets/sizes, block-info location, compressed metadata location.

Compression may make `pfs_image.dat` much smaller than the reconstructed mount. Physical size must
never pull metadata into the logical DATA interval.

## Current regression gates

CI covers, among other cases:

1. cross-file canonical block formation and byte-for-byte decode;
2. raw/module barriers;
3. memory-backed vs file-backed deterministic inner image and NAPS output;
4. 20,000 tiny files succeeding with O(U-blocks), not O(files), CblockInfo density;
5. uint24 `u2c` bases above `0xffff`;
6. highly compressible DATA where physical size is far below logical size;
7. zero-byte files;
8. package-stage cleanup on injected failures;
9. sources larger than 2 GiB without payload-sized memory allocation.

Future console-derived fixtures should be added as binary-golden parse/encode cases, especially around
RUN semantics, raw transitions, metadata padding and very large physical offsets.
