"""Validate a non-texture bundle and a raw font, using cache copies only."""
from collections import Counter
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "tools/python"))
import UnityPy
import UnityPy.config
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"
manifest = json.loads((root / "card-probe/manifest-public.json").read_text(encoding="utf-8-sig"))
def source(a):
    return root / "cache-copy/dat" / a["hash"][:2] / a["hash"]

out = root / "other-export"
out.mkdir(exist_ok=True)
asset = next(a for a in manifest["assets"] if a["name"].startswith("Prefabs/")
             and a["size"] < 20000 and source(a).is_file())
base = (root / "local-keys/bundle-base.bin").read_bytes()
key = (asset["key"] & ((1 << 64) - 1)).to_bytes(8, "little")
data = bytearray(source(asset).read_bytes())
for p in range(256, len(data)):
    data[p] ^= base[(p // 8) % len(base)] ^ key[p % 8]
env = UnityPy.load(bytes(data))
types = Counter(obj.type.name for obj in env.objects)
assert len(env.objects) > 0
(out / "prefab-sample.ab").write_bytes(data)
report = {"prefab": {"resource": asset["name"], "hash": asset["hash"], "objects": dict(types)}}
font = next(a for a in manifest["raw_assets"] if a["name"].lower().endswith(".otf") and source(a).is_file())
font_data = source(font).read_bytes()
assert font_data[:4] == b"OTTO"
(out / "font-sample.otf").write_bytes(font_data)
report["font"] = {"resource": font["name"], "hash": font["hash"], "magic": "OTTO", "bytes": len(font_data)}
report["manifest_cache_matches"] = {section: {"records": len(manifest[section]),
    "cached": sum(source(a).is_file() for a in manifest[section])} for section in ("assets", "raw_assets")}
(out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
