"""Adapt a public manifest's field names for the legacy bundle tool."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent / "card-probe"
source = root / "assetbundle.Chs.manifest.json"
original = root / "manifest-public.json"
if not original.exists():
    original.write_bytes(source.read_bytes())
manifest = json.loads(original.read_text(encoding="utf-8-sig"))
asset = next(a for a in manifest["assets"] if a["hash"] == "T3CNCIECZBPCG2DVHKAEVI566I")
names = {"name": "Name", "hash": "Hash", "asset_id": "AssetId",
         "all_dependencies": "AllDependencies", "key": "Key", "size": "Size",
         "category": "Category", "group": "Group", "checksum": "CheckSum"}
converted = {"ManifestAsset": [{names[k]: v for k, v in asset.items() if k in names}],
             "ManifestRawAsset": [], "AssetBundleLoadName": [], "ManifestConfig": []}
source.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(converted, ensure_ascii=False, indent=2))
