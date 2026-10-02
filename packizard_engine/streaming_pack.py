"""Bounded-memory Packizard pack implementation.

The legacy builder retained every source file and every encoded payload in memory
until the final .pak write. This module keeps the manifest metadata in memory but
streams source blocks directly into the destination pack and back-fills the
header after the deterministic build id is known.
"""
from __future__ import annotations

from pathlib import Path

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
    codec = PackizardLz4Codec()
    selected: dict[int, tuple[Path, str, dict, int]] = {}

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

                with source.open("rb") as src:
                    while True:
                        raw = src.read(block_size)
                        if not raw:
                            break

                        compressed = codec.compress(
                            raw,
                            mode=str(rule.get("compression_mode", mode)),
                            level=int(rule.get("compression_level", level)),
                            acceleration=acceleration,
                        )
                        savings = len(raw) - len(compressed)
                        use_lz4 = (
                            len(raw) > 0
                            and savings >= min_savings
                            and savings / max(1, len(raw)) >= min_ratio
                        )
                        stored = compressed if use_lz4 else raw
                        if not stored and not raw:
                            continue

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
                                len(raw),
                                0,
                                CHUNK_CODEC_LZ4 if use_lz4 else CHUNK_CODEC_RAW,
                                placement_flags,
                            )
                        )
                        checksums.append(crc32(raw))
                        logical_size += len(raw)
                        done_bytes += len(raw)
                        progress(
                            "packing",
                            int(done_bytes * 80 / max(1, total_bytes)),
                            f"packing {relative}",
                            started,
                            no_progress,
                        )
                        # raw/compressed/stored fall out of scope on the next iteration;
                        # no game-sized payload collection is retained.

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
