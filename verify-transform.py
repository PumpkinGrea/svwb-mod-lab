"""Compare a local encrypted/plain pair against the public wbu XOR formula."""
from pathlib import Path
import json

root = Path(__file__).resolve().parent
probe = root / "card-probe"
manifest = json.loads((probe / "manifest-public.json").read_text(encoding="utf-8-sig"))
asset = next(a for a in manifest["assets"] if a["hash"] == "T3CNCIECZBPCG2DVHKAEVI566I")
enc = (probe / "source" / asset["hash"]).read_bytes()
plain = (probe / "decrypt/Assets__Wizard2Resources_Card_Textures_100011300").read_bytes()
assert len(enc) == len(plain)
assert enc[:256] == plain[:256], "Header differs"
key = (asset["key"] & ((1 << 64) - 1)).to_bytes(8, "little")
base = {}
for p in range(256, len(enc)):
    value = enc[p] ^ plain[p] ^ key[p % 8]
    slot = p // 8
    assert slot not in base or base[slot] == value, f"Formula mismatch at {p}"
    base[slot] = value
period = next((n for n in range(1, 8193)
               if all(v == base.get(i + n, v) for i, v in base.items())), None)
assert period is not None, "No repeating base key found"
recovered = bytearray(period)
for i, value in base.items():
    recovered[i % period] = value
out = bytearray(enc)
for p in range(256, len(out)):
    out[p] ^= recovered[(p // 8) % period] ^ key[p % 8]
assert out == plain, "Independent decryption mismatch"
print(f"Public XOR formula matches all {len(enc)} bytes; base-key period: {period} bytes")
secrets = root / "local-keys"
secrets.mkdir(exist_ok=True)
(secrets / "bundle-base.bin").write_bytes(recovered)
print("Recovered parameters saved locally; not printed")
