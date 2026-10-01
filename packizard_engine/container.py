"""Packizard-owned AMPRPAK4 compatibility container implementation.

This module defines the compatibility bytes consumed by the currently deployed
PS5 runtime. The implementation is first-party Packizard code; AMPRPAK4 is
kept only as a transition format while the Packizard PS5 runtime is introduced.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import binascii
import hashlib
import os
import struct
import sys
from typing import Iterable, Sequence

INDEX_MAGIC = b"AMPRPAK4"
DATA_MAGIC = b"AMPRDAT3"
CRC_MAGIC = b"AMPRCRC1"
INDEX_VERSION = 4
DATA_VERSION = 3
CRC_VERSION = 1
ENDIAN_MARKER = 0x01020304
INDEX_HEADER_SIZE = 128
DATA_HEADER_SIZE = 64
CRC_HEADER_SIZE = 48
INDEX_HEADER = struct.Struct("<8sIIII16sQQIIIIQQQQQIIQ")
FILE_RECORD = struct.Struct("<QQqIIIIIBBH")
CHUNK_RECORD = struct.Struct("<QI")
PACK_RECORD = struct.Struct("<QQIIII")
DATA_HEADER = struct.Struct("<8sIIII16sQQII")
CRC_HEADER = struct.Struct("<8sII16sQII")
AMPRIDX3_HEADER = struct.Struct("<8sIIQQQII")
AMPRIDX3_ENTRY = struct.Struct("<IIQq")

FILE_FLAG_PACKED = 1 << 0
FILE_FLAG_STORE_ONLY = 1 << 1
FILE_FLAG_STREAMING = 1 << 2
FILE_FLAG_HOT = 1 << 3
FILE_FLAG_RANDOM_ACCESS = 1 << 4
FILE_KNOWN_FLAGS = 0x1F
CHUNK_CODEC_RAW = 0
CHUNK_CODEC_LZ4 = 1
CHUNK_FLAG_SHARED = 1 << 0
CHUNK_FLAG_STREAMING = 1 << 1
CHUNK_FLAG_PAGE_CONTAINED = 1 << 2
CHUNK_FLAG_PAGE_ALIGNED = 1 << 3
CHUNK_KNOWN_FLAGS = 0x0F
PACK_FLAG_STRIPED = 1 << 0
PACK_FLAG_IO_PAGE_LAYOUT = 1 << 1
PACK_KNOWN_FLAGS = 0x03
INDEX_KNOWN_FLAGS = 0
MIN_BLOCK_SHIFT = 14
MAX_BLOCK_SHIFT = 20
MIN_IO_PAGE_SHIFT = 12
MAX_IO_PAGE_SHIFT = 20
PHYSICAL_CHUNK_ALIGNMENT = 64
CHUNK_OFFSET_MASK = (1 << 48) - 1
CHUNK_STORED_BITS = 20
CHUNK_STORED_MASK = (1 << CHUNK_STORED_BITS) - 1
CHUNK_CODEC_SHIFT = 20
CHUNK_CODEC_MASK = 0x3
CHUNK_FLAGS_SHIFT = 22
CHUNK_FLAGS_MASK = 0xFF
CHUNK_DESCRIPTOR_KNOWN_MASK = CHUNK_STORED_MASK | (CHUNK_CODEC_MASK << CHUNK_CODEC_SHIFT) | (CHUNK_FLAGS_MASK << CHUNK_FLAGS_SHIFT)


def crc32(data: bytes | bytearray | memoryview, seed: int = 0) -> int:
    return binascii.crc32(data, seed) & 0xFFFFFFFF


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def parse_size(value: str | int) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip().replace("_", "")
    split = len(text)
    while split and text[split - 1].isalpha():
        split -= 1
    number, suffix = text[:split], text[split:].lower() or "b"
    units = {"b": 1, "k": 1000, "kb": 1000, "kib": 1024, "m": 1000**2, "mb": 1000**2, "mib": 1024**2, "g": 1000**3, "gb": 1000**3, "gib": 1024**3}
    if suffix not in units:
        raise ValueError(f"unknown size suffix: {suffix}")
    result = int(float(number) * units[suffix])
    if result < 0:
        raise ValueError("size must be non-negative")
    return result


def block_shift(block_size: str | int) -> int:
    size = parse_size(block_size)
    if size <= 0 or size & (size - 1):
        raise ValueError("block size must be a power of two")
    shift = size.bit_length() - 1
    if not MIN_BLOCK_SHIFT <= shift <= MAX_BLOCK_SHIFT:
        raise ValueError("block size outside Packizard compatibility range")
    return shift


def canonical_asset_path(path: str) -> str:
    normalized = str(path).replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    parts: list[str] = []
    for part in normalized.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            if not parts:
                raise ValueError("path escapes /app0")
            parts.pop()
            continue
        if "\x00" in part:
            raise ValueError("NUL in path")
        parts.append(part)
    result = "/" + "/".join(parts)
    if result.lower() == "/app0":
        return "/app0"
    if not result.lower().startswith("/app0/"):
        raise ValueError(f"asset is outside /app0: {path}")
    return result


def asset_relative_path(path: str) -> str:
    canonical = canonical_asset_path(path)
    return "" if canonical.lower() == "/app0" else canonical[6:]


def fnv1a64(data: bytes) -> int:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value or 1


def asset_path_hash(path: str) -> int:
    raw = canonical_asset_path(path).encode("utf-8")
    folded = bytes((b + 0x20) if 0x41 <= b <= 0x5A else b for b in raw)
    return fnv1a64(folded)


def safe_output_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or "\\" in relative or any(p in ("", ".", "..") for p in pure.parts):
        raise ValueError(f"unsafe output path: {relative!r}")
    candidate = root.joinpath(*pure.parts)
    root_resolved = root.resolve()
    parent_resolved = candidate.parent.resolve()
    if os.path.commonpath((str(root_resolved), str(parent_resolved))) != str(root_resolved):
        raise ValueError(f"output path escapes root: {relative!r}")
    return candidate


@dataclass(frozen=True)
class AmprIndexEntry:
    path: str
    size: int
    mtime: int


def read_ampridx3(path: Path) -> list[AmprIndexEntry]:
    data = path.read_bytes()
    if len(data) < AMPRIDX3_HEADER.size:
        raise ValueError("AMPRIDX3 is truncated")
    magic, version, entry_size, count, path_bytes, hash_offset, hash_slot_size, hash_slot_count = AMPRIDX3_HEADER.unpack_from(data)
    if magic != b"AMPRIDX3" or version != 3 or entry_size != AMPRIDX3_ENTRY.size:
        raise ValueError("unsupported AMPRIDX3")
    records_offset = AMPRIDX3_HEADER.size
    paths_offset = records_offset + count * entry_size
    if paths_offset + path_bytes > len(data) or hash_offset < paths_offset + path_bytes:
        raise ValueError("invalid AMPRIDX3 layout")
    if hash_slot_count and not hash_slot_size:
        raise ValueError("invalid AMPRIDX3 hash table")
    result: list[AmprIndexEntry] = []
    for index in range(count):
        path_at, path_len, size, mtime = AMPRIDX3_ENTRY.unpack_from(data, records_offset + index * entry_size)
        if path_at + path_len >= path_bytes:
            raise ValueError("AMPRIDX3 path out of range")
        start = paths_offset + path_at
        end = start + path_len
        if data[end] != 0:
            raise ValueError("AMPRIDX3 path is not NUL terminated")
        result.append(AmprIndexEntry(canonical_asset_path(data[start:end].decode("utf-8")), size, mtime))
    return result


@dataclass
class FileRecord:
    path_hash: int
    logical_size: int
    mtime: int
    first_chunk: int
    chunk_count: int
    path_offset: int
    path_length: int
    flags: int
    block_shift: int
    packing_class: int = 0
    reserved: int = 0

    def pack(self) -> bytes:
        return FILE_RECORD.pack(self.path_hash, self.logical_size, self.mtime, self.first_chunk, self.chunk_count, self.path_offset, self.path_length, self.flags, self.block_shift, self.packing_class, self.reserved)

    @classmethod
    def unpack_from(cls, data: bytes, offset: int) -> "FileRecord":
        return cls(*FILE_RECORD.unpack_from(data, offset))


@dataclass
class ChunkRecord:
    offset: int
    stored_size: int
    raw_size: int
    pack_id: int
    codec: int
    flags: int = 0

    def pack(self) -> bytes:
        if not 0 <= self.offset <= CHUNK_OFFSET_MASK:
            raise ValueError("chunk offset exceeds compatibility domain")
        if not 0 <= self.pack_id <= 0xFFFF:
            raise ValueError("pack id exceeds uint16")
        if not 1 <= self.stored_size <= 1 << MAX_BLOCK_SHIFT:
            raise ValueError("stored chunk size invalid")
        if self.codec not in (CHUNK_CODEC_RAW, CHUNK_CODEC_LZ4):
            raise ValueError("unsupported chunk codec")
        if self.flags & ~CHUNK_KNOWN_FLAGS:
            raise ValueError("unknown chunk flags")
        location = self.offset | (self.pack_id << 48)
        descriptor = (self.stored_size - 1) | (self.codec << CHUNK_CODEC_SHIFT) | (self.flags << CHUNK_FLAGS_SHIFT)
        return CHUNK_RECORD.pack(location, descriptor)

    @classmethod
    def unpack_from(cls, data: bytes, offset: int) -> "ChunkRecord":
        location, descriptor = CHUNK_RECORD.unpack_from(data, offset)
        if descriptor & ~CHUNK_DESCRIPTOR_KNOWN_MASK:
            raise ValueError("unknown chunk descriptor bits")
        return cls(location & CHUNK_OFFSET_MASK, (descriptor & CHUNK_STORED_MASK) + 1, 0, (location >> 48) & 0xFFFF, (descriptor >> CHUNK_CODEC_SHIFT) & CHUNK_CODEC_MASK, (descriptor >> CHUNK_FLAGS_SHIFT) & CHUNK_FLAGS_MASK)


@dataclass
class PackRecord:
    payload_bytes: int
    file_size: int
    name_offset: int
    name_length: int
    flags: int
    io_page_size: int

    def pack(self) -> bytes:
        return PACK_RECORD.pack(self.payload_bytes, self.file_size, self.name_offset, self.name_length, self.flags, self.io_page_size)

    @classmethod
    def unpack_from(cls, data: bytes, offset: int) -> "PackRecord":
        return cls(*PACK_RECORD.unpack_from(data, offset))


@dataclass
class PackManifest:
    path: Path
    build_id: bytes
    flags: int
    files: list[FileRecord]
    chunks: list[ChunkRecord]
    packs: list[PackRecord]
    strings: bytes

    def string_at(self, offset: int, length: int) -> str:
        if offset < 0 or length < 0 or offset + length >= len(self.strings) or self.strings[offset + length] != 0:
            raise ValueError("invalid string table reference")
        return self.strings[offset:offset + length].decode("utf-8")

    def file_path(self, file_id: int) -> str:
        record = self.files[file_id - 1]
        return self.string_at(record.path_offset, record.path_length)

    def pack_name(self, pack_id: int) -> str:
        record = self.packs[pack_id]
        return self.string_at(record.name_offset, record.name_length)


class StringTable:
    def __init__(self) -> None:
        self._data = bytearray()
        self._known: dict[str, tuple[int, int]] = {}

    def add(self, value: str) -> tuple[int, int]:
        if value in self._known:
            return self._known[value]
        encoded = value.encode("utf-8")
        if b"\x00" in encoded:
            raise ValueError("NUL in string")
        result = (len(self._data), len(encoded))
        self._data.extend(encoded)
        self._data.append(0)
        self._known[value] = result
        return result

    def bytes(self) -> bytes:
        return bytes(self._data)


def build_manifest_header(*, flags: int, build_id: bytes, file_count: int, chunk_count: int, pack_count: int, files_offset: int, chunks_offset: int, packs_offset: int, strings_offset: int, strings_size: int, payload_crc: int) -> bytes:
    values = (INDEX_MAGIC, INDEX_VERSION, INDEX_HEADER_SIZE, flags, ENDIAN_MARKER, build_id, file_count, chunk_count, pack_count, FILE_RECORD.size, CHUNK_RECORD.size, PACK_RECORD.size, files_offset, chunks_offset, packs_offset, strings_offset, strings_size, payload_crc, 0, 0)
    zero = INDEX_HEADER.pack(*values)
    return INDEX_HEADER.pack(*(values[:-2] + (crc32(zero), 0)))


def build_manifest_bytes(build_id: bytes, files: Sequence[FileRecord], chunks: Sequence[ChunkRecord], packs: Sequence[PackRecord], strings: bytes) -> bytes:
    files_offset = INDEX_HEADER_SIZE
    chunks_offset = files_offset + len(files) * FILE_RECORD.size
    packs_offset = chunks_offset + len(chunks) * CHUNK_RECORD.size
    strings_offset = packs_offset + len(packs) * PACK_RECORD.size
    payload = b"".join(r.pack() for r in files) + b"".join(r.pack() for r in chunks) + b"".join(r.pack() for r in packs) + strings
    header = build_manifest_header(flags=0, build_id=build_id, file_count=len(files), chunk_count=len(chunks), pack_count=len(packs), files_offset=files_offset, chunks_offset=chunks_offset, packs_offset=packs_offset, strings_offset=strings_offset, strings_size=len(strings), payload_crc=crc32(payload))
    return header + payload


def load_manifest(path: Path) -> PackManifest:
    data = path.read_bytes()
    if len(data) < INDEX_HEADER_SIZE:
        raise ValueError("pack index truncated")
    values = INDEX_HEADER.unpack_from(data)
    (magic, version, header_size, flags, endian, build_id, file_count, chunk_count, pack_count, file_size, chunk_size, pack_size, files_offset, chunks_offset, packs_offset, strings_offset, strings_size, payload_crc, header_crc, reserved) = values
    if magic != INDEX_MAGIC or version != INDEX_VERSION or header_size != INDEX_HEADER_SIZE or endian != ENDIAN_MARKER or flags or reserved:
        raise ValueError("unsupported Packizard compatibility index")
    if (file_size, chunk_size, pack_size) != (FILE_RECORD.size, CHUNK_RECORD.size, PACK_RECORD.size):
        raise ValueError("record-size mismatch")
    header_copy = bytearray(data[:INDEX_HEADER_SIZE])
    struct.pack_into("<I", header_copy, 116, 0)
    if crc32(header_copy) != header_crc or crc32(data[INDEX_HEADER_SIZE:]) != payload_crc:
        raise ValueError("pack index CRC mismatch")
    if files_offset != INDEX_HEADER_SIZE or chunks_offset != files_offset + file_count * FILE_RECORD.size or packs_offset != chunks_offset + chunk_count * CHUNK_RECORD.size or strings_offset != packs_offset + pack_count * PACK_RECORD.size or strings_offset + strings_size != len(data):
        raise ValueError("invalid pack index layout")
    files = [FileRecord.unpack_from(data, files_offset + i * FILE_RECORD.size) for i in range(file_count)]
    chunks = [ChunkRecord.unpack_from(data, chunks_offset + i * CHUNK_RECORD.size) for i in range(chunk_count)]
    for record in files:
        if not record.flags & FILE_FLAG_PACKED:
            continue
        block = 1 << record.block_shift
        for local in range(record.chunk_count):
            at = record.first_chunk + local
            if at >= len(chunks):
                raise ValueError("file chunk range invalid")
            remaining = record.logical_size - local * block
            if remaining <= 0:
                raise ValueError("too many chunks")
            chunks[at].raw_size = min(block, remaining)
    packs = [PackRecord.unpack_from(data, packs_offset + i * PACK_RECORD.size) for i in range(pack_count)]
    result = PackManifest(path, build_id, flags, files, chunks, packs, data[strings_offset:])
    validate_manifest(result)
    return result


def validate_manifest(manifest: PackManifest) -> None:
    for pack_id, pack in enumerate(manifest.packs):
        safe_output_path(Path("."), manifest.pack_name(pack_id))
        if pack.flags & ~PACK_KNOWN_FLAGS or not pack.flags & PACK_FLAG_IO_PAGE_LAYOUT:
            raise ValueError("invalid pack flags")
        if pack.io_page_size < 1 << MIN_IO_PAGE_SHIFT or pack.io_page_size > 1 << MAX_IO_PAGE_SHIFT or pack.io_page_size & (pack.io_page_size - 1):
            raise ValueError("invalid I/O page size")
        payload_offset = pack.file_size - pack.payload_bytes
        if pack.file_size < DATA_HEADER_SIZE or payload_offset < DATA_HEADER_SIZE or payload_offset % pack.io_page_size or pack.file_size % pack.io_page_size:
            raise ValueError("invalid pack geometry")
    for file_id, record in enumerate(manifest.files, 1):
        path = manifest.file_path(file_id)
        if canonical_asset_path(path) != path or path == "/app0" or record.path_hash != asset_path_hash(path):
            raise ValueError("invalid file path/hash")
        if record.reserved or record.flags & ~FILE_KNOWN_FLAGS:
            raise ValueError("invalid file flags")
        if not record.flags & FILE_FLAG_PACKED:
            if record.first_chunk or record.chunk_count or record.block_shift or record.packing_class or record.flags:
                raise ValueError("loose file references chunks")
            continue
        if record.block_shift < MIN_BLOCK_SHIFT or record.block_shift > MAX_BLOCK_SHIFT or record.first_chunk + record.chunk_count > len(manifest.chunks):
            raise ValueError("invalid packed file geometry")
        total = 0
        for chunk in manifest.chunks[record.first_chunk:record.first_chunk + record.chunk_count]:
            if chunk.pack_id >= len(manifest.packs) or chunk.codec not in (CHUNK_CODEC_RAW, CHUNK_CODEC_LZ4):
                raise ValueError("invalid chunk")
            pack = manifest.packs[chunk.pack_id]
            payload_offset = pack.file_size - pack.payload_bytes
            if chunk.offset < payload_offset or chunk.offset + chunk.stored_size > pack.file_size or chunk.offset % PHYSICAL_CHUNK_ALIGNMENT:
                raise ValueError("chunk outside pack")
            page_safe = bool(chunk.flags & CHUNK_FLAG_PAGE_CONTAINED) if chunk.stored_size <= pack.io_page_size else bool(chunk.flags & CHUNK_FLAG_PAGE_ALIGNED)
            if not page_safe and not record.flags & FILE_FLAG_STREAMING:
                raise ValueError("non-streaming chunk is not page safe")
            total += chunk.raw_size
        if total != record.logical_size:
            raise ValueError("logical size mismatch")


def build_data_header(pack_id: int, build_id: bytes, payload_offset: int, payload_bytes: int, flags: int = PACK_FLAG_IO_PAGE_LAYOUT) -> bytes:
    zero = DATA_HEADER.pack(DATA_MAGIC, DATA_VERSION, DATA_HEADER_SIZE, pack_id, flags, build_id, payload_offset, payload_bytes, 0, 0)
    return DATA_HEADER.pack(DATA_MAGIC, DATA_VERSION, DATA_HEADER_SIZE, pack_id, flags, build_id, payload_offset, payload_bytes, crc32(zero), 0)


def validate_data_header(header: bytes, expected_pack_id: int | None = None, expected_build_id: bytes | None = None) -> tuple[int, bytes, int, int, int]:
    if len(header) != DATA_HEADER_SIZE:
        raise ValueError("pack data header truncated")
    magic, version, header_size, pack_id, flags, build_id, payload_offset, payload_bytes, header_crc, reserved = DATA_HEADER.unpack(header)
    copy = bytearray(header)
    struct.pack_into("<I", copy, 56, 0)
    if magic != DATA_MAGIC or version != DATA_VERSION or header_size != DATA_HEADER_SIZE or reserved or crc32(copy) != header_crc:
        raise ValueError("invalid pack data header")
    if expected_pack_id is not None and pack_id != expected_pack_id:
        raise ValueError("pack id mismatch")
    if expected_build_id is not None and build_id != expected_build_id:
        raise ValueError("build id mismatch")
    return pack_id, build_id, payload_offset, payload_bytes, flags


def chunk_crc_path(index_path: Path) -> Path:
    return Path(str(index_path) + ".crc")


def build_chunk_crc_header(build_id: bytes, chunk_count: int, payload_crc: int) -> bytes:
    zero = CRC_HEADER.pack(CRC_MAGIC, CRC_VERSION, CRC_HEADER_SIZE, build_id, chunk_count, payload_crc, 0)
    return CRC_HEADER.pack(CRC_MAGIC, CRC_VERSION, CRC_HEADER_SIZE, build_id, chunk_count, payload_crc, crc32(zero))


def build_chunk_crc_bytes(build_id: bytes, checksums: Sequence[int]) -> bytes:
    values = array("I", checksums)
    if sys.byteorder != "little":
        values.byteswap()
    payload = values.tobytes()
    return build_chunk_crc_header(build_id, len(checksums), crc32(payload)) + payload


def load_chunk_crcs(path: Path, build_id: bytes, count: int) -> array:
    data = path.read_bytes()
    if len(data) < CRC_HEADER_SIZE:
        raise ValueError("CRC sidecar truncated")
    magic, version, header_size, got_id, got_count, payload_crc, header_crc = CRC_HEADER.unpack_from(data)
    copy = bytearray(data[:CRC_HEADER_SIZE])
    struct.pack_into("<I", copy, 44, 0)
    payload = data[CRC_HEADER_SIZE:]
    if magic != CRC_MAGIC or version != CRC_VERSION or header_size != CRC_HEADER_SIZE or got_id != build_id or got_count != count or crc32(copy) != header_crc or crc32(payload) != payload_crc or len(payload) != count * 4:
        raise ValueError("invalid CRC sidecar")
    result = array("I")
    result.frombytes(payload)
    if sys.byteorder != "little":
        result.byteswap()
    return result


def deterministic_build_id(parts: Iterable[bytes]) -> bytes:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "little"))
        digest.update(part)
    return digest.digest()[:16]


RUNTIME_PROFILE = struct.Struct("<8sII16sQQIIII")

@dataclass(frozen=True)
class RuntimeSettings:
    decoded_cache_bytes: int
    physical_cache_bytes: int
    workers: int
    latency_reserve_workers: int

    def validate(self) -> None:
        if not 1 <= self.workers <= 16 or not 0 <= self.latency_reserve_workers < self.workers:
            raise ValueError("runtime workers must be 1..16 and reserve smaller than workers")
        for value in (self.decoded_cache_bytes, self.physical_cache_bytes):
            if value < 0 or value >= 1 << 64 or value % 16384:
                raise ValueError("runtime cache sizes must be 16 KiB multiples")

    def encode(self, build_id: bytes) -> bytes:
        self.validate()
        data = bytearray(RUNTIME_PROFILE.pack(b"AMPRCFG1", 1, RUNTIME_PROFILE.size, build_id, self.decoded_cache_bytes, self.physical_cache_bytes, self.workers, self.latency_reserve_workers, 0, 0))
        struct.pack_into("<I", data, 56, crc32(data))
        return bytes(data)


def read_runtime_settings(path: Path, build_id: bytes) -> RuntimeSettings | None:
    try:
        data = bytearray(path.read_bytes())
    except FileNotFoundError:
        return None
    if len(data) != RUNTIME_PROFILE.size:
        raise ValueError("invalid runtime profile size")
    magic, version, size, bound_id, decoded, physical, workers, reserve, checksum, flags = RUNTIME_PROFILE.unpack(data)
    struct.pack_into("<I", data, 56, 0)
    if magic != b"AMPRCFG1" or version != 1 or size != len(data) or bound_id != build_id or flags or crc32(data) != checksum:
        raise ValueError("invalid runtime profile")
    result = RuntimeSettings(decoded, physical, workers, reserve)
    result.validate()
    return result
