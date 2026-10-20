"""Offline single-card export using the verified public XOR transform."""
import argparse
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "tools/python"))
import UnityPy
import UnityPy.config

parser = argparse.ArgumentParser()
parser.add_argument("card_id")
parser.add_argument("--manifest", type=Path, default=root / "card-probe/manifest-public.json",
                    help="Normalized JSON manifest, including fetch-manifest.py output")
args = parser.parse_args()
if not args.card_id.isdigit():
    parser.error("card_id must be numeric")
manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
asset = next(a for a in manifest["assets"]
             if a["name"] == f"Assets/_Wizard2Resources/Card/Textures/{args.card_id}")
source = root / "cache-copy/dat" / asset["hash"][:2] / asset["hash"]
base = (root / "local-keys/bundle-base.bin").read_bytes()
key = (asset["key"] & ((1 << 64) - 1)).to_bytes(8, "little")
data = bytearray(source.read_bytes())
for p in range(256, len(data)):
    data[p] ^= base[(p // 8) % len(base)] ^ key[p % 8]
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"
env = UnityPy.load(bytes(data))
textures = [obj.read() for obj in env.objects if obj.type.name == "Texture2D"]
if not textures:
    raise SystemExit("No Texture2D found; nothing exported")
out = root / "independent-export" / args.card_id
out.mkdir(parents=True, exist_ok=True)
(out / f"{args.card_id}.ab").write_bytes(data)
for index, texture in enumerate(textures):
    image = texture.image
    dest = out / f"{args.card_id}-{index}.png"
    image.save(dest)
    print(f"EXPORTED {dest} {image.size}")
