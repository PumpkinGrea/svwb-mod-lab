"""Bounded serialized configuration and encrypted entry validation."""
import base64
import struct
import unittest
from modtool.core import ModError
from modtool.diskprefs import parse_entries, decode_key


def serialized(pairs):
    raw = bytearray(28)
    def string(value):
        raw.extend(struct.pack('<i', len(value)))
        raw.extend(value)
        raw.extend(b'\0' * (-len(raw) % 4))
    string(b'_ProjectPrefs')
    raw.extend(struct.pack('<i', len(pairs)))
    for name, value in pairs:
        string(name)
        string(value)
    return bytes(raw)


class DiskPrefsTests(unittest.TestCase):
    def test_alignment_and_multiple_entries(self):
        pairs = [(b'a', b'abc'), (b'long_name', b'value')]
        self.assertEqual(parse_entries(serialized(pairs)), dict(pairs))

    def test_truncated_duplicate_and_unknown_fields(self):
        raw = serialized([(b'entry', b'value')])
        for size in range(len(raw)):
            with self.subTest(size=size), self.assertRaises(ModError):
                parse_entries(raw[:size])
        with self.assertRaises(ModError):
            parse_entries(raw + b'\0\0\0\0')
        with self.assertRaises(ModError):
            parse_entries(serialized([(b'a', b'b'), (b'a', b'c')]))

    def test_encrypted_entry_decodes_raw_parameter(self):
        from py3rijndael import RijndaelCbc, Pkcs7Padding
        def encrypt(value):
            cipher = RijndaelCbc(
                base64.b64decode('OnOFurwfBWIQHlCBf/2aHsQRvP2BGxGZcMfJf13Bcao='),
                base64.b64decode('CNMAeKOLwe84toAHQcJBapYARVF4CZnbmk7aSsjIpHI='),
                Pkcs7Padding(32), block_size=32)
            return base64.b64encode(cipher.encrypt(value))
        name = encrypt(b'sqlite3mcKey')
        # A base64-looking value must not be decoded a second time.
        self.assertEqual(decode_key({name: encrypt(b'ZGlzay10ZXN0')}), b'ZGlzay10ZXN0')
        for entries in ({}, {name: b'!'}, {name: encrypt(b'')}):
            with self.assertRaises(ModError):
                decode_key(entries)


if __name__ == '__main__':
    unittest.main()
