# Packizard-native NAPS design

This document defines the invariants for Packizard's own `naps_pkg_layout.dat` planner/generator.
The goal is not to silence a particular `u2c delta` exception. The goal is to make every logical,
physical and bit-width relationship explicit and testable before a PKG is emitted.

## Why the old design fails

`u2c` maps each group of eight logical 256 KiB U-blocks into the `CblockInfo` table. The binary
shape is a 24-bit base index plus seven 8-bit deltas. For a real U-block `u` in a group with base
`b`, the selected `CblockInfo` index must therefore satisfy:

```
0 <= first[u] - b <= 255
```

A value such as `524` or `19945` is not something that can be clamped, wrapped or truncated. It
means the planned topology cannot be represented by the descriptor being written.

The observed real-world failure

```
real U-block 8463
first = 29493
base  = 9548
delta = 19945
numUBlocks = 8471
numCblockInfo = 29503
```

is especially diagnostic. U-block 8463 lies in the group beginning at U-block 8456. The planner
therefore jumps almost twenty thousand `CblockInfo` indices inside one eight-U-block window.
That is a topology discontinuity, not a normal compression-size effect.

## Coordinate systems must never be mixed

Packizard carries two independent geometries:

1. **Logical mount geometry** — uncompressed offsets visible to the PFS mount and described by
   `fidx`, U-block numbers and metadata logical placement.
2. **Physical encoded geometry** — compressed/stored byte offsets inside `pfs_image.dat`.

These are intentionally different. Compression can make the physical DATA region dramatically
smaller than its logical mount span.

The previous path derived the metadata logical base from the physical compressed DATA length while
file logical offsets were accumulated from uncompressed file sizes. With sufficiently compressible
DATA this places metadata logically inside the still-live DATA address range. Sorting Cblock records
by logical position while retaining their physical/emission indices can then make `first[u]` jump
from an early DATA index to a late metadata/tail index in a single u2c group.

Native invariant:

```
DataEndLogical <= MetaBaseLogical <= MountSizeLogical
```

`MetaBaseLogical` is derived only from logical DATA length/alignment/reserve. Physical block-info and
metadata byte offsets are derived only from encoded DATA length/alignment. A build aborts if these
coordinate systems cross.

## Every class of u2c failure we guard

### 1. Logical/physical geometry collapse

Metadata base or mount size is calculated from compressed physical bytes instead of logical bytes.
Result: metadata overlaps DATA in logical space and `first[u]` can jump thousands of indices.

Guard: explicit logical/physical fields plus `MetaBaseLogical >= DataEndLogical` validation.

### 2. Excess CblockInfo density inside eight U-blocks

Even with correct coordinates, more than 255 CblockInfo index steps can occur between the first and
last selected U-block in one group. Sources include pathological numbers of tiny file segments,
fragmentation, or an encoder that manufactures multiple records for boundaries that do not need
them.

Guard: a pre-serialization budget report for every group (`base/min/max/span/std/run`). No clamp.

### 3. RUN-base inflation

RUN records consume the same CblockInfo index space as ordinary block records. Opening a RUN at every
file, at every stored/compressed transition, and again periodically can make an otherwise valid
layout exceed the one-byte delta budget.

Guard: RUNs are explicit plan records; their count is included in the group budget. Adding a RUN is
never treated as a free operation.

### 4. Wrong block granularity

Treating an entire compressed file as one block, inventing a block per filesystem object regardless
of logical U-block geometry, or losing the encoder's true block map changes which CblockInfo should
serve each U-block.

Guard: Packizard records exact DATA block geometry (`logical offset`, `physical offset`, encoded
length, stored/Kraken decision, chunk split) in a canonical intermediate representation.

### 5. Non-monotonic logical-to-Cblock ordering

If Cblocks are emitted in one order but later sorted by logical offset, the selected index can move
backward or jump across unrelated late records. Overlapping DATA/metadata is one cause; an invalid
plan order is another.

Guard: monotonic logical checks before the Cblock walk and negative-delta rejection.

### 6. Partial final u2c group

Unused slots in the last group are not real U-blocks. Pointing those slots at a distant terminator can
create a fake overflow even when every real U-block is representable.

Guard: unused deltas are zero. Validation only budgets real U-blocks.

### 7. Incorrect u2c packing

One u2c entry is modeled as one uint24 base followed by seven delta bytes. A previous experimental
builder phase-shifted the bytes across adjacent groups. That disagrees with the descriptor model and
independent decoders and can manufacture incorrect bases/deltas.

