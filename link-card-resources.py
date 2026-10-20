"""Join the three audio samples to official card names and resource records.

Column positions below are verified against this downloaded resource version;
do not assume they remain unchanged across future versions.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TABLES = ROOT / "master-data/tables"
def load(name):
    return json.loads((TABLES / f"{name}.json").read_text(encoding="utf-8"))

cards = {r[0]: r for r in load("CardMaster")}
resources = {r[0]: r for r in load("CardResourceMaster")}
texts = {r[0]: r for r in load("CardText")}
labels = dict(load("MasterTextLabel"))
manifest = json.loads((ROOT / "official-manifests/722884456691/Chs/assetbundle.Chs.manifest.json").read_text(encoding="utf-8"))
bundles = {r["name"]: r for r in manifest["assets"]}
raws = {r["name"]: r for r in manifest["raw_assets"]}
event_map = json.loads((ROOT / "audio-export/event-map.json").read_text(encoding="utf-8"))
entries = []
for card_id in (10974110, 10964110, 10954110):
    card = cards[card_id]
    resource = resources[card[2]]
    text = texts[card[4]]
    prefix = resource[38]
    image_name = f"Assets/_Wizard2Resources/Card/Textures/{resource[1]}"
    image = bundles[image_name]
    audio_name = f"sound/Windows/d/Japanese(JP)/{prefix}.pck"
    audio = raws[audio_name]
    declared = []
    for col, slot in ((39, "play"), (41, "attack"), (42, "evo_attack"), (43, "evolve"),
                      (45, "destroy"), (46, "evo_destroy"), (47, "destroy_token"),
                      (48, "skill"), (49, "evo_skill"), (50, "act")):
        declared.extend({"column": col, "slot_group": slot, "name": e.strip()} for e in resource[col].split(",") if e.strip())
    media = event_map["packs"][prefix.removeprefix("dx_")]["clips"]
    found = {event["name"]: [] for event in declared}
    for clip in media:
        for event in clip["events"]:
            if event["name"] in found:
                found[event["name"]].append({"media_id": clip["media_id"], "event_id": event["event_id"],
                    "wav": f"audio-export/{prefix}-jp/{clip['media_id']}.wav"})
    for event in declared:
        event["media"] = found[event["name"]]
    def location(asset):
        path = ROOT / "cache-copy/dat" / asset["hash"][:2] / asset["hash"]
        return {"name": asset["name"], "hash": asset["hash"], "cached": path.is_file()}
    entry = {"card_id": card[0], "base_card_id": card[1], "name_chs": labels[text[1]],
             "name_text_key": text[1], "resource_record_id": resource[0],
             "image_resource": location(image), "voice_resource": location(audio),
             "events": declared, "declared_events": len(declared),
             "matched_events": sum(bool(e["media"]) for e in declared)}
    entries.append(entry)
    print(f"{card_id} {entry['name_chs']} image={resource[1]} voice={prefix} events={entry['matched_events']}/{len(declared)}")
output = {"version": "722884456691", "join": {"CardMaster[2]": "CardResourceMaster[0]",
          "CardMaster[4]": "CardText[0]", "CardText[1]": "MasterTextLabel[0]",
          "CardResourceMaster[1]": "observed card texture resource path ID",
          "CardResourceMaster[38]": "voice prefix"}, "cards": entries}
(ROOT / "master-data/card-resource-links.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
