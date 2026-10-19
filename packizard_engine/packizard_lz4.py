"""First-party raw LZ4 block codec used by the Packizard engine.

This module intentionally implements the LZ4 *block* format, not the framed
format. AMPR-compatible Packizard payloads store independently addressable raw
blocks and keep raw/stored sizes in their own index metadata.

The implementation is dependency-free and conservative. Compression ratio can
be improved later without changing the on-disk format or decoder contract.
"""
from __future__ import annotations

from dataclasses import dataclass

_MIN_MATCH = 4
_MAX_OFFSET = 0xFFFF
_HASH_BITS = 16
_HASH_SIZE = 1 << _HASH_BITS
_HASH_MULTIPLIER = 2654435761


class PackizardLz4Error(ValueError):
    """Raised when a raw LZ4 block is malformed or violates output bounds."""


def _hash4(data: bytes, pos: int) -> int:
    value = int.from_bytes(data[pos : pos + 4], "little")
    return ((value * _HASH_MULTIPLIER) & 0xFFFFFFFF) >> (32 - _HASH_BITS)


def _emit_length(out: bytearray, length: int) -> None:
    while length >= 255:
        out.append(255)
        length -= 255
    out.append(length)


def _emit_sequence(
    out: bytearray,
    literals: bytes,
    *,
    offset: int | None = None,
    match_length: int = 0,
) -> None:
    literal_length = len(literals)
    if offset is None:
        token = min(literal_length, 15) << 4
        out.append(token)
        if literal_length >= 15:
            _emit_length(out, literal_length - 15)
        out.extend(literals)
        return

    if not 1 <= offset <= _MAX_OFFSET:
        raise PackizardLz4Error(f"invalid LZ4 offset: {offset}")
    if match_length < _MIN_MATCH:
        raise PackizardLz4Error(f"invalid LZ4 match length: {match_length}")

    encoded_match = match_length - _MIN_MATCH
    token = (min(literal_length, 15) << 4) | min(encoded_match, 15)
    out.append(token)
    if literal_length >= 15:
        _emit_length(out, literal_length - 15)
    out.extend(literals)
    out.extend(offset.to_bytes(2, "little"))
    if encoded_match >= 15:
        _emit_length(out, encoded_match - 15)


def compress_block(data: bytes, *, acceleration: int = 1) -> bytes:
    """Encode *data* as a standards-compatible raw LZ4 block.

    The encoder deliberately observes the common LZ4 end-of-block constraints:
    the final five input bytes remain literals and the last match begins at
    least twelve bytes before the end. This maximizes compatibility with safe
    decoders used by console runtimes.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    src = bytes(data)
    size = len(src)
    if size == 0:
        return b"\x00"
    if size < 13:
        out = bytearray()
        _emit_sequence(out, src)
        return bytes(out)

    acceleration = max(1, int(acceleration))
    table = [-1] * _HASH_SIZE
    out = bytearray()
    anchor = 0
    pos = 0
    last_match_start = size - 12
    match_limit = size - 5

    while pos <= last_match_start:
        h = _hash4(src, pos)
        candidate = table[h]
        table[h] = pos

        if (
            candidate < 0
            or pos - candidate > _MAX_OFFSET
            or src[candidate : candidate + 4] != src[pos : pos + 4]
        ):
            pos += acceleration
            continue

        match_length = _MIN_MATCH
        while (
            pos + match_length < match_limit
            and candidate + match_length < pos
            and src[candidate + match_length] == src[pos + match_length]
        ):
            match_length += 1

        # LZ4 permits overlapping matches. Once the candidate catches the
        # current position, compare against the already-matched periodic bytes.
        while pos + match_length < match_limit:
            source_index = candidate + (match_length % (pos - candidate))
            if src[source_index] != src[pos + match_length]:
                break
            match_length += 1

        _emit_sequence(
            out,
            src[anchor:pos],
            offset=pos - candidate,
            match_length=match_length,
        )

        match_end = pos + match_length
        # Seed hashes inside the match so repetitive assets do not degrade into
        # mostly-literal output after a long run.
        seed = pos + 1
        seed_end = min(match_end - 3, last_match_start + 1)
        while seed < seed_end:
            table[_hash4(src, seed)] = seed
            seed += 1

        pos = match_end
        anchor = pos

    _emit_sequence(out, src[anchor:])
    return bytes(out)



_HC_SEARCH_DEPTH = {
    5: 4,
    6: 8,
    7: 16,
    8: 32,
    9: 64,
    10: 128,
    11: 256,
    12: 512,
}


def _match_length(src: bytes, candidate: int, pos: int, match_limit: int) -> int:
    """Return the legal LZ4 match length for candidate -> pos, including overlap."""
    distance = pos - candidate
    if distance <= 0 or distance > _MAX_OFFSET:
        return 0
    if src[candidate:candidate + _MIN_MATCH] != src[pos:pos + _MIN_MATCH]:
        return 0

    length = _MIN_MATCH
    # Before the source reaches pos, compare directly.
    while (
        pos + length < match_limit
        and candidate + length < pos
        and src[candidate + length] == src[pos + length]
    ):
        length += 1

    # LZ4 matches may overlap. Continue using the repeated period.
    while pos + length < match_limit:
        source_index = candidate + (length % distance)
        if src[source_index] != src[pos + length]:
            break
        length += 1
    return length


def compress_block_hc(data: bytes, *, level: int = 9) -> bytes:
    """Encode a raw LZ4 block using bounded hash-chain match search.

    Levels 5..12 increase the number of previous candidates examined for each
    position. The emitted representation is ordinary raw LZ4 and remains
    decodable by the same safe decoder/runtime as fast mode.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    src = bytes(data)
    size = len(src)
    if size == 0:
        return b"\x00"
    if size < 13:
        out = bytearray()
        _emit_sequence(out, src)
        return bytes(out)

    level = max(5, min(12, int(level)))
    depth = _HC_SEARCH_DEPTH[level]
    head = [-1] * _HASH_SIZE
    prev = [-1] * size
    out = bytearray()
    anchor = 0
    pos = 0
    last_match_start = size - 12
    match_limit = size - 5

    while pos <= last_match_start:
        h = _hash4(src, pos)
        candidate = head[h]
        prev[pos] = candidate
        head[h] = pos

        best_candidate = -1
        best_length = 0
        attempts = 0
        probe = candidate
        while probe >= 0 and attempts < depth:
            distance = pos - probe
            if distance > _MAX_OFFSET:
                break
            length = _match_length(src, probe, pos, match_limit)
            if length > best_length:
                best_length = length
                best_candidate = probe
                if pos + best_length >= match_limit:
                    break
            probe = prev[probe]
            attempts += 1

        if best_length < _MIN_MATCH:
            pos += 1
            continue

        _emit_sequence(
            out,
            src[anchor:pos],
            offset=pos - best_candidate,
            match_length=best_length,
        )

        match_end = pos + best_length
        # Insert intermediate positions into the hash chain. This is important
        # for repetitive game assets where the next best reference often begins
        # inside the match we just emitted.
        seed = pos + 1
        seed_end = min(match_end, last_match_start + 1)
        while seed < seed_end:
            seed_hash = _hash4(src, seed)
            prev[seed] = head[seed_hash]
            head[seed_hash] = seed
            seed += 1

        pos = match_end
        anchor = pos

    _emit_sequence(out, src[anchor:])
    return bytes(out)


