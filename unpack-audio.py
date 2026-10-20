"""Extract indexed Wwise media from local Japanese card PCK samples."""
import argparse
import json
import struct
import subprocess
import wave
from pathlib import Path

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("card_id", nargs="?", default="10001110", help="Numeric dx pack ID, not a verified official card ID")
parser.add_argument("--manifest", type=Path, default=root / "official-manifests/722884456691/Chs/assetbundle.Chs.manifest.json")
args = parser.parse_args()
if not args.card_id.isdigit():
    parser.error("card_id must be numeric")
manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
name = f"sound/Windows/d/Japanese(JP)/dx_{args.card_id}.pck"
asset = next(a for a in manifest["raw_assets"] if a["name"] == name)
source = root / "cache-copy/dat" / asset["hash"][:2] / asset["hash"]
data = source.read_bytes()
assert data[:4] == b"AKPK"
header_size, endian, lang_size, bank_size, media_size, external_size = struct.unpack_from("<6I", data, 4)
assert endian == 1, "Only this sample's little-endian format is supported"
offset = 28 + lang_size + bank_size
assert offset + media_size <= header_size + 8 <= len(data)
count = struct.unpack_from("<I", data, offset)[0]
assert media_size == 4 + count * 20
out = root / f"audio-export/dx_{args.card_id}-jp"
out.mkdir(parents=True, exist_ok=True)
(out / f"dx_{args.card_id}.pck").write_bytes(data)
records = []
for i in range(count):
    media_id, block_size, size, block_offset, language_id = struct.unpack_from("<5I", data, offset + 4 + 20*i)
    assert block_size > 0 and block_size * block_offset + size <= len(data)
    start = block_size * block_offset
    media = data[start:start + size]
    assert len(media) == size and media[:4] == b"RIFF" and media[8:12] == b"WAVE"
    assert struct.unpack_from("<I", media, 4)[0] + 8 == size
    wem = out / f"{media_id}.wem"
    wav = out / f"{media_id}.wav"
    wem.write_bytes(media)
    result = subprocess.run([str(root / "tools/vgmstream/vgmstream-cli.exe"), "-o", str(wav), str(wem)],
                            capture_output=True, text=True, errors="replace", timeout=30)
    (out / f"{media_id}.decode.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    result.check_returncode()
    with wave.open(str(wav), "rb") as audio:
        info = {"media_id": media_id, "channels": audio.getnchannels(),
                "sample_rate": audio.getframerate(), "frames": audio.getnframes(),
                "sample_width_bytes": audio.getsampwidth(), "wav_bytes": wav.stat().st_size,
                "wem_bytes": size, "wem_file": wem.name, "wav_file": wav.name,
                "seconds": round(audio.getnframes() / audio.getframerate(), 3)}
    records.append(info)
    print(info)
(out / "report.json").write_text(json.dumps({"resource": name, "hash": asset["hash"],
    "bank_index_bytes": bank_size, "media_count": count, "audio": records}, indent=2), encoding="utf-8")
print(f"EXPORTED {len(records)} WAV files")
