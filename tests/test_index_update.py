"""Offline-only index, initialization and transactional recovery tests."""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import lz4.block
import msgpack

from modtool.catalog import build_catalog, empty_catalog
from modtool.core import ModError, ModManager, sha
from modtool.formats import parse_master
from modtool.localmeta import LocalReader
from modtool.updater import IndexStore


def packed_tables(tables):
    directory, chunks, offset = {}, [], 0
    for name, rows in tables.items():
        raw = msgpack.packb(rows, use_bin_type=True)
        compressed = msgpack.packb(len(raw)) + lz4.block.compress(raw, store_size=False)
        chunk = msgpack.packb(msgpack.ExtType(99, compressed))
        directory[name] = [offset, len(chunk)]
        chunks.append(chunk)
        offset += len(chunk)
    return msgpack.packb(directory, use_bin_type=True) + b"".join(chunks)


def fixtures():
    master = packed_tables({"CardMaster": [[100, 100, 200, 0, 300, 0]],
        "CardResourceMaster": [[200, 123456780, 0]], "CardText": [[300, "card_name"]],
        "MasterTextLabel": [["card_name", "测试卡牌"]]})
    manifest = {"assets": [{"name": "Assets/_Wizard2Resources/Card/Textures/123456780",
                 "hash": "ABCDEFGH12345678", "key": 42, "size": 8}],
        "master": {"name": "Master/mastermemory.bytes", "hash": "MASTERDATA1234567", "size": len(master), "key": 0},
        "roots": [{"n": "//root", "h": "LOCALFINGERPRINT"}]}
    old = build_catalog(parse_master(master), manifest, "local:" + "9" * 64)
    old["cards"][0]["asset"]["original_sha256"] = "a" * 64
    return master, manifest, old


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="svwb-local-index-")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name)
        self.store = IndexStore(self.game)
        self.master, self.manifest, self.old = fixtures()
        data = self.game / "ShadowverseWB_Data/Persistent/dat/MA/MASTERDATA1234567"
        data.parent.mkdir(parents=True)
        data.write_bytes(self.master)
        self.mock_reader = patch("modtool.updater.LocalReader")
        reader = self.mock_reader.start()
        self.addCleanup(self.mock_reader.stop)
        self.read = reader.return_value.read
        self.read.return_value = self.manifest
        self.no_network = patch("socket.create_connection", side_effect=AssertionError("Network forbidden"))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    def test_local_refresh_reload_and_rollback(self):
        result = self.store.update(self.old)
        new = result["index"]
        self.assertTrue(result["updated"])
        self.assertTrue(new["version"].startswith("local:"))
        self.assertEqual(new["source"], "local")
        self.assertEqual(new["cards"][0]["name"], "测试卡牌")
        self.assertEqual(new["cards"][0]["asset"]["original_sha256"], "a" * 64)
        self.assertEqual(IndexStore(self.game).load(), (new, ""))
        self.assertEqual(self.store.rollback(new), self.old)
        self.assertEqual(self.store.load(), (self.old, ""))
        self.assertEqual(self.store.rollback(self.old), new)
        self.assertFalse((self.game / "SVWBModData/backups").exists())

    def test_empty_first_run_and_no_change(self):
        self.assertEqual(self.store.load(), (empty_catalog(), ""))
        result = self.store.update(empty_catalog())
        self.assertTrue(result["updated"])
        self.assertIsNone(result["index"]["cards"][0]["asset"]["original_sha256"])
        self.assertFalse((self.store.root / "previous.json").exists())
        result = self.store.update(result["index"])
        self.assertFalse(result["updated"])

    def test_failure_and_mixed_snapshot_keep_old(self):
        self.store.publish(self.old, empty_catalog())
        pointer = (self.store.root / "active.json").read_bytes()
        self.read.side_effect = ModError("not initialized")
        with self.assertRaises(ModError):
            self.store.update(self.old)
        self.assertEqual((self.store.root / "active.json").read_bytes(), pointer)
        changed = copy.deepcopy(self.manifest)
        changed["roots"][0]["h"] = "CHANGED"
        self.read.side_effect = [self.manifest, changed]
        with self.assertRaisesRegex(ValueError, "清单"):
            self.store.update(self.old)
        self.assertEqual((self.store.root / "active.json").read_bytes(), pointer)

    def test_atomic_failure_and_corrupt_pointer_fallback(self):
        self.store.publish(self.old, empty_catalog())
        pointer = (self.store.root / "active.json").read_bytes()
        from modtool.updater import write_json
        def fail(path, data):
            if Path(path).name == "active.json":
                raise OSError("disk full")
            write_json(path, data)
        with patch("modtool.updater.write_json", side_effect=fail):
            with self.assertRaises(OSError):
                self.store.update(self.old)
        self.assertEqual((self.store.root / "active.json").read_bytes(), pointer)
        (self.store.root / "active.json").write_text("broken", encoding="utf-8")
        loaded, warning = self.store.load()
        self.assertEqual(loaded, self.old)
        self.assertIn("active.json", warning)

    def test_old_online_index_never_used_for_search(self):
        old = dict(self.old, schema=1, version="12345")
        old.pop("source")
        pointer = self.store.save_object(old)
        (self.store.root / "active.json").write_text(json.dumps(pointer), encoding="utf-8")
        loaded, warning = self.store.load()
        self.assertEqual(loaded, empty_catalog())
        self.assertIn("旧在线索引", warning)
        (self.store.root / "previous.json").write_text(json.dumps(pointer), encoding="utf-8")
        self.assertFalse(self.store.has_previous())

    def test_missing_or_changed_master_rejected(self):
        path = self.game / "ShadowverseWB_Data/Persistent/dat/MA/MASTERDATA1234567"
        path.unlink()
        with self.assertRaises(ValueError):
            self.store.update(self.old)
        path.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.store.update(self.old)
        self.assertFalse((self.store.root / "active.json").exists())

    def test_changed_key_cannot_reuse_known_fingerprint(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["assets"][0]["key"] += 1
        self.read.return_value = manifest
        updated = self.store.update(self.old)["index"]
        self.assertIsNone(updated["cards"][0]["asset"]["original_sha256"])


class ReaderTests(unittest.TestCase):
    def test_disk_read_without_client_binary_or_process(self):
        _, manifest, _ = fixtures()
        with tempfile.TemporaryDirectory() as temp:
            reader = LocalReader(temp)
            @contextmanager
            def connection(key):
                self.assertEqual(key, b"disk-parameter")
                def query(sql):
                    if "table_info" in sql:
                        return [{"name": x} for x in ("n", "h", "l", "e")]
                    if "FROM c" in sql:
                        return manifest["roots"]
                    return [{"n": r["name"], "h": r["hash"], "l": str(r["size"]), "e": str(r["key"])}
                            for r in manifest["assets"] + [manifest["master"]]]
                yield query
            with patch("modtool.diskprefs.disk_key", return_value=b"disk-parameter") as disk, patch.object(reader, "connection", connection):
                self.assertEqual(reader.read(), manifest)
                self.assertIn("磁盘", reader.initialize())
                self.assertEqual(disk.call_count, 2)
            self.assertFalse((Path(temp) / "SVWBModData/local-reader").exists())

    def test_resource_fields_match_only_allowed_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            reader = LocalReader(temp)
            @contextmanager
            def connection(key):
                def query(sql):
                    if "table_info" in sql:
                        return [{"name": x} for x in ("n", "h", "l", "e")]
                    if "FROM c" in sql:
                        return [{"n": "//root", "h": "test"}]
                    return [{"n": "Assets/_Wizard2Resources/Card/Textures/123", "h": "ABCDEFGH", "l": "8", "e": "42"},
                            {"n": "Master/mastermemory.bytes", "h": "MASTERDATA", "l": "9", "e": "0"}]
                yield query
            with patch.object(reader, "connection", connection):
                result = reader.read(key=b"test")
            self.assertEqual(result["assets"][0]["key"], 42)
            self.assertEqual(result["master"]["size"], 9)


class OfflineBaselineTests(unittest.TestCase):
    def test_unknown_local_bytes_are_not_labeled_official(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp)
            (game / "ShadowverseWB.exe").touch()
            (game / "ShadowverseWB_Data/Persistent/dat").mkdir(parents=True)
            manager = ModManager(game, b"test")
            asset = {"hash": "ABCDEFGH", "key": 1, "size": 8, "original_sha256": None}
            result = manager.reference_asset(asset)
            self.assertIsNone(result["original_sha256"])
            self.assertFalse(manager.data_dir.exists())


if __name__ == "__main__":
    unittest.main()
