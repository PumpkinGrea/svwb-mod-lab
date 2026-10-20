"""Offline parser tests; run with py -3 test-fetch-manifest.py."""
import hashlib
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("fetch_manifest", Path(__file__).with_name("fetch-manifest.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
msgpack = module.msgpack


def fixture(compressed=True, bad_offset=False):
    rows = {
        "asset": [["card/1", "ABC", 1, [1], -123, 500, "All", 4, 2**64-1]],
        "raw_asset": [["sample.pck", "DEF", 25, "All", 1, 12345]],
        "assetname": [["card/1", "card"]],
        "config": [["extension", "False"]],
    }
    tables = {}
    for name, value in rows.items():
        encoded = msgpack.packb(value, use_bin_type=True)
        if compressed and name != "config":
            encoded = msgpack.packb(msgpack.ExtType(99, msgpack.packb(len(encoded)) +
                module.lz4.block.compress(encoded, store_size=False)))
        tables[name] = encoded
    offset = 0
    toc = {}
    for name, data in tables.items():
        toc[name] = [offset, len(data)]
        offset += len(data)
    if bad_offset:
        toc["asset"][0] = 10**8
    body = msgpack.packb(toc, use_bin_type=True) + b"".join(tables.values())
    return body + hashlib.md5(body).digest()


class ParserTests(unittest.TestCase):
    def test_compressed(self):
        result, report = module.parse_manifest(fixture())
        self.assertEqual(result["assets"][0]["key"], -123)
        self.assertEqual(result["assets"][0]["checksum"], 2**64-1)
        self.assertEqual(result["raw_assets"][0]["extra_5"], 12345)
        self.assertTrue(report["body_md5_matches_trailer"])

    def test_uncompressed(self):
        result, _ = module.parse_manifest(fixture(compressed=False))
        self.assertEqual(len(result["assets"]), 1)

    def test_invalid_digest(self):
        with self.assertRaisesRegex(ValueError, "MD5"):
            module.parse_manifest(fixture()[:-1] + b"x")

    def test_invalid_offset(self):
        with self.assertRaisesRegex(ValueError, "out of bounds"):
            module.parse_manifest(fixture(bad_offset=True))

    def test_short(self):
        with self.assertRaises(ValueError):
            module.parse_manifest(b"short")


if __name__ == "__main__":
    unittest.main()
