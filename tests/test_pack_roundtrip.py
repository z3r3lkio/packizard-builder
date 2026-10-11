# ruff: noqa: I001
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.lz4_packer import TOOLS_DIR, run_lz4_pack
from packizard_engine.container import FILE_FLAG_PACKED, load_manifest
from utils.process_manager import ExtractWorker, GameWorker


class PackRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lazy_ampr_pack_test_"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_gui_maps_verification_and_copy_to_distinct_progress_stages(self):
        worker = GameWorker(self.root / "source", self.root / "output", {})
        progress = []
        statuses = []
        worker.progress_updated.connect(progress.append)
        worker.status_updated.connect(statuses.append)

        worker._pack_progress(0.5, "verify")
        worker._pack_progress(0.5, "compare")
        worker._pack_progress(0.5, "loose")

        self.assertEqual(progress, [88, 95, 98])
        self.assertEqual(
            statuses,
            [
                "Verifying packed chunks…",
                "Comparing against source…",
                "Placing loose files…",
            ],
        )

    def test_pack_and_extract_reconstructs_game_tree(self):
        source = self.root / "game"
        (source / "assets").mkdir(parents=True)
        (source / "sce_sys").mkdir()
        packed_data = (b"compressible asset data\n" * 8192)
        (source / "assets" / "world.uasset").write_bytes(packed_data)
        metadata = b'{"titleId":"PPSA00001"}'
        (source / "sce_sys" / "param.json").write_bytes(metadata)

        packed = self.root / "packed"
        run_lz4_pack(
            source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            workers=1,
        )
        self.assertTrue((packed / "ampr_assets.index").is_file())
        self.assertTrue(any(packed.glob("ampr_assets-*.pak")))

        extracted = self.root / "extracted"
        outcomes = []
        worker = ExtractWorker(packed, extracted)
        worker.finished.connect(lambda ok, message: outcomes.append((ok, message)))
        worker.run()

        self.assertTrue(outcomes and outcomes[-1][0], outcomes[-1][1] if outcomes else "no result")
        self.assertEqual((extracted / "assets" / "world.uasset").read_bytes(), packed_data)
        self.assertEqual((extracted / "sce_sys" / "param.json").read_bytes(), metadata)

    def test_verify_cli_reports_both_stages_and_keeps_json_on_stdout(self):
        source = self.root / "verify-source"
        (source / "assets").mkdir(parents=True)
        (source / "assets" / "data.bin").write_bytes(b"verify me\n" * 16384)
        packed = self.root / "verify-packed"
        run_lz4_pack(
            source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            skip_verify=True,
            workers=1,
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "packer.py"),
                "verify",
                "--index",
                str(packed / "ampr_assets.index"),
                "--root",
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertGreater(result["files"], 0)
        self.assertGreater(result["source_compare"]["bytes"], 0)
        self.assertIn("[verify 100%] verifying packed chunks", completed.stderr)
        self.assertIn("[compare 100%] comparing against source", completed.stderr)
        self.assertIn("files 1/1", completed.stderr)
        self.assertIn("elapsed ", completed.stderr)
        self.assertNotIn("ETA ", completed.stderr)

    def test_gui_timing_reports_elapsed_time_instead_of_eta(self):
        source = self.root / "elapsed-source"
        (source / "assets").mkdir(parents=True)
        (source / "assets" / "data.bin").write_bytes(b"elapsed\n" * 8192)
        timings = []

        run_lz4_pack(
            source,
            self.root / "elapsed-packed",
            {"lz4_level": 1, "auto_loose_large": False},
            skip_verify=True,
            workers=1,
            eta_callback=timings.append,
        )

        self.assertTrue(any(value.startswith("Elapsed ") for value in timings), timings)
        self.assertFalse(any(value.startswith("ETA ") for value in timings), timings)

    def test_pack_regenerates_output_index_for_replacement_without_changing_source(self):
        source = self.root / "fakelib-source"
        (source / "assets").mkdir(parents=True)
        (source / "fakelib").mkdir()
        (source / "assets" / "data.bin").write_bytes(b"asset\n" * 8192)
        (source / "fakelib" / "libSceAmpr.sprx").write_bytes(b"sprx")
        source_index = source / "ampr_emu.index"
        source_index.write_bytes(b"stale")
        packed = self.root / "fakelib-packed"

        run_lz4_pack(
            source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            skip_verify=True,
            workers=1,
        )

        # The release path replaces the output runtime, so its index must be regenerated.
        # separately instead of putting replacement metadata into the source.
        self.assertEqual(source_index.read_bytes(), b"stale")
        self.assertTrue((packed / "ampr_emu.index").read_bytes().startswith(b"AMPRIDX3"))

    def test_read_only_source_builds_fakelib_index_only_in_output(self):
        source = self.root / "mounted-fakelib-source"
        (source / "assets").mkdir(parents=True)
        (source / "fakelib").mkdir()
        (source / "assets" / "data.bin").write_bytes(b"asset\n" * 8192)
        (source / "fakelib" / "libSceAmpr.sprx").write_bytes(b"sprx")
        source_index = source / "ampr_emu.index"
        source_index.write_bytes(b"source-must-remain-unchanged")
        packed = self.root / "mounted-fakelib-packed"

        run_lz4_pack(
            source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            source_read_only=True,
            skip_verify=True,
            workers=1,
        )

        self.assertEqual(source_index.read_bytes(), b"source-must-remain-unchanged")
        self.assertTrue((packed / "ampr_emu.index").read_bytes().startswith(b"AMPRIDX3"))

    def test_balanced_lanes_roll_over_and_verify(self):
        source = self.root / "lane-source"
        (source / "assets").mkdir(parents=True)
        # Four equally sized incompressible files distribute 2+2 across two lanes.
        for index in range(4):
            (source / "assets" / f"part{index}.bin").write_bytes(
                bytes(((byte + index * 37) & 0xFF) for byte in range(256)) * 320
            )

        config = self.root / "lane-profile.toml"
        config.write_text(
            """
[pack]
default_action = "loose"
default_block_size = "64KiB"
io_page_size = "64KiB"
compression_mode = "fast"
compression_level = 1
min_savings_bytes = "1MiB"
min_savings_ratio = 0.99

[groups.assets]
pack_count = 2
assignment = "balanced"
max_pack_size = "160KiB"

[[rule]]
action = "compress"
include = ["assets/**"]
group = "assets"
block_size = "64KiB"
force_pack = true
""".strip() + "\n",
            encoding="utf-8",
        )

        packed = self.root / "lane-packed"
        run_lz4_pack(
            source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            custom_config=config,
            skip_verify=False,
            workers=1,
        )

        manifest = load_manifest(packed / "ampr_assets.index")
        names = [manifest.pack_name(pack_id) for pack_id in range(len(manifest.packs))]
        self.assertGreaterEqual(len(names), 4)
        self.assertTrue(any("lane00-vol00" in name for name in names), names)
        self.assertTrue(any("lane00-vol01" in name for name in names), names)
        self.assertTrue(any("lane01-vol00" in name for name in names), names)
        self.assertTrue(any("lane01-vol01" in name for name in names), names)

        used_pack_ids = {
            chunk.pack_id
            for chunk in manifest.chunks
        }
        self.assertGreaterEqual(len(used_pack_ids), 4)

    def test_custom_catch_all_cannot_pack_required_ps5_metadata(self):
        source = self.root / "custom-safety-source"
        (source / "assets").mkdir(parents=True)
        (source / "sce_sys").mkdir()
        asset = b"compressible\n" * 8192
        metadata = b'{"titleId":"PPSA00001"}'
        (source / "assets" / "data.bin").write_bytes(asset)
        (source / "sce_sys" / "param.json").write_bytes(metadata)
        config = self.root / "catch-all.toml"
        config.write_text(
            '[[rule]]\naction = "compress"\ninclude = ["**/*"]\nforce_pack = true\n',
            encoding="utf-8",
        )
        packed = self.root / "custom-safety-packed"

        run_lz4_pack(
            source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            custom_config=config,
            skip_verify=True,
            workers=1,
        )

        manifest = load_manifest(packed / "ampr_assets.index")
        placements = {
            manifest.file_path(file_id): bool(record.flags & FILE_FLAG_PACKED)
            for file_id, record in enumerate(manifest.files, 1)
        }
        self.assertTrue(placements["/app0/assets/data.bin"])
        self.assertFalse(placements["/app0/sce_sys/param.json"])
        self.assertEqual((packed / "sce_sys" / "param.json").read_bytes(), metadata)
