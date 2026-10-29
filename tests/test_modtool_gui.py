"""Exercise actual Qt selection, import, preview, apply and restore on a temporary game."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtTest import QTest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from svwbmod import Window
from modtool.core import sha
from modtool.updater import IndexStore
from modtool.management_ui import ManagementDialog
from modtool.core import write_json

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / "input/mod-app-data/bundle-base.bin").exists(), "Requires local application data")
class GuiTests(unittest.TestCase):
    def setUp(self):
        closed = patch("modtool.core.require_game_closed")
        closed.start()
        self.addCleanup(closed.stop)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The offscreen platform may not discover Windows CJK fonts by itself.
        font_file = Path("C:/Windows/Fonts/msyh.ttc")
        if font_file.is_file():
            QFontDatabase.addApplicationFont(str(font_file))
            cls.app.setFont(QFont("Microsoft YaHei", 9))

    def wait_ready(self, window):
        deadline = time.monotonic() + 25
        while window.busy and time.monotonic() < deadline:
            QTest.qWait(50)
        self.assertFalse(window.busy, "Background operation did not finish")

    def seed_index(self, game):
        index = json.loads((ROOT / "input/test-fixtures/catalog.json").read_text(encoding="utf-8"))
        index.update(schema=2, source="local", version="local:" + "1" * 64)
        from modtool.catalog import empty_catalog
        IndexStore(game).publish(index, empty_catalog())

    def test_backup_management_filter_restore_and_preserve_backup(self):
        with tempfile.TemporaryDirectory(prefix="svwb-management-gui-") as temporary:
            game = Path(temporary)
            (game / "ShadowverseWB.exe").touch()
            (game / "ShadowverseWB_Data/Persistent/dat").mkdir(parents=True)
            window = Window(str(game), auto_check=False)
            dialog = None
            try:
                cards = []
                for ident, payload in [("100", b"modified"), ("101", b"external")]:
                    asset = {"name": "Assets/_Wizard2Resources/Card/Textures/" + ident,
                             "hash": "TESTCACHE" + ident, "key": 42, "size": 8}
                    directory = window.manager.backup_dir(asset)
                    directory.mkdir(parents=True)
                    (directory / "original.bin").write_bytes(b"original")
                    write_json(directory / "record.json", {"asset": asset, "original_sha": sha(b"original"), "modded_shas": [sha(b"modified")]})
                    target = window.manager.target(asset)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                    cards.append({"name": "测试卡" + ident, "texture_id": ident, "card_ids": [int(ident)], "relation": "test", "asset": asset})
                window.install_index({"schema": 2, "source": "local", "version": "local:" + "1" * 64, "cards": cards})
                dialog = ManagementDialog(window)
                dialog.show()
                QTest.qWait(50)
                self.wait_ready(dialog)
                self.assertEqual(dialog.table.rowCount(), 2)
                self.assertIn("可恢复 1", dialog.summary.text())
                screenshot = os.environ.get("SVWB_MANAGEMENT_SCREENSHOT")
                if screenshot:
                    dialog.grab().save(screenshot)
                dialog.search.setText("101")
                self.assertEqual(dialog.table.rowCount(), 1)
                dialog.table.selectRow(0)
                self.assertFalse(dialog.restore_selected_button.isEnabled())
                self.assertIn("无法区分", dialog.details.toPlainText())
                dialog.search.clear()
                dialog.state_filter.setCurrentIndex(1)
                self.assertEqual(dialog.table.rowCount(), 1)
                dialog.table.selectRow(0)
                self.assertTrue(dialog.restore_selected_button.isEnabled())
                with patch.object(dialog, "confirm", return_value=False):
                    dialog.restore_selected_button.click()
                    self.assertFalse(dialog.busy)
                    self.assertEqual(window.manager.target(cards[0]["asset"]).read_bytes(), b"modified")
                with patch.object(dialog, "confirm", return_value=True):
                    dialog.restore_selected_button.click()
                    self.wait_ready(dialog)
                self.assertTrue(dialog.changed)
                self.assertEqual(dialog.table.rowCount(), 0)
                self.assertFalse(dialog.restore_all_button.isEnabled())
                self.assertEqual(window.manager.target(cards[0]["asset"]).read_bytes(), b"original")
                self.assertEqual(window.manager.target(cards[1]["asset"]).read_bytes(), b"external")
                self.assertTrue((window.manager.backup_dir(cards[0]["asset"]) / "original.bin").is_file())
                dialog.state_filter.setCurrentIndex(0)
                self.assertEqual(dialog.table.rowCount(), 2)
            finally:
                if dialog:
                    self.wait_ready(dialog)
                    dialog.close()
                window.close()

    def test_empty_management_and_busy_close_guard(self):
        with tempfile.TemporaryDirectory(prefix="svwb-management-empty-") as temporary:
            game = Path(temporary)
            (game / "ShadowverseWB.exe").touch()
            (game / "ShadowverseWB_Data/Persistent/dat").mkdir(parents=True)
            window = Window(str(game), auto_check=False)
            dialog = ManagementDialog(window)
            try:
                dialog.show()
                QTest.qWait(50)
                self.wait_ready(dialog)
                self.assertIn("尚无备份", dialog.details.toPlainText())
                self.assertFalse(dialog.restore_selected_button.isEnabled())
                self.assertFalse(dialog.restore_all_button.isEnabled())
                self.assertFalse(dialog.locate_button.isEnabled())
                dialog.busy = True
                dialog.reject()
                self.assertTrue(dialog.isVisible())
                dialog.close()
                self.assertTrue(dialog.isVisible())
                dialog.busy = False
            finally:
                dialog.busy = False
                dialog.close()
                window.close()

    def test_search_import_crop_apply_restore(self):
        with tempfile.TemporaryDirectory(prefix="svwbmod-gui-") as temporary:
            game = Path(temporary)
            (game / "ShadowverseWB.exe").touch()
            cache = game / "ShadowverseWB_Data/Persistent/dat/J4"
            cache.mkdir(parents=True)
            target = cache / "J4L2U6EMMVQMUBU3V6UBDOTQHM"
            original = (ROOT / "cache-copy/dat/J4" / target.name).read_bytes()
            target.write_bytes(original)
            source_image = game / "replacement.png"
            Image.new("RGB", (1400, 900), "orange").save(source_image)
            errors = []
            self.seed_index(game)
            with patch.object(Window, "error", lambda window, message: errors.append(message)):
                window = Window(str(game), auto_check=False)
                try:
                    window.search.setText("卡特斯罗特")
                    window.filter_cards()
                    self.assertEqual(window.list.count(), 1)
                    window.list.setCurrentRow(0)
                    self.wait_ready(window)
                    self.assertIsNotNone(window.document)
                    self.assertEqual(window.selected["texture_id"], "109741100")
                    with patch("svwbmod.QFileDialog.getOpenFileName", return_value=(str(source_image), "PNG")):
                        window.import_image()
                    window.zoom.setValue(150)
                    window.horizontal.setValue(70)
                    self.assertTrue(window.apply_button.isEnabled())
                    with patch.object(window, "confirm", return_value=True):
                        window.apply()
                        self.wait_ready(window)
                        self.assertNotEqual(sha(target.read_bytes()), sha(original))
                        self.assertTrue(window.restore_button.isEnabled())
                        window.restore()
                        self.wait_ready(window)
                    self.assertEqual(target.read_bytes(), original)
                    self.assertEqual(errors, [])
                    self.assertEqual(window.manager.state(window.selected["asset"]), "已恢复")
                finally:
                    self.wait_ready(window)
                    window.close()

    def test_manual_update_reload_rollback_and_failure(self):
        with tempfile.TemporaryDirectory(prefix="svwbmod-gui-index-") as temporary:
            game = Path(temporary)
            (game / "ShadowverseWB.exe").touch()
            (game / "ShadowverseWB_Data/Persistent/dat").mkdir(parents=True)
            errors = []
            self.seed_index(game)
            with patch.object(Window, "error", lambda window, message: errors.append(message)):
                window = Window(str(game), auto_check=False)
                try:
                    original = window.index
                    newer = dict(original, version="local:" + "2" * 64)
                    def updated(store, current, force=False):
                        self.assertTrue(force)
                        store.publish(newer, current)
                        return {"updated": True, "index": newer, "message": "updated"}
                    with patch.object(IndexStore, "update", updated):
                        window.update_button.click()
                        self.wait_ready(window)
                    self.assertEqual(window.index["version"], newer["version"])
                    self.assertIn("2222222222222222", window.note.text())
                    self.assertTrue(window.rollback_button.isEnabled())
                    with patch.object(window, "confirm", return_value=True):
                        window.rollback_button.click()
                        self.wait_ready(window)
                    self.assertEqual(window.index, original)
                    with patch.object(IndexStore, "update", side_effect=TimeoutError("offline")):
                        window.update_index(True)
                        self.wait_ready(window)
                    self.assertIn("offline", window.status.text())
                    self.assertEqual(errors, [])
                    self.assertEqual(window.index, original)
                    self.assertEqual(IndexStore(game).load()[0], original)
                finally:
                    self.wait_ready(window)
                    window.close()


if __name__ == "__main__":
    unittest.main()