Guard: native code constructs `base + seven deltas` directly and round-trips all 10 bytes.

### 8. 24-bit base/count overflow

Header U-block count, outer-block count, CblockInfo count/base indices are finite-width fields. A
large package can exceed them independently of the 8-bit delta constraint.

Guard: explicit 24-bit checks before serialization.

### 9. 40-bit fidx overflow

File/mount logical offsets in fidx are 40-bit values.

Guard: reject offsets outside `0..0xffffffffff`.

### 10. CblockInfo field overflow

RUN physical bases, tweak indices, compressed-offset fragments, uncompressed-offset fragments and
chunk lengths have independent bit widths. A layout can satisfy u2c and still be unencodable here.

Guard: every field is range-checked at the model/codec boundary. No masking of an oversized source
value is allowed.

### 11. Zero-length files and duplicate logical starts

A zero-byte filesystem object has an fidx/inode identity but no DATA U-block. Manufacturing a DATA
Cblock for it creates duplicate starts and can destabilize u2c selection.

Guard: zero-length files contribute no DATA block.

### 12. Padding/metadata collision

The final partial DATA block, padding/hole descriptor and first metadata block must not claim the same
logical U-block accidentally.

Guard: the planner owns a single logical interval map and rejects overlap before Cblock generation.

### 13. Raw/Kraken transition without a valid cursor anchor

A change in physical stream semantics can require a RUN re-anchor. Missing it produces incorrect
physical reconstruction even if u2c indices fit; adding too many RUNs can cause case 3.

Guard: cursor reconstruction is part of round-trip tests, and the RUN scheduler is budget-aware.

### 14. Section-count/alignment disagreement

Real implementations disagree on some large-layout details (especially trailing u2c count/section
alignment). A serializer can therefore produce a self-consistent blob that is not console-correct.

Guard: Packizard will keep binary-codec assumptions isolated behind golden-fixture tests. Self
round-trip is necessary but not sufficient.

### 15. CblockInfo bitfield disagreement

Public reverse-engineered implementations do not currently agree on every high-bit field of a
9-byte CblockInfo record. This is exactly the kind of uncertainty that must not be hidden behind a
third-party implementation.

Guard: topology/planning is Packizard-owned now; replacement of the remaining byte codec is gated on
real descriptor fixtures whose bytes, decoded fields and reconstruction behavior are known.

## Native architecture

The target design is deliberately layered:

```
filesystem / game tree
        |
        v
LogicalLayoutPlanner
  - file logical offsets
  - DataEndLogical
  - metadata logical base
  - mount logical size
        |
        v
DataBlockEncoder
  - exact 256 KiB logical coverage
  - stored/Kraken decision
  - exact physical byte spans
        |
        v
NapsPlan
  - DATA / padding / metadata / terminator intervals
  - RUN schedule
        |
        +--> BudgetAnalyzer
        |      - per-group base/deltas
        |      - all field widths
        |      - monotonicity/overlap
        |
        v
NativeNapsCodec
  - header
  - fidx
  - u2c
  - CblockInfo
        |
        v
naps_pkg_layout.dat
```

A failure at any layer reports the logical U-block range, physical range, Cblock index range, region
(DATA/padding/metadata/terminator), RUN/STD counts, and exact field that cannot be represented.

## Validation gates

A native build is not considered console-ready merely because it reaches `Done: package.pkg`.
Before promotion it must pass:

1. in-memory vs file-backed DATA equivalence;
2. deterministic DATA block-map equivalence;
3. complete `pfs_image.dat + NAPS -> reconstructed mount` byte-for-byte comparison;
4. highly compressible DATA where physical size is far below logical size;
5. hostile tiny-file density;
6. large u2c bases above `0xffff` to exercise the third base byte;
7. partial and exact-multiple-of-eight U-block counts;
8. stored/Kraken transitions and RUN windows;
9. zero-byte and boundary-sized files;
10. >2 GiB file streaming without payload-sized allocations;
11. golden real `naps_pkg_layout.dat` fixtures for every binary-field interpretation;
12. final installation/mount/launch test on PS5.

## Non-negotiable rule

No native Packizard NAPS path may use `delta % 256`, `min(delta, 255)`, saturation, truncation or a
masked oversized base as a compatibility strategy. If the model says a value does not fit, the
planner must change or the build must stop with diagnostics.
