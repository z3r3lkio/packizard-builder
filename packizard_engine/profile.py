"""Packizard-owned trace profiler for the compatibility asset-pack format.

The profiler consumes the command journal only for direct APR file reads. It
keeps unobserved and boot/runtime-sensitive files loose and emits a conservative
Packizard pack configuration. Unknown packets never produce guessed reads.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import struct

CMD_HEADER = struct.Struct("<8sHHIQQQQQQIIIIIIII")
IDX_HEADER = struct.Struct("<8sIIQQQII")
IDX_RECORD = struct.Struct("<IIQq")

SAFETY_BASENAMES = {"eboot.bin", "ampr_emu.index", "ampr_assets.index", "param.sfo", "nptitle.dat"}
SAFETY_SUFFIXES = {".prx", ".sprx", ".self", ".elf"}
STREAM_SUFFIXES = {".bk2", ".mp4", ".m4v", ".webm", ".wem", ".ogg", ".mp3", ".aac", ".flac"}


def _load_index(path: Path) -> dict[int, tuple[str, int]]:
    data = path.read_bytes()
    if len(data) < IDX_HEADER.size:
        raise ValueError("Packizard compatibility index is truncated")
    magic, version, record_size, count, path_bytes, hash_offset, _slot_size, _slot_count = IDX_HEADER.unpack_from(data)
    if magic != b"AMPRIDX3" or version != 3 or record_size != IDX_RECORD.size:
        raise ValueError("unsupported compatibility index")
    records_at = IDX_HEADER.size
    paths_at = records_at + count * record_size
    paths_end = paths_at + path_bytes
    if paths_end > len(data) or hash_offset < paths_end:
        raise ValueError("invalid compatibility index layout")
    blob = data[paths_at:paths_end]
    result: dict[int, tuple[str, int]] = {}
    for i in range(count):
        off, length, size, _mtime = IDX_RECORD.unpack_from(data, records_at + i * record_size)
        if off + length > len(blob):
            raise ValueError("index path out of range")
        result[i + 1] = (blob[off:off + length].decode("utf-8", errors="replace"), size)
    return result


def _iter_direct_reads(path: Path):
    with path.open("rb") as fh:
        while True:
            raw = fh.read(CMD_HEADER.size)
            if not raw:
                return
            if len(raw) != CMD_HEADER.size:
                raise ValueError("truncated command journal header")
            fields = CMD_HEADER.unpack(raw)
            magic, version, header_bytes, record_bytes = fields[:4]
            payload_bytes = fields[10]
            priority = fields[13]
            if magic != b"AMPRCMD1" or version != 1:
                raise ValueError("unsupported command journal")
            if header_bytes < CMD_HEADER.size or record_bytes < header_bytes or record_bytes - header_bytes != payload_bytes:
                raise ValueError("invalid command journal record geometry")
            if header_bytes > CMD_HEADER.size:
                extra = fh.read(header_bytes - CMD_HEADER.size)
                if len(extra) != header_bytes - CMD_HEADER.size:
                    raise ValueError("truncated command journal extended header")
            payload = fh.read(payload_bytes)
            if len(payload) != payload_bytes:
                raise ValueError("truncated command journal payload")
            off = 0
            while off + 4 <= len(payload):
                w0 = struct.unpack_from("<I", payload, off)[0]
                opcode = w0 & 0xFF
                if opcode == 40:
                    dwords = ((w0 >> 8) & 7) + 1
                    if dwords not in (5, 6) or off + dwords * 4 > len(payload):
                        break
                    length = struct.unpack_from("<I", payload, off + 4)[0] + 1
                    file_id = struct.unpack_from("<I", payload, off + 8)[0] & 0x7FFFFFFF
                    w4 = struct.unpack_from("<I", payload, off + 16)[0]
                    file_offset = ((w0 >> 12) & 0x3FFFF) | (w4 & 0xFFFC0000)
                    if dwords == 6:
                        file_offset |= (struct.unpack_from("<I", payload, off + 20)[0] & 0xFF) << 32
                    yield file_id, file_offset, length, priority
                    off += dwords * 4
                    continue
                dwords = ((w0 >> 8) & 0xF) + 1
                if dwords <= 0 or off + dwords * 4 > len(payload):
                    break
                off += dwords * 4


def _block_for(size: int, reads: int, avg_read: float) -> int:
    if avg_read <= 16 * 1024 or reads >= 5000:
        return 16
    if avg_read <= 64 * 1024:
        return 32
    if size >= 4 * 1024**3 or avg_read >= 512 * 1024:
        return 128
    return 64


def generate(trace_pairs, name: str, output: Path, report: Path | None, metrics: Path | None, overwrite: bool) -> None:
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    stats = defaultdict(lambda: {"reads": 0, "bytes": 0, "max_end": 0, "priorities": Counter()})
    index_by_path: dict[str, int] = {}
    warnings: list[str] = []
    for commands, index_path in trace_pairs:
        index = _load_index(index_path)
        for _fid, (path, size) in index.items():
            index_by_path[path] = max(index_by_path.get(path, 0), size)
        try:
            for file_id, offset, length, priority in _iter_direct_reads(commands):
                entry = index.get(file_id)
                if entry is None:
                    warnings.append(f"unknown file id {file_id} in {commands.name}")
                    continue
                path, _size = entry
                item = stats[path]
                item["reads"] += 1
                item["bytes"] += length
                item["max_end"] = max(item["max_end"], offset + length)
                item["priorities"][priority] += 1
        except ValueError as exc:
            warnings.append(f"{commands}: {exc}")

    lines = [
        "# Generated by Packizard Engine trace profiler", f"# Profile: {name}", "",
        "[pack]", 'index_name = "ampr_assets.index"',
        'pack_pattern = "ampr_assets-{group}-lane{lane:02d}-vol{volume:02d}-{id:03d}.pak"',
        'default_action = "loose"', 'default_block_size = "64KiB"',
        'io_page_size = "64KiB"', 'compression_mode = "hc"',
        'compression_level = 9', 'min_savings_bytes = 64', 'min_savings_ratio = 0.01', "",
        "[runtime]", 'decoded_cache_bytes = "256MiB"', 'physical_cache_bytes = "64MiB"',
        'workers = 4', 'latency_reserve_workers = 1', "",
        "[groups.assets]", 'pack_count = 4', 'assignment = "balanced"',
        'max_pack_size = "16GiB"', 'stripe_large_files = false', "",
    ]
    rows = []
    for path in sorted(stats):
        rel = path.replace("\\", "/")
        if rel.lower().startswith("/app0/"):
            rel = rel[6:]
        size = index_by_path.get(path, 0)
        suffix = Path(rel).suffix.lower()
        base = Path(rel).name.lower()
        item = stats[path]
        avg = item["bytes"] / max(1, item["reads"])
        if base in SAFETY_BASENAMES or suffix in SAFETY_SUFFIXES or rel.startswith(("sce_sys/", "sce_module/", "system/", "fakelib/")):
            action, block = "loose", 64
        elif suffix in STREAM_SUFFIXES:
            action, block = "loose", 64
        else:
            action, block = "compress", _block_for(size, item["reads"], avg)
        if action == "compress":
            escaped = rel.replace('\\', '\\\\').replace('"', '\\"')
            lines.extend([
                "[[rule]]", 'action = "compress"', f'include = ["{escaped}"]',
                f'block_size = "{block}KiB"', 'group = "assets"',
                'layout = "random"' if block <= 32 else 'layout = "mixed"', "",
            ])
        rows.append({"path": rel, "size": size, "reads": item["reads"], "requested_bytes": item["bytes"], "average_read": avg, "action": action, "block_kib": block})

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    summary = {"engine": "Packizard Engine", "profile": name, "traces": len(trace_pairs), "observed_files": len(rows), "warnings": warnings, "files": rows}
    if metrics:
        metrics.parent.mkdir(parents=True, exist_ok=True)
        metrics.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "# Packizard trace profile\n\n" + f"Profile: `{name}`\n\nObserved files: {len(rows)}\n\n" +
            "| File | Reads | Requested bytes | Action | Block |\n|---|---:|---:|---|---:|\n" +
            "\n".join(f"| `{r['path']}` | {r['reads']} | {r['requested_bytes']} | {r['action']} | {r['block_kib']} KiB |" for r in rows) +
            ("\n\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings) if warnings else "") + "\n",
            encoding="utf-8",
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="packizard-profile")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("positional", nargs="*")
    gen.add_argument("--trace", nargs=2, action="append", metavar=("COMMANDS", "INDEX"), default=[])
    gen.add_argument("--name", default="game")
    gen.add_argument("--output", required=True)
    gen.add_argument("--report")
    gen.add_argument("--metrics")
    gen.add_argument("--overwrite", action="store_true")
    gen.add_argument("--pattern-mode", default="exact")
    gen.add_argument("--cache-sim", action="store_true")
    args = parser.parse_args(argv)
    pairs = [(Path(c), Path(i)) for c, i in args.trace]
    if not pairs and args.positional:
        root = Path(args.positional[0])
        commands = root / "ampr_commands.bin"
        index = root / "ampr_emu.index"
        if commands.is_file() and index.is_file():
            pairs = [(commands, index)]
    if not pairs:
        parser.error("at least one trace pair is required")
    generate(pairs, args.name, Path(args.output), Path(args.report) if args.report else None, Path(args.metrics) if args.metrics else None, args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
