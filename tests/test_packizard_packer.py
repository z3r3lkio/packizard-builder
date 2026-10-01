from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
if str(NATIVE) not in sys.path:
    sys.path.insert(0, str(NATIVE))

import packizard_container as container
import packizard_packer as packer


def build_source_index(root: Path, paths: list[str], size_overrides: dict[str, int] | None = None) -> Path:
    records = bytearray()
    strings = bytearray()
    size_overrides = size_overrides or {}
    for relative in paths:
        encoded = f"/app0/{relative}".encode("utf-8")
        offset = len(strings)
        strings.extend(encoded)
        strings.append(0)
        stat = (root / relative).stat()
        size = size_overrides.get(relative, stat.st_size)
        records.extend(container.AMPRIDX3_ENTRY.pack(offset, len(encoded), size, stat.st_mtime_ns))
    header_size = container.AMPRIDX3_HEADER.size
    hash_offset = header_size + len(records) + len(strings)
    data = container.AMPRIDX3_HEADER.pack(
        b"AMPRIDX3", 3, container.AMPRIDX3_ENTRY.size,
        len(paths), len(strings), hash_offset, 0, 0,
    ) + records + strings
    path = root / "ampr_emu.index"
    path.write_bytes(data)
    return path


class PackizardPackerTests(unittest.TestCase):
    def test_native_pack_verify_unpack_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            (source / "assets").mkdir(parents=True)
            (source / "sce_sys").mkdir()
            original = b"Packizard native data\n" * 12000
            (source / "assets" / "world.uasset").write_bytes(original)
            metadata = b'{"titleId":"PPSA00001"}'
            (source / "sce_sys" / "param.json").write_bytes(metadata)
            index = build_source_index(source, ["assets/world.uasset", "sce_sys/param.json"])
            config = base / "pack.toml"
            config.write_text(
                '[pack]\n'
                'default_action = "loose"\n'
                'default_block_size = "64KiB"\n'
                'io_page_size = "64KiB"\n'
                'compression_mode = "fast"\n'
                'compression_level = 1\n'
                '[runtime]\n'
                'decoded_cache_bytes = "64MiB"\n'
                'physical_cache_bytes = "32MiB"\n'
                'workers = 4\n'
                'latency_reserve_workers = 1\n'
                '[[rule]]\n'
                'action = "compress"\n'
                'include = ["assets/**"]\n',
                encoding="utf-8",
            )
            packed = base / "packed"
            result = packer.build(source, index, packed, config, ["sce_sys/**"], no_progress=True)
            self.assertEqual(result["engine"], packer.VERSION)
            self.assertEqual(result["loose_paths"], ["sce_sys/param.json"])
            manifest = container.load_manifest(packed / "ampr_assets.index")
            self.assertEqual(manifest.file_path(1), "/app0/assets/world.uasset")
            self.assertTrue(manifest.files[0].flags & container.FILE_FLAG_PACKED)
            self.assertFalse(manifest.files[1].flags & container.FILE_FLAG_PACKED)
            self.assertIsNotNone(container.read_runtime_settings(packed / "ampr_assets.index.runtime", manifest.build_id))
            verification = packer.verify(packed / "ampr_assets.index", source, no_progress=True)
            self.assertEqual(verification["source_compare"]["bytes"], len(original))
            extracted = base / "extracted"
            packer.unpack(packed / "ampr_assets.index", extracted, no_progress=True)
            self.assertEqual((extracted / "assets" / "world.uasset").read_bytes(), original)

    def test_loose_replacement_metadata_can_differ_from_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            (source / "fakelib").mkdir(parents=True)
            (source / "assets").mkdir()
            (source / "fakelib" / "libSceAmpr.sprx").write_bytes(b"old")
            (source / "assets" / "data.bin").write_bytes(b"A" * 65536)
            index = build_source_index(
                source,
                ["fakelib/libSceAmpr.sprx", "assets/data.bin"],
                {"fakelib/libSceAmpr.sprx": 4096},
            )
            config = base / "p.toml"
            config.write_text('[[rule]]\naction="compress"\ninclude=["assets/**"]\n', encoding="utf-8")
            packed = base / "packed"
            packer.build(source, index, packed, config, ["fakelib/**"], no_progress=True)
            manifest = container.load_manifest(packed / "ampr_assets.index")
            runtime = next(record for file_id, record in enumerate(manifest.files, 1) if manifest.file_path(file_id) == "/app0/fakelib/libSceAmpr.sprx")
            self.assertEqual(runtime.logical_size, 4096)
            self.assertFalse(runtime.flags & container.FILE_FLAG_PACKED)

    def test_compatibility_manifest_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            (source / "assets").mkdir(parents=True)
            (source / "assets" / "a.bin").write_bytes(b"A" * 131072)
            index = build_source_index(source, ["assets/a.bin"])
            config = base / "p.toml"
            config.write_text('[[rule]]\naction="compress"\ninclude=["**"]\n', encoding="utf-8")
            first = base / "one"
            second = base / "two"
            packer.build(source, index, first, config, [], no_progress=True)
            packer.build(source, index, second, config, [], no_progress=True)
            self.assertEqual((first / "ampr_assets.index").read_bytes(), (second / "ampr_assets.index").read_bytes())
            self.assertEqual(next(first.glob("*.pak")).read_bytes(), next(second.glob("*.pak")).read_bytes())


if __name__ == "__main__":
    unittest.main()
