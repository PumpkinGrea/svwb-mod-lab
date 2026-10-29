"""Bounded local MasterMemory decoding; reference: Hypnos-PD/wbunpacker (MIT)."""
import io
import lz4.block
import msgpack

MAX_TABLE = 128 * 1024 * 1024


def read_value(stream):
    start = stream.tell()
    unpacker = msgpack.Unpacker(raw=False, strict_map_key=False, max_buffer_size=MAX_TABLE)
    unpacker.feed(stream.read())
    value = unpacker.unpack()
    stream.seek(start + unpacker.tell())
    return value


def decode_table(data):
    value = msgpack.unpackb(data, raw=False, strict_map_key=False)
    compressed = isinstance(value, msgpack.ExtType)
    if compressed:
        if value.code != 99:
            raise ValueError(f"Unsupported extension {value.code}")
        packed = io.BytesIO(value.data)
        size = read_value(packed)
        if type(size) is not int or not 0 < size <= MAX_TABLE:
            raise ValueError("Invalid decompressed table size")
        decoded = lz4.block.decompress(packed.read(), uncompressed_size=size)
        if len(decoded) != size:
            raise ValueError("LZ4 size mismatch")
        value = msgpack.unpackb(decoded, raw=False, strict_map_key=False)
    if not isinstance(value, list):
        raise ValueError("Table is not a row list")
    return value, compressed


def table_ranges(raw):
    stream = io.BytesIO(raw)
    toc = read_value(stream)
    if not isinstance(toc, dict):
        raise ValueError("Invalid table directory")
    end = stream.tell()
    ranges = {}
    for name, value in toc.items():
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("Invalid table range")
        offset, size = value
        if type(offset) is not int or type(size) is not int or offset < 0 or size <= 0:
            raise ValueError("Invalid table range")
        start = end + offset
        if start + size > len(raw):
            raise ValueError("Table outside file")
        ranges[name] = (offset, start, size)
    return ranges, end


def parse_master(raw):
    # Unlike manifests, mastermemory.bytes has no verified MD5-footer convention.
    ranges, _ = table_ranges(raw)
    tables = {}
    for name in ("CardMaster", "CardResourceMaster", "CardText", "MasterTextLabel"):
        if name not in ranges:
            raise ValueError(f"Missing master table: {name}")
        _, start, length = ranges[name]
        tables[name] = decode_table(raw[start:start + length])[0]
    return tables
