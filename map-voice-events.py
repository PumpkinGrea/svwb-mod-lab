"""Map sample media IDs through Wwise Sound/Action/Event objects.

Format reference: Hypnos-PD/wbunpacker crates/audio/src/wwise.rs (MIT).
Event names are read from game data; purpose labels are suffix interpretations,
not yet cross-checked against CardResourceMaster.
"""
from collections import defaultdict
import json
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/python"))
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def u32(data, p):
    return struct.unpack_from("<I", data, p)[0]


def event_names(data):
    if len(data) < 64 or (len(data) - 48) % 16:
        raise ValueError("Unexpected mapping file size")
    decryptor = Cipher(algorithms.AES(data[:32]), modes.CBC(data[32:48])).decryptor()
    padded = decryptor.update(data[48:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    count = u32(plain, 0)
    offset, result = 4, {}
    for _ in range(count):
        event_id, length = struct.unpack_from("<II", plain, offset)
        offset += 8
        if offset + length > len(plain):
            raise ValueError("Mapping name out of bounds")
        name = plain[offset:offset + length].decode("utf-8")
        if event_id in result and result[event_id] != name:
            raise ValueError("Conflicting event IDs")
        result[event_id] = name
        offset += length
    if offset != len(plain):
        raise ValueError("Unexpected mapping trailing data")
    return result


def banks(data):
    if data[:4] != b"AKPK":
        raise ValueError("Not AKPK")
    header_size, endian, lang_size, bank_size = struct.unpack_from("<4I", data, 4)
    if endian != 1:
        raise ValueError("Unsupported byte order")
    at = 28 + lang_size
    count = u32(data, at)
    if bank_size != 4 + 20 * count or at + bank_size > header_size + 8:
        raise ValueError("Unexpected bank table")
    for i in range(count):
        bank_id, block_size, size, block_offset, lang = struct.unpack_from("<5I", data, at + 4 + 20*i)
        start = block_size * block_offset
        bank = data[start:start + size]
        if len(bank) != size or bank[:4] != b"BKHD":
            raise ValueError("Invalid bank range/header")
        yield bank


def varint(data):
    value = 0
    for i, byte in enumerate(data[:5]):
        value = (value << 7) | (byte & 127)
        if not byte & 128:
            return value, i + 1
    raise ValueError("Invalid action list length")


def collect(bank, media_sound, sound_action, action_event):
    pos = 0
    while pos + 8 <= len(bank):
        tag, size = bank[pos:pos+4], u32(bank, pos+4)
        body = bank[pos+8:pos+8+size]
        if len(body) != size:
            raise ValueError("Bank chunk out of bounds")
        pos += 8 + size
        if tag != b"HIRC":
            continue
        count, off = u32(body, 0), 4
        for _ in range(count):
            kind, obj_size = struct.unpack_from("<BI", body, off)
            start, end = off + 5, off + 5 + obj_size
            if obj_size < 4 or end > len(body):
                raise ValueError("HIRC object out of bounds")
            obj_id = u32(body, start)
            content = body[start+4:end]
            off = end
            if kind == 2 and len(content) >= 9:
                media_sound[u32(content, 5)].add(obj_id)
            elif kind == 3 and len(content) >= 6 and struct.unpack_from("<H", content)[0] == 0x0403:
                sound_action[u32(content, 2)].add(obj_id)
            elif kind == 4 and content:
                actions, skip = varint(content)
                if skip + actions * 4 > len(content):
                    raise ValueError("Event actions out of bounds")
                for i in range(actions):
                    action_event[u32(content, skip + 4*i)].add(obj_id)


def label(event, prefix):
    suffix = event.removeprefix(f"Play_dx_{prefix}_")
    if suffix.startswith(("9_", "11_")):
        return "联动语音（后缀规则推断，目标编号 " + suffix.split("_", 1)[1] + "）"
    return {"1": "登场", "2": "攻击", "2_evo": "进化后攻击", "3": "进化",
            "3_sp": "超进化", "4": "破坏/退场", "4_evo": "进化后破坏/退场",
            "5": "效果", "5_evo": "进化后效果", "10": "启动"}.get(suffix, "特殊事件，待核实")


def main():
    manifest = json.loads((ROOT / "official-manifests/722884456691/Chs/assetbundle.Chs.manifest.json").read_text(encoding="utf-8"))
    asset = next(a for a in manifest["raw_assets"] if a["name"] == "sound/WwiseIdMapping.bytes")
    source = ROOT / "cache-copy/dat" / asset["hash"][:2] / asset["hash"]
    names = event_names(source.read_bytes())
    report = {"mapping_resource": asset["name"], "mapping_hash": asset["hash"],
              "global_event_count": len(names), "label_basis": "event suffix convention, not CardResourceMaster", "packs": {}}
    media_sound, sound_action, action_event = (defaultdict(set) for _ in range(3))
    prefixes = ("10974110", "10964110", "10954110")
    for prefix in prefixes:
        pck = ROOT / f"audio-export/dx_{prefix}-jp/dx_{prefix}.pck"
        for bank in banks(pck.read_bytes()):
            collect(bank, media_sound, sound_action, action_event)
    for prefix in prefixes:
        folder = ROOT / f"audio-export/dx_{prefix}-jp"
        clips = json.loads((folder / "report.json").read_text(encoding="utf-8"))["audio"]
        mapped = []
        for clip in clips:
            media_id = clip["media_id"]
            events = {}
            for sound in media_sound[media_id]:
                for action in sound_action[sound]:
                    for event in action_event[action]:
                        if event in names:
                            events[event] = names[event]
            item = {"media_id": media_id, "events": [{"event_id": event, "name": name,
                    "purpose_by_suffix": label(name, prefix)} for event, name in sorted(events.items())]}
            # Preserve the original ID-based files; add event-named copies for listening.
            for event_name in set(events.values()):
                if not event_name.startswith("Play_dx_") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in event_name):
                    continue
                dest = folder / "by-event"
                dest.mkdir(exist_ok=True)
                shutil.copyfile(folder / clip["wav_file"], dest / f"{event_name}--{media_id}.wav")
            mapped.append(item)
        report["packs"][prefix] = {"media_count": len(mapped), "mapped_count": sum(bool(a["events"]) for a in mapped), "clips": mapped}
        (folder / "event-map.json").write_text(json.dumps(report["packs"][prefix], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{prefix}: {report['packs'][prefix]['mapped_count']}/{len(mapped)} mapped")
        for clip in mapped:
            print(clip["media_id"], ", ".join(e["name"] for e in clip["events"]))
    (ROOT / "audio-export/event-map.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Global event names: {len(names)}")


if __name__ == "__main__":
    main()
