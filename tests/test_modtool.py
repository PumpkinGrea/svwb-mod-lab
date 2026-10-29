"""Run against local resource copies; never modify the actual game directory."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat
from modtool.core import ModError, ModManager, TextureDocument, fit_image, sha

ROOT = Path(__file__).resolve().parents[1]


class ImageTests(unittest.TestCase):
    def test_fitting(self):
        image = Image.new("RGBA", (200, 100), "red")
        for mode in ("cover", "contain", "stretch"):
            self.assertEqual(fit_image(image, (64, 64), mode).size, (64, 64))
        contained = fit_image(image, (64, 64), "contain")
        self.assertEqual(contained.getpixel((0, 0)), (0, 0, 0, 255))
        self.assertEqual(contained.getpixel((32, 32)), (255, 0, 0, 255))


@unittest.skipUnless((ROOT / "input/test-fixtures/catalog.json").exists(), "Requires ignored local test resources")
class ResourceTests(unittest.TestCase):
    def setUp(self):
        # The fake game has no running process; ignore unrelated real installations.
        closed = patch("modtool.core.require_game_closed")
        closed.start()
        self.addCleanup(closed.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix="svwbmod-test-")
        self.addCleanup(self.temporary.cleanup)
        self.game = Path(self.temporary.name)
        (self.game / "ShadowverseWB.exe").touch()
        (self.game / "ShadowverseWB_Data/Persistent/dat").mkdir(parents=True)
        self.manager = ModManager(self.game, (ROOT / "local-keys/bundle-base.bin").read_bytes())
        catalog = json.loads((ROOT / "input/test-fixtures/catalog.json").read_text(encoding="utf-8"))
        self.assets = [next(c["asset"] for c in catalog["cards"] if c["texture_id"] == ident)
                       for ident in ("109741100", "109641100")]
        for asset in self.assets:
            target = self.manager.target(asset)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = ROOT / "cache-copy/dat" / asset["hash"][:2] / asset["hash"]
            target.write_bytes(source.read_bytes())

    def test_apply_repeat_backup_and_restore_all(self):
        for asset in self.assets:
            original = self.manager.target(asset).read_bytes()
            doc, image, expected = self.manager.read(asset)
            replacement = Image.new("RGBA", image.size, (220, 20, 160, 255))
            preview = self.manager.apply(asset, replacement, expected)
            self.assertEqual(preview.size, image.size)
            self.assertLess(sum(ImageStat.Stat(ImageChops.difference(preview.convert("RGB"), replacement.convert("RGB"))).mean), 12)
            self.assertEqual(self.manager.state(asset), "已替换")
            self.assertEqual((self.manager.backup_dir(asset) / "original.bin").read_bytes(), original)
            _, _, expected = self.manager.read(asset)
            self.manager.apply(asset, Image.new("RGBA", image.size, "blue"), expected)
            self.assertEqual((self.manager.backup_dir(asset) / "original.bin").read_bytes(), original)
            self.assertEqual(self.manager.read(asset)[0].encrypted, original)
        restored, errors = self.manager.restore_all()
        self.assertEqual((restored, errors), (2, []))
        for asset in self.assets:
            self.assertEqual(self.manager.state(asset), "已恢复")
            self.assertFalse(self.manager.restore(asset))

    def test_external_changes_are_not_overwritten(self):
        asset = self.assets[0]
        doc, image, expected = self.manager.read(asset)
        self.manager.apply(asset, image, expected)
        self.manager.target(asset).write_bytes(b"external update")
        with self.assertRaises(ModError):
            self.manager.restore(asset)
        with self.assertRaises(ModError):
            self.manager.read(asset)
        self.assertEqual(self.manager.target(asset).read_bytes(), b"external update")

    def test_original_fingerprint_and_preview_race(self):
        asset = self.assets[0]
        doc, image, expected = self.manager.read(asset)
        with self.assertRaises(ModError):
            self.manager.apply(asset, image, "incorrect-preview-sha")
        changed = dict(asset, original_sha256="0" * 64)
        with self.assertRaises(ModError):
            self.manager.read(changed)
        self.assertFalse(self.manager.backup_dir(asset).exists())

    def test_write_failure_keeps_original_and_backup(self):
        asset = self.assets[0]
        doc, image, expected = self.manager.read(asset)
        from modtool import core
        real_atomic = core.atomic_write
        def failing_write(path, data):
            if Path(path) == self.manager.target(asset):
                raise OSError("simulated disk error")
            return real_atomic(path, data)
        with patch("modtool.core.atomic_write", side_effect=failing_write):
            with self.assertRaises(OSError):
                self.manager.apply(asset, image, expected)
        self.assertEqual(sha(self.manager.target(asset).read_bytes()), expected)
        self.assertEqual(self.manager.backup_bytes(asset, self.manager.metadata(asset)), doc.encrypted)

    def test_corrupt_backup_and_path_traversal(self):
        asset = self.assets[0]
        doc, image, expected = self.manager.read(asset)
        self.manager.apply(asset, image, expected)
        (self.manager.backup_dir(asset) / "original.bin").write_bytes(b"corrupt")
        with self.assertRaises(ModError):
            self.manager.restore(asset)
        with self.assertRaises(ModError):
            self.manager.target(dict(asset, hash="../../not-a-cache"))

    def test_running_game_guard(self):
        with patch("modtool.core.require_game_closed", side_effect=ModError("game running")):
            with self.assertRaises(ModError):
                self.manager.restore_all()

    def test_offline_baseline_requires_explicit_consent_and_preserves_first_backup(self):
        asset = dict(self.assets[0], original_sha256=None)
        original = self.manager.target(asset).read_bytes()
        doc, image, expected = self.manager.read(asset)
        self.assertEqual(doc.asset["fingerprint_source"], "unconfirmed_local")
        self.assertFalse(self.manager.backup_dir(asset).exists())
        with self.assertRaises(ModError):
            self.manager.apply(asset, image, expected)
        self.assertEqual(self.manager.target(asset).read_bytes(), original)
        self.manager.apply(asset, image, expected, trust_local=True,
                           context={"name": "测试卡牌", "texture_id": "109741100", "index_version": "local:test"})
        self.assertEqual(self.manager.metadata(asset)["asset"]["fingerprint_source"], "user_confirmed_local")
        record = self.manager.metadata(asset)
        self.assertEqual(record["context"]["name"], "测试卡牌")
        self.assertIn("created_at", record)
        self.assertIn("modified_at", record)
        self.assertFalse(record.get("created_at_estimated", False))
        self.assertEqual(self.manager.backup_bytes(asset, self.manager.metadata(asset)), original)
        self.manager.restore(asset)
        self.assertEqual(self.manager.target(asset).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
