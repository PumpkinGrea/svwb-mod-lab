"""Backup management tests use only isolated synthetic files, never the real game."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modtool.core import ModError, ModManager, sha, write_json
from modtool.management import scan_backups, restore_entries


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="svwb-management-")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name)
        (self.game / "ShadowverseWB.exe").touch()
        (self.game / "ShadowverseWB_Data/Persistent/dat").mkdir(parents=True)
        self.manager = ModManager(self.game, b"synthetic-test")
        self.cards = []
        guard = patch("modtool.core.require_game_closed")
        guard.start()
        self.addCleanup(guard.stop)

    def backup(self, ident="123456780", state="modified"):
        asset = {"hash": "TESTCACHE" + ident, "key": 42, "size": 8,
                 "name": "Assets/_Wizard2Resources/Card/Textures/" + ident}
        original, modified = b"original", b"modified"
        directory = self.manager.backup_dir(asset)
        directory.mkdir(parents=True)
        (directory / "original.bin").write_bytes(original)
        write_json(directory / "record.json", {"asset": asset, "original_sha": sha(original),
                   "modded_shas": [sha(modified)], "context": {"name": "测试卡牌", "texture_id": ident}})
        target = self.manager.target(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        if state != "missing":
            target.write_bytes({"modified": modified, "restored": original, "external": b"external"}[state])
        self.cards.append({"name": "测试卡牌 " + ident, "texture_id": ident, "asset": asset})
        return asset

    def test_empty_inventory_does_not_create_files(self):
        self.assertEqual(scan_backups(self.manager, []), [])
        self.assertFalse(self.manager.data_dir.exists())

    def test_classification_and_legacy_time(self):
        for ident, state in [("100", "modified"), ("101", "restored"), ("102", "external"), ("103", "missing")]:
            self.backup(ident, state)
        before = {p: p.read_bytes() for p in self.game.rglob("*") if p.is_file()}
        rows = scan_backups(self.manager, self.cards)
        self.assertEqual([r["state"] for r in rows], ["modified", "restored", "external", "missing"])
        self.assertTrue(rows[0]["restorable"])
        self.assertTrue(rows[0]["time_estimated"])
        self.assertTrue(rows[0]["created_at"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.game.rglob("*") if p.is_file()})

    def test_missing_invalid_records_and_corrupt_backup_are_isolated(self):
        asset = self.backup("100")
        (self.manager.backup_dir(asset) / "original.bin").write_bytes(b"corrupt!")
        self.backup("101")
        for name, data in [("BADJSON1", b"{bad"), ("BADPATH1", b'{"asset":{"hash":"../../outside"}}')]:
            directory = self.manager.data_dir / "backups" / name
            directory.mkdir()
            (directory / "record.json").write_bytes(data)
        (self.manager.data_dir / "backups/ORPHAN01").mkdir()
        rows = scan_backups(self.manager, self.cards)
        self.assertEqual(sum(r["state"] == "invalid" for r in rows), 4)
        self.assertEqual(sum(r["restorable"] for r in rows), 1)
        self.assertFalse(any(r["restorable"] for r in rows if r["state"] == "invalid"))

    def test_updated_mapping_does_not_restore_still_present_old_cache(self):
        asset = self.backup()
        cards = copy.deepcopy(self.cards)
        cards[0]["asset"]["hash"] = "NEWCACHE12345678"
        entry = scan_backups(self.manager, cards)[0]
        self.assertEqual(entry["state"], "outdated")
        self.assertFalse(entry["restorable"])
        count, errors = restore_entries(self.manager, cards, [entry])
        self.assertEqual(count, 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.manager.target(asset).read_bytes(), b"modified")
        cards[0]["asset"] = dict(asset, key=43)
        self.assertEqual(scan_backups(self.manager, cards)[0]["state"], "outdated")

    def test_restore_selected_preserves_unselected_and_original_backup(self):
        first, second = self.backup("100"), self.backup("101")
        rows = scan_backups(self.manager, self.cards)
        self.assertEqual(restore_entries(self.manager, self.cards, [rows[0]]), (1, []))
        self.assertEqual(self.manager.target(first).read_bytes(), b"original")
        self.assertEqual(self.manager.target(second).read_bytes(), b"modified")
        self.assertEqual((self.manager.backup_dir(first) / "original.bin").read_bytes(), b"original")
        self.assertEqual(scan_backups(self.manager, self.cards)[0]["state"], "restored")

    def test_stale_selection_rejected_even_if_new_content_is_known_mod(self):
        asset = self.backup()
        row = scan_backups(self.manager, self.cards)[0]
        record = self.manager.metadata(asset)
        record["modded_shas"].append(sha(b"new mod!"))
        write_json(self.manager.backup_dir(asset) / "record.json", record)
        self.manager.target(asset).write_bytes(b"new mod!")
        count, errors = restore_entries(self.manager, self.cards, [row])
        self.assertEqual((count, len(errors)), (0, 1))
        self.assertEqual(self.manager.target(asset).read_bytes(), b"new mod!")
        with self.assertRaises(ModError):
            self.manager._restore(asset, expected_sha=row["current_sha"])

    def test_batch_restore_skips_bad_entries_without_hiding_good_ones(self):
        first, second = self.backup("100"), self.backup("101")
        external = self.backup("102", "external")
        count, errors = restore_entries(self.manager, self.cards, scan_backups(self.manager, self.cards))
        self.assertEqual((count, len(errors)), (2, 1))
        for asset in (first, second):
            self.assertEqual(self.manager.target(asset).read_bytes(), b"original")
        self.assertEqual(self.manager.target(external).read_bytes(), b"external")

    def test_running_game_restore_refused(self):
        self.backup()
        rows = scan_backups(self.manager, self.cards)
        with patch("modtool.core.require_game_closed", side_effect=ModError("game running")):
            with self.assertRaises(ModError):
                restore_entries(self.manager, self.cards, rows)

    def test_no_index_reports_limit_but_keeps_recovery_available(self):
        self.backup()
        row = scan_backups(self.manager, [])[0]
        self.assertTrue(row["restorable"])
        self.assertIn("不能确认", row["reason"])
        self.assertEqual(row["name"], "测试卡牌")


if __name__ == "__main__":
    unittest.main()
