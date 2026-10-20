"""Decode official master tables and inspect card-to-resource linkage."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fetch_manifest", ROOT / "fetch-manifest.py")
fmt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fmt)
raw = (ROOT / "master-data/mastermemory.bytes").read_bytes()
stream = io.BytesIO(raw)
toc = fmt.read_value(stream)
toc_end = stream.tell()
out = ROOT / "master-data/tables"
out.mkdir(exist_ok=True)
tables = {}
for name in ("CardMaster", "CardResourceMaster", "CardText", "MasterTextLabel"):
    offset, length = toc[name]
    start = toc_end + offset
    if start < toc_end or start + length > len(raw):
        raise ValueError("Table outside file")
    value = fmt.read_value(io.BytesIO(raw[start:start + length]))
    if isinstance(value, fmt.msgpack.ExtType):
        if value.code != 99:
            raise ValueError("Unknown compression")
        packed = io.BytesIO(value.data)
        size = fmt.read_value(packed)
        if not 0 < size < fmt.MAX_TABLE:
            raise ValueError("Table too large")
        decoded = fmt.lz4.block.decompress(packed.read(), uncompressed_size=size)
        value = fmt.msgpack.unpackb(decoded, raw=False, strict_map_key=False)
    if not isinstance(value, list):
        raise ValueError("Not a row list")
    tables[name] = value
    (out / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{name}: {len(value)} rows")
report = {"sha256": hashlib.sha256(raw).hexdigest(), "table_count": len(toc),
          "trailer_matches_md5": hashlib.md5(raw[:-16]).digest() == raw[-16:]}
(ROOT / "master-data/report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
for prefix in ("10974110", "10964110", "10954110"):
    resources = [r for r in tables["CardResourceMaster"] if f"dx_{prefix}" in r]
    for resource in resources:
        print("RESOURCE", prefix, json.dumps(dict(enumerate(resource)), ensure_ascii=False))
        cards = [r for r in tables["CardMaster"] if len(r) > 4 and r[2] == resource[0]]
        for card in cards:
            text = next((r for r in tables["CardText"] if r[0] == card[4]), None)
            name = next((r[1] for r in tables["MasterTextLabel"] if text and r[0] == text[1]), None)
            print("CARD", json.dumps(card, ensure_ascii=False), "NAME", name, "TEXT", text)
