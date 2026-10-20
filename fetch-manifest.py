"""Download official Windows manifests and decode their MasterMemory tables.

Format reference: Hypnos-PD/wbunpacker, crates/manifest/src/lib.rs (MIT).
No login, client modification, or bundle base key is required.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/python"))
import lz4.block
import msgpack

FIELDS = {
    "asset": ("assets", ("name", "hash", "asset_id", "all_dependencies", "key", "size", "category", "group", "checksum")),
    "raw_asset": ("raw_assets", ("name", "hash", "size", "category", "group")),
    "assetname": ("load_names", ("asset_name", "name")),
    "config": ("config", ("key", "value")),
}
MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_TABLE = 128 * 1024 * 1024


def read_value(stream):
    start = stream.tell()
    unpacker = msgpack.Unpacker(raw=False, strict_map_key=False, max_buffer_size=MAX_TABLE)
    unpacker.feed(stream.read())
    value = unpacker.unpack()
    stream.seek(start + unpacker.tell())
    return value


def parse_manifest(raw):
    if len(raw) < 17:
        raise ValueError("Manifest too short")
    body, trailer = raw[:-16], raw[-16:]
    md5_matches = hashlib.md5(body).digest() == trailer
    if not md5_matches:
        raise ValueError("Manifest MD5 mismatch; previous outputs left intact")
    stream = io.BytesIO(body)
    toc = read_value(stream)
    toc_end = stream.tell()
    if not isinstance(toc, dict) or not all(table in toc for table in FIELDS):
        raise ValueError("Unexpected manifest table directory")
    result = {}
    diagnostics = {}
    for table, (output_name, fields) in FIELDS.items():
        offset, length = toc[table]
        if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length <= 0:
            raise ValueError(f"Invalid {table} table range")
        start = toc_end + offset
        if start + length > len(body):
            raise ValueError(f"{table} table out of bounds")
        value = msgpack.unpackb(body[start:start + length], raw=False, strict_map_key=False)
        compressed = isinstance(value, msgpack.ExtType)
        if compressed:
            if value.code != 99:
                raise ValueError(f"Unsupported extension {value.code}")
            packed = io.BytesIO(value.data)
            size = read_value(packed)
            if not isinstance(size, int) or not 0 < size <= MAX_TABLE:
                raise ValueError(f"Invalid {table} decompressed size {size!r}")
            decoded = lz4.block.decompress(packed.read(), uncompressed_size=size)
            if len(decoded) != size:
                raise ValueError("LZ4 size mismatch")
            value = msgpack.unpackb(decoded, raw=False, strict_map_key=False)
        if not isinstance(value, list):
            raise ValueError(f"{table} is not a list")
        rows = []
        for row in value:
            row_fields = fields
            # Official raw_asset rows include a sixth integer omitted by the
            # reference parser. Preserve it without guessing its semantics.
            if table == "raw_asset" and isinstance(row, list) and len(row) == 6:
                row_fields = fields + ("extra_5",)
            if not isinstance(row, list) or len(row) != len(row_fields):
                raise ValueError(f"Unexpected {table} row schema: {row!r}; inspect version before proceeding")
            rows.append(dict(zip(row_fields, row)))
        result[output_name] = rows
        diagnostics[table] = {"offset": offset, "bytes": length, "lz4": compressed, "rows": len(rows)}
    return result, {"trailer_hex": trailer.hex(), "body_md5": hashlib.md5(body).hexdigest(),
                    "body_md5_matches_trailer": md5_matches, "toc_bytes": toc_end, "tables": diagnostics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Resource version, not app version")
    parser.add_argument("--variant", choices=("Chs", "Cht", "Eng", "Jpn", "Kor"), default="Chs")
    parser.add_argument("--input", type=Path, help="Parse an already downloaded file offline")
    parser.add_argument("--compare", type=Path, help="Compare with a prior normalized JSON manifest")
    args = parser.parse_args()
    if not args.version.isdigit():
        parser.error("version must be numeric")
    filename = "assetbundle" + ("" if args.variant == "Jpn" else f".{args.variant}") + ".manifest"
    url = f"https://shadowverse-wb.akamaized.net/dl/manifests/Windows/{args.version}/{filename}"
    headers = {}
    if args.input:
        raw = args.input.read_bytes()
    else:
        with urlopen(Request(url, headers={"User-Agent": "SVWB-Mod-Lab/1.0"}), timeout=30) as response:
            raw = response.read(MAX_DOWNLOAD + 1)
            headers = {key: response.headers.get(key) for key in ("Last-Modified", "ETag", "Content-Type")}
    if len(raw) > MAX_DOWNLOAD:
        raise ValueError("Download exceeds limit")
    manifest, report = parse_manifest(raw)
    report.update({"url": url, "version": args.version, "variant": args.variant,
                   "read_at_utc": datetime.now(timezone.utc).isoformat(),
                   "mode": "offline" if args.input else "official_download",
                   "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "http_headers": headers})
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8-sig"))
        comparison = {}
        for section in ("assets", "raw_assets", "config", "load_names"):
            if section in ("assets", "raw_assets"):
                old = {a["name"]: a for a in previous[section]}
                new = {a["name"]: a for a in manifest[section]}
                comparison[section] = {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
                    "changed_common_fields": sum(any(new[name].get(k) != v for k, v in old[name].items())
                        for name in old.keys() & new.keys()),
                    "extra_fields_in_new": sorted({k for name in old.keys() & new.keys()
                                                   for k in new[name].keys() - old[name].keys()})}
            else:
                comparison[section] = {"equal": previous[section] == manifest[section]}
        report["comparison"] = comparison
    out = ROOT / "official-manifests" / args.version / args.variant
    out.mkdir(parents=True, exist_ok=True)
    # Publish only after full parsing succeeds; never replace the previous GitHub manifest.
    (out / filename).write_bytes(raw)
    (out / f"{filename}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"JSON: {out / (filename + '.json')}")


if __name__ == "__main__":
    main()
