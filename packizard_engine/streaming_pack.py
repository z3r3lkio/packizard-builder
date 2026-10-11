"""Bounded-memory Packizard pack implementation.

The legacy builder retained every source file and every encoded payload in memory
until the final .pak write. This module keeps the manifest metadata in memory but
streams source blocks directly into the destination pack and back-fills the
header after the deterministic build id is known.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import sys

from packizard_container import (
    CHUNK_CODEC_LZ4,
    CHUNK_CODEC_RAW,
    CHUNK_FLAG_PAGE_ALIGNED,
    CHUNK_FLAG_PAGE_CONTAINED,
    FILE_FLAG_PACKED,
    PACK_FLAG_IO_PAGE_LAYOUT,
    ChunkRecord,
    FileRecord,
    PackRecord,
    RuntimeSettings,
    StringTable,
    align_up,
    asset_path_hash,
    asset_relative_path,
    block_shift,
    build_chunk_crc_bytes,
    build_data_header,
    build_manifest_bytes,
    crc32,
    deterministic_build_id,
    parse_size,
    read_ampridx3,
    safe_output_path,
)
from packizard_lz4 import PackizardLz4Codec


def _rule_value(rule: dict, pack_cfg: dict, name: str, default):
    if isinstance(rule, dict) and name in rule:
        return rule[name]
    return pack_cfg.get(name, default)


def _encoding_policy(rule: dict, pack_cfg: dict, io_page: int) -> dict:
    return {
        "mode": str(_rule_value(rule, pack_cfg, "compression_mode", "hc")).lower(),
        "level": int(_rule_value(rule, pack_cfg, "compression_level", 9)),
        "acceleration": max(1, int(_rule_value(rule, pack_cfg, "acceleration", 1))),
        "min_savings": parse_size(_rule_value(rule, pack_cfg, "min_savings_bytes", 64)),
        "min_ratio": float(_rule_value(rule, pack_cfg, "min_savings_ratio", 0.01)),
        "neutral_savings": parse_size(
            _rule_value(rule, pack_cfg, "io_neutral_min_savings_bytes", "8KiB")
        ),
        "neutral_ratio": float(
            _rule_value(rule, pack_cfg, "io_neutral_min_savings_ratio", 0.125)
        ),
        "io_page": io_page,
    }


def _encoded_is_worthwhile(raw_size: int, stored_size: int, policy: dict) -> bool:
    if raw_size <= 0 or stored_size >= raw_size:
        return False
    savings = raw_size - stored_size
    ratio = savings / raw_size
    if savings < policy["min_savings"] or ratio < policy["min_ratio"]:
        return False

    # If both representations consume the same number of runtime I/O pages,
    # demand the stricter "I/O neutral" threshold. This avoids spending CPU
    # merely to save bytes that do not reduce physical reads.
    page = policy["io_page"]
    raw_pages = align_up(raw_size, page)
    stored_pages = align_up(stored_size, page)
    if raw_pages == stored_pages:
        if savings < policy["neutral_savings"] or ratio < policy["neutral_ratio"]:
            return False
    return True


def _encode_chunk_task(raw: bytes, policy: dict) -> tuple[bytes, int, int, int]:
    codec = PackizardLz4Codec()
    compressed = codec.compress(
        raw,
        mode=policy["mode"],
        level=policy["level"],
        acceleration=policy["acceleration"],
    )
    if _encoded_is_worthwhile(len(raw), len(compressed), policy):
        return compressed, CHUNK_CODEC_LZ4, crc32(raw), len(raw)
    return raw, CHUNK_CODEC_RAW, crc32(raw), len(raw)


def _sample_block_indices(size: int, block_size: int, max_blocks: int, max_bytes: int) -> list[int]:
    total = (size + block_size - 1) // block_size
    if total <= 0:
        return []
    by_bytes = max(1, max_bytes // block_size)
    count = max(1, min(max_blocks, by_bytes, total))
    if total <= count:
        return list(range(total))
    if count == 1:
        return [total // 2]
    result = []
    for sample in range(count):
        value = sample * (total - 1) // (count - 1)
        if not result or result[-1] != value:
            result.append(value)
    return result


def _auto_loose_decision(
    source: Path,
    relative: str,
    rule: dict,
    shift: int,
    pack_cfg: dict,
    io_page: int,
) -> tuple[bool, str | None]:
    if not bool(pack_cfg.get("auto_loose_large_files", False)):
        return False, None
    if bool(rule.get("force_pack", False)):
        return False, None
    if bool(rule.get("hot", False)) and not bool(pack_cfg.get("auto_loose_hot_files", False)):
        return False, None

    size = source.stat().st_size
    minimum = parse_size(pack_cfg.get("auto_loose_min_file_size", "64MiB"))
    if size < minimum or size <= 0:
        return False, None

    block_size = 1 << shift
    sample_blocks = int(pack_cfg.get("auto_loose_sample_blocks", 32))
    sample_bytes = parse_size(pack_cfg.get("auto_loose_sample_bytes", "16MiB"))
    min_ratio = float(pack_cfg.get("auto_loose_min_savings_ratio", 0.05))
    max_raw_ratio = float(pack_cfg.get("auto_loose_max_raw_ratio", 0.90))
    if not 1 <= sample_blocks <= 4096 or sample_bytes <= 0:
        raise ValueError("auto-loose sampling settings are out of range")

    policy = _encoding_policy(rule, pack_cfg, io_page)
    indices = _sample_block_indices(size, block_size, sample_blocks, sample_bytes)
    before = source.stat()
    sampled = 0
    stored = 0
    raw_chunks = 0
    with source.open("rb") as stream:
        for block in indices:
            offset = block * block_size
            stream.seek(offset)
            raw = stream.read(min(block_size, size - offset))
            if not raw:
                raise RuntimeError(f"source was truncated while sampling: {relative}")
            encoded, chunk_codec, _crc, raw_len = _encode_chunk_task(raw, policy)
            sampled += raw_len
            stored += len(encoded)
            raw_chunks += chunk_codec == CHUNK_CODEC_RAW

    after = source.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
    ):
        raise RuntimeError(f"source changed while sampling: {relative}")

    savings_ratio = 1.0 - (stored / sampled if sampled else 1.0)
    raw_ratio = raw_chunks / max(1, len(indices))
    use_loose = savings_ratio < min_ratio or raw_ratio >= max_raw_ratio
    if not use_loose:
        return False, None
    return True, (
        f"auto-loose: {relative} size={size} "
        f"saving={savings_ratio * 100:.2f}% rawBlocks={raw_ratio * 100:.2f}%"
    )


def build_streaming(
    root: Path,
    ampr_index: Path,
    output: Path,
    config_path: Path | None,
    excludes: list[str],
    no_progress: bool,
    *,
    load_config,
    rule_for,
    matches,
    progress,
    canonical_config_bytes,
    version: str,
) -> dict:
    import time

    started = time.monotonic()
    root = root.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = load_config(config_path)
    pack_cfg = config.get("pack", {}) if isinstance(config.get("pack", {}), dict) else {}
    default_shift = block_shift(pack_cfg.get("default_block_size", "64KiB"))
    io_page = parse_size(pack_cfg.get("io_page_size", "64KiB"))
    if io_page < 4096 or io_page & (io_page - 1):
        raise ValueError("invalid io_page_size")

    workers = max(1, int(pack_cfg.get("workers", max(1, (os.cpu_count() or 2) - 1))))
    max_in_flight = max(1, workers * 2)

    entries = read_ampridx3(ampr_index)
    strings = StringTable()
    files: list[FileRecord] = []
    chunks: list[ChunkRecord] = []
    checksums: list[int] = []
    loose: list[str] = []
    selected: dict[int, tuple[Path, str, dict, int]] = {}
    auto_loose_messages: list[str] = []

    for file_id, entry in enumerate(entries, 1):
        relative = asset_relative_path(entry.path)
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(f"indexed source missing: {relative}")
        action, rule = rule_for(config, relative)
        forced_loose = any(matches(relative, pattern) for pattern in excludes)
        should_pack = action in {"pack", "compress"} and not forced_loose
        shift = block_shift(rule.get("block_size", 1 << default_shift)) if rule else default_shift
        if should_pack:
            if source.stat().st_size != entry.size:
                raise RuntimeError(f"indexed packed source size changed: {relative}")
            use_loose, message = _auto_loose_decision(
                source, relative, rule, shift, pack_cfg, io_page
            )
            if use_loose:
                loose.append(relative)
                if message:
                    auto_loose_messages.append(message)
                    print(f"[INFO] {message}", file=sys.stderr, flush=True)
            else:
                selected[file_id] = (source, relative, rule, shift)
        else:
            loose.append(relative)

    total_bytes = sum(entries[file_id - 1].size for file_id in selected)
    done_bytes = 0

    pack_pattern = str(
        pack_cfg.get(
            "pack_pattern",
            "ampr_assets-{group}-lane{lane:02d}-vol{volume:02d}-{id:03d}.pak",
        )
    )
    pack_name = pack_pattern.format(group="default", lane=0, volume=0, id=0)
    pack_path = safe_output_path(output, pack_name)
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    payload_offset = io_page

    try:
        with pack_path.open("w+b") as handle:
            # Reserve the fixed header/page. The real header depends on build_id,
            # which itself depends on the completed chunk table.
            handle.seek(payload_offset)

            for file_id, entry in enumerate(entries, 1):
                path_offset, path_length = strings.add(entry.path)
                item = selected.get(file_id)
                if item is None:
                    files.append(
                        FileRecord(
                            asset_path_hash(entry.path),
                            entry.size,
                            entry.mtime,
                            0,
                            0,
                            path_offset,
                            path_length,
                            0,
                            0,
                        )
                    )
                    continue

                source, relative, rule, shift = item
                block_size = 1 << shift
                first_chunk = len(chunks)
                logical_size = 0

                policy = _encoding_policy(rule, pack_cfg, io_page)

                def commit_encoded(result):
                    nonlocal logical_size, done_bytes
                    stored, chunk_codec, checksum, raw_len = result
                    aligned = align_up(handle.tell(), io_page)
                    gap = aligned - handle.tell()
                    if gap:
                        handle.write(b"\x00" * gap)
                    chunk_offset = handle.tell()
                    handle.write(stored)

                    placement_flags = CHUNK_FLAG_PAGE_ALIGNED
                    if len(stored) <= io_page:
                        placement_flags |= CHUNK_FLAG_PAGE_CONTAINED
                    chunks.append(
                        ChunkRecord(
                            chunk_offset,
                            len(stored),
                            raw_len,
                            0,
                            chunk_codec,
                            placement_flags,
                        )
                    )
                    checksums.append(checksum)
                    logical_size += raw_len
                    done_bytes += raw_len
                    progress(
                        "packing",
                        int(done_bytes * 80 / max(1, total_bytes)),
                        f"packing {relative}",
                        started,
                        no_progress,
                    )

                with source.open("rb") as src:
                    if workers == 1:
                        while True:
                            raw = src.read(block_size)
                            if not raw:
                                break
                            commit_encoded(_encode_chunk_task(raw, policy))
                    else:
                        # Bounded producer/consumer pipeline. Results are committed in
                        # source order, preserving deterministic chunk tables while
                        # compression runs on multiple CPU cores.
                        with ProcessPoolExecutor(max_workers=workers) as pool:
                            pending = []
                            while True:
                                while len(pending) < max_in_flight:
                                    raw = src.read(block_size)
                                    if not raw:
                                        break
                                    pending.append(pool.submit(_encode_chunk_task, raw, policy))
                                if not pending:
                                    break
                                commit_encoded(pending.pop(0).result())

                if logical_size != entry.size:
                    raise RuntimeError(
                        f"packed source size changed while reading: {relative} "
                        f"({logical_size}/{entry.size})"
                    )
                files.append(
                    FileRecord(
                        asset_path_hash(entry.path),
                        logical_size,
                        entry.mtime,
                        first_chunk,
                        len(chunks) - first_chunk,
                        path_offset,
                        path_length,
                        FILE_FLAG_PACKED,
                        shift,
                    )
                )

            final_size = align_up(handle.tell(), io_page)
            if handle.tell() < final_size:
                handle.write(b"\x00" * (final_size - handle.tell()))

            name_offset, name_length = strings.add(pack_name)
            pack_record = PackRecord(
                final_size - payload_offset,
                final_size,
                name_offset,
                name_length,
                PACK_FLAG_IO_PAGE_LAYOUT,
                io_page,
            )
            crc_payload = b"".join(int(value).to_bytes(4, "little") for value in checksums)
            build_id = deterministic_build_id(
                (
                    canonical_config_bytes(config),
                    b"".join(item.pack() for item in files),
                    b"".join(item.pack() for item in chunks),
                    crc_payload,
                    pack_record.pack(),
                    strings.bytes(),
                )
            )

            header = build_data_header(0, build_id, payload_offset, final_size - payload_offset)
            if len(header) > payload_offset:
                raise RuntimeError("pack header exceeds reserved payload offset")
            handle.seek(0)
            handle.write(header)
            handle.flush()

        index_name = str(pack_cfg.get("index_name", "ampr_assets.index"))
        index_path = safe_output_path(output, index_name)
        index_path.write_bytes(
            build_manifest_bytes(build_id, files, chunks, [pack_record], strings.bytes())
        )
        Path(str(index_path) + ".crc").write_bytes(
            build_chunk_crc_bytes(build_id, checksums)
        )
        runtime_cfg = config.get("runtime")
        if isinstance(runtime_cfg, dict):
            settings = RuntimeSettings(
                parse_size(runtime_cfg.get("decoded_cache_bytes", 0)),
                parse_size(runtime_cfg.get("physical_cache_bytes", 0)),
                int(runtime_cfg.get("workers", 4)),
                int(runtime_cfg.get("latency_reserve_workers", 0)),
            )
            Path(str(index_path) + ".runtime").write_bytes(settings.encode(build_id))

        progress("packing", 100, "Packizard pack complete", started, no_progress)
        return {
            "index": str(index_path),
            "packs": [pack_name],
            "crc": index_path.name + ".crc",
            "files": len(files),
            "packed_files": len(selected),
            "loose_paths": sorted(loose),
            "engine": version,
            "workers": workers,
            "auto_loose_paths": sorted(
                message.split(": ", 1)[1].split(" size=", 1)[0]
                for message in auto_loose_messages
            ),
        }
    except Exception:
        pack_path.unlink(missing_ok=True)
        raise


def install() -> None:
    """Replace packer.build in the frozen worker with the bounded-memory implementation."""
    from packizard_engine import packer

    def _build(root, ampr_index, output, config_path, excludes, no_progress=False):
        return build_streaming(
            root,
            ampr_index,
            output,
            config_path,
            excludes,
            no_progress,
            load_config=packer._load_config,
            rule_for=packer._rule_for,
            matches=packer._matches,
            progress=packer._progress,
            canonical_config_bytes=packer._canonical_config_bytes,
            version=packer.VERSION,
        )

    packer.build = _build
