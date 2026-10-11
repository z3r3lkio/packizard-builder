"""Memory-bounded verifier for Packizard packed files."""
from __future__ import annotations

from pathlib import Path


def verify_streaming(
    index: Path,
    root: Path | None,
    no_progress: bool = False,
    *,
    packer_module=None,
) -> dict:
    # Source CLI execution does not necessarily have the repository root on
    # sys.path. Prefer the module explicitly bound by install(); only resolve
    # the package import when verify_streaming is called independently.
    if packer_module is None:
        from packizard_engine import packer as packer_module
    p = packer_module

    started = p.time.monotonic()
    manifest = p.load_manifest(index)
    codec = p.PackizardLz4Codec()
    checksums = p.load_chunk_crcs(Path(str(index) + ".crc"), manifest.build_id, len(manifest.chunks))
    handles = []
    try:
        for pack_id in range(len(manifest.packs)):
            handle = (index.parent / manifest.pack_name(pack_id)).open("rb")
            p.validate_data_header(handle.read(64), pack_id, manifest.build_id)
            handles.append(handle)

        source_bytes = 0
        checked = 0
        packed_records = [
            (file_id, record)
            for file_id, record in enumerate(manifest.files, 1)
            if record.flags & p.FILE_FLAG_PACKED
        ]

        for position, (file_id, record) in enumerate(packed_records, 1):
            logical_bytes = 0
            source = None
            source_handle = None
            if root is not None:
                source = root / p.asset_relative_path(manifest.file_path(file_id))
                source_handle = source.open("rb")

            try:
                for chunk_index in range(record.first_chunk, record.first_chunk + record.chunk_count):
                    raw = p._read_chunk(manifest, handles, manifest.chunks[chunk_index], codec)
                    if p.crc32(raw) != checksums[chunk_index]:
                        raise ValueError(f"chunk CRC mismatch: {manifest.file_path(file_id)}")

                    logical_bytes += len(raw)
                    checked += 1

                    if source_handle is not None:
                        expected = source_handle.read(len(raw))
                        source_bytes += len(expected)
                        if expected != raw:
                            raise ValueError(f"source comparison failed: {source}")

                if logical_bytes != record.logical_size:
                    raise ValueError(
                        f"logical size mismatch: {manifest.file_path(file_id)} "
                        f"({logical_bytes}/{record.logical_size})"
                    )

                if source_handle is not None:
                    # The source must end at exactly the packed logical size. Reading one byte avoids
                    # materialising the source while still detecting a stale/larger source file.
                    if source_handle.read(1):
                        raise ValueError(f"source comparison failed: {source} (source is larger than manifest)")
                    if source_bytes < 0:  # defensive; keeps the counter explicitly non-negative.
                        raise AssertionError("source byte counter overflow")
            finally:
                if source_handle is not None:
                    source_handle.close()

            p._progress(
                "verify",
                int(position * 100 / max(1, len(packed_records))),
                f"verifying packed chunks files {position}/{len(packed_records)}",
                started,
                no_progress,
            )

        if root is not None:
            p._progress(
                "compare",
                100,
                f"comparing against source files {len(packed_records)}/{len(packed_records)}",
                started,
                no_progress,
            )
        return {"files": len(packed_records), "chunks": checked, "source_compare": {"bytes": source_bytes}}
    finally:
        for handle in handles:
            handle.close()


def install(packer_module=None) -> None:
    """Install the bounded verifier into an existing packer module."""
    if packer_module is None:
        from packizard_engine import packer as packer_module

    def _verify(index, root, no_progress=False):
        return verify_streaming(
            index,
            root,
            no_progress,
            packer_module=packer_module,
        )

    packer_module.verify = _verify