def _read_extended_length(src: bytes, pos: int) -> tuple[int, int]:
    total = 0
    while True:
        if pos >= len(src):
            raise PackizardLz4Error("truncated LZ4 extended length")
        value = src[pos]
        pos += 1
        total += value
        if value != 255:
            return total, pos


def decompress_block(data: bytes, raw_size: int) -> bytes:
    """Safely decode one raw LZ4 block and require exactly *raw_size* bytes."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    src = bytes(data)
    raw_size = int(raw_size)
    if raw_size < 0:
        raise ValueError("raw_size must be non-negative")

    out = bytearray()
    pos = 0

    while pos < len(src):
        token = src[pos]
        pos += 1

        literal_length = token >> 4
        if literal_length == 15:
            extra, pos = _read_extended_length(src, pos)
            literal_length += extra
        if pos + literal_length > len(src):
            raise PackizardLz4Error("truncated LZ4 literals")
        if len(out) + literal_length > raw_size:
            raise PackizardLz4Error("LZ4 literals exceed declared output size")

        out.extend(src[pos : pos + literal_length])
        pos += literal_length

        if pos == len(src):
            break
        if pos + 2 > len(src):
            raise PackizardLz4Error("truncated LZ4 offset")

        offset = int.from_bytes(src[pos : pos + 2], "little")
        pos += 2
        if offset == 0 or offset > len(out):
            raise PackizardLz4Error("invalid LZ4 match offset")

        match_length = (token & 0x0F) + _MIN_MATCH
        if (token & 0x0F) == 15:
            extra, pos = _read_extended_length(src, pos)
            match_length += extra
        if len(out) + match_length > raw_size:
            raise PackizardLz4Error("LZ4 match exceeds declared output size")

        match_at = len(out) - offset
        for index in range(match_length):
            out.append(out[match_at + index])

    if pos != len(src):
        raise PackizardLz4Error("trailing bytes in LZ4 block")
    if len(out) != raw_size:
        raise PackizardLz4Error(
            f"decoded LZ4 size mismatch: expected {raw_size}, got {len(out)}"
        )
    return bytes(out)


@dataclass(slots=True)
class PackizardLz4Codec:
    """Drop-in codec facade for the existing AMPR pack-format integration."""

    def compress(
        self,
        data: bytes,
        *,
        mode: str = "fast",
        level: int = 9,
        acceleration: int = 1,
    ) -> bytes:
        if mode not in {"fast", "hc"}:
            raise ValueError(f"unsupported compression mode: {mode}")
        level = max(1, min(12, int(level)))
        if mode == "hc":
            return compress_block_hc(data, level=max(5, level))

        # Fast levels deliberately trade ratio for speed. Level 4 performs the
        # densest search used by fast mode; levels 1..3 skip progressively more
        # candidate positions while preserving the exact same raw LZ4 format.
        level_acceleration = 1 << max(0, 4 - min(level, 4))
        effective_acceleration = max(max(1, int(acceleration)), level_acceleration)
        return compress_block(data, acceleration=effective_acceleration)

    def decompress(self, data: bytes, raw_size: int) -> bytes:
        return decompress_block(data, raw_size)
