"""First-party Packizard pack/index engine with AMPRPAK4 compatibility output."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import sys
import time
import tomllib

from packizard_container import (
    CHUNK_CODEC_LZ4, CHUNK_CODEC_RAW, CHUNK_FLAG_PAGE_ALIGNED,
    CHUNK_FLAG_PAGE_CONTAINED, FILE_FLAG_PACKED, PACK_FLAG_IO_PAGE_LAYOUT,
    ChunkRecord, FileRecord, PackRecord, RuntimeSettings, StringTable, align_up,
    asset_path_hash, asset_relative_path, block_shift, build_chunk_crc_bytes,
    build_data_header, build_manifest_bytes, crc32, deterministic_build_id,
    load_chunk_crcs, load_manifest, parse_size, read_ampridx3, safe_output_path,
    validate_data_header,
)
from packizard_lz4 import PackizardLz4Codec

VERSION = "Packizard Engine 1.0-compat4"


def _matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    return fnmatch.fnmatchcase(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))


def _patterns(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(x) for x in value] if isinstance(value, list) else []


def _rule_for(config: dict, relative: str) -> tuple[str, dict]:
    pack = config.get("pack", {}) if isinstance(config.get("pack", {}), dict) else {}
    action = str(pack.get("default_action", "loose")).lower()
    selected: dict = {}
    rules = config.get("rule", [])
    if isinstance(rules, dict):
        rules = [rules]
    if not isinstance(rules, list):
        rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        includes = _patterns(rule.get("include", ["**"]))
        excludes = _patterns(rule.get("exclude", []))
        if any(_matches(relative, item) for item in includes) and not any(_matches(relative, item) for item in excludes):
            selected = rule
            action = str(rule.get("action", action)).lower()
    return action, selected


def _progress(stage: str, percent: int, message: str, started: float, no_progress: bool) -> None:
    if no_progress:
        return
    elapsed = int(time.monotonic() - started)
    stamp = f"{elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}"
    print(f"[{stage} {max(0, min(100, percent))}%] {message} elapsed {stamp}", file=sys.stderr, flush=True)


def _load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    return value if isinstance(value, dict) else {}


def _canonical_config_bytes(config: dict) -> bytes:
    return json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build(root: Path, ampr_index: Path, output: Path, config_path: Path | None, excludes: list[str], no_progress: bool = False) -> dict:
    started = time.monotonic()
    root = root.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = _load_config(config_path)
    pack_cfg = config.get("pack", {}) if isinstance(config.get("pack", {}), dict) else {}
    default_shift = block_shift(pack_cfg.get("default_block_size", "64KiB"))
    io_page = parse_size(pack_cfg.get("io_page_size", "64KiB"))
    if io_page < 4096 or io_page & (io_page - 1):
        raise ValueError("invalid io_page_size")
    mode = str(pack_cfg.get("compression_mode", "hc")).lower()
    level = int(pack_cfg.get("compression_level", 9))
    acceleration = int(pack_cfg.get("acceleration", 1))
    min_savings = parse_size(pack_cfg.get("min_savings_bytes", 64))
    min_ratio = float(pack_cfg.get("min_savings_ratio", 0.01))

    entries = read_ampridx3(ampr_index)
    strings = StringTable()
    files: list[FileRecord] = []
    chunks: list[ChunkRecord] = []
    checksums: list[int] = []
    loose: list[str] = []
    payloads: list[bytes] = []
    codec = PackizardLz4Codec()
    selected: dict[int, tuple[Path, str, dict, int]] = {}

    for file_id, entry in enumerate(entries, 1):
        relative = asset_relative_path(entry.path)
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(f"indexed source missing: {relative}")
        if source.stat().st_size != entry.size:
            raise RuntimeError(f"indexed source size changed: {relative}")
        action, rule = _rule_for(config, relative)
        forced_loose = any(_matches(relative, pattern) for pattern in excludes)
        should_pack = action in {"pack", "compress"} and not forced_loose
        shift = block_shift(rule.get("block_size", 1 << default_shift)) if rule else default_shift
        if should_pack:
            selected[file_id] = (source, relative, rule, shift)
        else:
            loose.append(relative)

    total_bytes = sum(entries[file_id - 1].size for file_id in selected)
    done_bytes = 0
    for file_id, entry in enumerate(entries, 1):
        path_offset, path_length = strings.add(entry.path)
        item = selected.get(file_id)
        if item is None:
            files.append(FileRecord(asset_path_hash(entry.path), entry.size, entry.mtime, 0, 0, path_offset, path_length, 0, 0))
            continue
        source, relative, rule, shift = item
        block_size = 1 << shift
        first_chunk = len(chunks)
        data = source.read_bytes()
        for offset in range(0, len(data), block_size):
            raw = data[offset:offset + block_size]
            compressed = codec.compress(
                raw,
                mode=str(rule.get("compression_mode", mode)),
                level=int(rule.get("compression_level", level)),
                acceleration=acceleration,
            )
            savings = len(raw) - len(compressed)
            use_lz4 = len(raw) > 0 and savings >= min_savings and savings / max(1, len(raw)) >= min_ratio
            stored = compressed if use_lz4 else raw
            if not stored and not raw:
                continue
            payloads.append(stored)
            chunks.append(ChunkRecord(0, len(stored), len(raw), 0, CHUNK_CODEC_LZ4 if use_lz4 else CHUNK_CODEC_RAW, CHUNK_FLAG_PAGE_ALIGNED | CHUNK_FLAG_PAGE_CONTAINED))
            checksums.append(crc32(raw))
            done_bytes += len(raw)
            _progress("packing", int(done_bytes * 80 / max(1, total_bytes)), f"packing {relative}", started, no_progress)
        files.append(FileRecord(asset_path_hash(entry.path), len(data), entry.mtime, first_chunk, len(chunks) - first_chunk, path_offset, path_length, FILE_FLAG_PACKED, shift))

    pack_pattern = str(pack_cfg.get("pack_pattern", "ampr_assets-{group}-lane{lane:02d}-vol{volume:02d}-{id:03d}.pak"))
    pack_name = pack_pattern.format(group="default", lane=0, volume=0, id=0)
    payload_offset = io_page
    cursor = payload_offset
    for record, payload in zip(chunks, payloads):
        cursor = align_up(cursor, io_page)
        record.offset = cursor
        cursor += len(payload)
    final_size = align_up(cursor, io_page)
    name_offset, name_length = strings.add(pack_name)
    pack_record = PackRecord(final_size - payload_offset, final_size, name_offset, name_length, PACK_FLAG_IO_PAGE_LAYOUT, io_page)
    crc_payload = b"".join(int(value).to_bytes(4, "little") for value in checksums)
    build_id = deterministic_build_id((_canonical_config_bytes(config), b"".join(item.pack() for item in files), b"".join(item.pack() for item in chunks), crc_payload, pack_record.pack(), strings.bytes()))

    pack_path = safe_output_path(output, pack_name)
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    with pack_path.open("wb") as handle:
        handle.write(build_data_header(0, build_id, payload_offset, final_size - payload_offset))
        if handle.tell() < payload_offset:
            handle.write(b"\x00" * (payload_offset - handle.tell()))
        for record, payload in zip(chunks, payloads):
            if handle.tell() < record.offset:
                handle.write(b"\x00" * (record.offset - handle.tell()))
            handle.write(payload)
        if handle.tell() < final_size:
            handle.write(b"\x00" * (final_size - handle.tell()))

    index_name = str(pack_cfg.get("index_name", "ampr_assets.index"))
    index_path = safe_output_path(output, index_name)
    index_path.write_bytes(build_manifest_bytes(build_id, files, chunks, [pack_record], strings.bytes()))
    Path(str(index_path) + ".crc").write_bytes(build_chunk_crc_bytes(build_id, checksums))
    runtime_cfg = config.get("runtime")
    if isinstance(runtime_cfg, dict):
        settings = RuntimeSettings(parse_size(runtime_cfg.get("decoded_cache_bytes", 0)), parse_size(runtime_cfg.get("physical_cache_bytes", 0)), int(runtime_cfg.get("workers", 4)), int(runtime_cfg.get("latency_reserve_workers", 0)))
        Path(str(index_path) + ".runtime").write_bytes(settings.encode(build_id))
    _progress("packing", 100, "Packizard pack complete", started, no_progress)
    return {"index": str(index_path), "packs": [pack_name], "crc": index_path.name + ".crc", "files": len(files), "packed_files": len(selected), "loose_paths": sorted(loose), "engine": VERSION}


def _read_chunk(manifest, pack_handles, chunk, codec):
    handle = pack_handles[chunk.pack_id]
    handle.seek(chunk.offset)
    stored = handle.read(chunk.stored_size)
    if len(stored) != chunk.stored_size:
        raise ValueError("pack chunk truncated")
    return stored if chunk.codec == CHUNK_CODEC_RAW else codec.decompress(stored, chunk.raw_size)


def verify(index: Path, root: Path | None, no_progress: bool = False) -> dict:
    started = time.monotonic()
    manifest = load_manifest(index)
    codec = PackizardLz4Codec()
    checksums = load_chunk_crcs(Path(str(index) + ".crc"), manifest.build_id, len(manifest.chunks))
    handles = []
    try:
        for pack_id in range(len(manifest.packs)):
            handle = (index.parent / manifest.pack_name(pack_id)).open("rb")
            validate_data_header(handle.read(64), pack_id, manifest.build_id)
            handles.append(handle)
        source_bytes = 0
        checked = 0
        packed_records = [(file_id, record) for file_id, record in enumerate(manifest.files, 1) if record.flags & FILE_FLAG_PACKED]
        for position, (file_id, record) in enumerate(packed_records, 1):
            data = bytearray()
            for chunk_index in range(record.first_chunk, record.first_chunk + record.chunk_count):
                raw = _read_chunk(manifest, handles, manifest.chunks[chunk_index], codec)
                if crc32(raw) != checksums[chunk_index]:
                    raise ValueError(f"chunk CRC mismatch: {manifest.file_path(file_id)}")
                data.extend(raw)
                checked += 1
            if len(data) != record.logical_size:
                raise ValueError("logical size mismatch")
            if root is not None:
                source = root / asset_relative_path(manifest.file_path(file_id))
                expected = source.read_bytes()
                source_bytes += len(expected)
                if expected != bytes(data):
                    raise ValueError(f"source comparison failed: {source}")
            _progress("verify", int(position * 100 / max(1, len(packed_records))), f"verifying packed chunks files {position}/{len(packed_records)}", started, no_progress)
        if root is not None:
            _progress("compare", 100, f"comparing against source files {len(packed_records)}/{len(packed_records)}", started, no_progress)
        return {"files": len(packed_records), "chunks": checked, "source_compare": {"bytes": source_bytes}}
    finally:
        for handle in handles:
            handle.close()


def unpack(index: Path, output: Path, no_progress: bool = False) -> dict:
    started = time.monotonic()
    manifest = load_manifest(index)
    output.mkdir(parents=True, exist_ok=True)
    codec = PackizardLz4Codec()
    handles = []
    try:
        for pack_id in range(len(manifest.packs)):
            handle = (index.parent / manifest.pack_name(pack_id)).open("rb")
            validate_data_header(handle.read(64), pack_id, manifest.build_id)
            handles.append(handle)
        selected = [(file_id, record) for file_id, record in enumerate(manifest.files, 1) if record.flags & FILE_FLAG_PACKED]
        for position, (file_id, record) in enumerate(selected, 1):
            target = safe_output_path(output, asset_relative_path(manifest.file_path(file_id)))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as stream:
                for chunk_index in range(record.first_chunk, record.first_chunk + record.chunk_count):
                    stream.write(_read_chunk(manifest, handles, manifest.chunks[chunk_index], codec))
            _progress("unpack", int(position * 100 / max(1, len(selected))), f"unpacking {target.name}", started, no_progress)
        return {"files": len(selected), "output": str(output)}
    finally:
        for handle in handles:
            handle.close()


def rows(index: Path) -> list[dict]:
    manifest = load_manifest(index)
    return [{"file_id": file_id, "path": manifest.file_path(file_id), "size": record.logical_size, "packed": bool(record.flags & FILE_FLAG_PACKED), "chunks": record.chunk_count} for file_id, record in enumerate(manifest.files, 1)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="packizard_packer")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack")
    pack.add_argument("--root", type=Path, required=True)
    pack.add_argument("--ampr-index", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--config", type=Path)
    pack.add_argument("--exclude", action="append", default=[])
    pack.add_argument("--no-progress", action="store_true")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--index", type=Path, required=True)
    verify_parser.add_argument("--root", type=Path)
    verify_parser.add_argument("--no-progress", action="store_true")
    unpack_parser = sub.add_parser("unpack")
    unpack_parser.add_argument("--index", type=Path, required=True)
    unpack_parser.add_argument("--output", "--out", dest="output", type=Path, required=True)
    unpack_parser.add_argument("--no-progress", action="store_true")
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--index", type=Path, required=True)
    list_parser.add_argument("--json", action="store_true")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--index", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "pack":
        result = build(args.root, args.ampr_index, args.output, args.config, args.exclude, args.no_progress)
    elif args.command == "verify":
        result = verify(args.index, args.root, args.no_progress)
    elif args.command == "unpack":
        result = unpack(args.index, args.output, args.no_progress)
    elif args.command == "list":
        result = rows(args.index)
    else:
        manifest = load_manifest(args.index)
        result = {"engine": VERSION, "files": len(manifest.files), "chunks": len(manifest.chunks), "packs": len(manifest.packs), "build_id": manifest.build_id.hex()}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
