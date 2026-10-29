"""Join locally installed master tables and resource records into a search index."""
import re


def validate_catalog(index):
    if not isinstance(index, dict):
        raise ValueError("索引资源版本无效")
    local = index.get("schema") == 2 and index.get("source") == "local"
    version = str(index.get("version", ""))
    if local:
        if version != "uninitialized" and not re.fullmatch(r"local:[a-f0-9]{64}", version):
            raise ValueError("本地清单指纹无效")
    elif index.get("schema") != 1 or not re.fullmatch(r"[0-9]{1,20}", version):
        raise ValueError("旧索引版本无效")
    cards = index.get("cards")
    if not isinstance(cards, list) or len(cards) > 100000 or (not cards and not (local and version == "uninitialized")):
        raise ValueError("索引卡图列表无效")
    if version == "uninitialized" and cards:
        raise ValueError("未初始化的索引不能包含卡图")
    seen = set()
    for card in cards:
        ident = card["texture_id"]
        if not isinstance(ident, str) or not re.fullmatch(r"(?:[0-9]+(?:_(?:front|back))?|empty)", ident) or ident in seen:
            raise ValueError("索引纹理编号无效或重复")
        seen.add(ident)
        if not isinstance(card["name"], str) or not isinstance(card["relation"], str):
            raise ValueError("索引卡名/关联类型无效")
        if not isinstance(card["card_ids"], list) or not all(type(value) is int for value in card["card_ids"]):
            raise ValueError("索引卡牌编号无效")
        asset = card["asset"]
        if not re.fullmatch(r"[A-Z0-9]{8,80}", asset["hash"]):
            raise ValueError("索引文件标识无效")
        if type(asset["key"]) is not int or not -(1 << 63) <= asset["key"] < (1 << 64):
            raise ValueError("索引资源参数无效")
        if type(asset["size"]) is not int or not 0 < asset["size"] <= 128 * 1024 * 1024:
            raise ValueError("索引资源大小无效")
        fingerprint = asset.get("original_sha256")
        if fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("索引原始指纹无效")
    return index


def empty_catalog():
    return {"schema": 2, "source": "local", "version": "uninitialized", "cards": []}


def build_catalog(tables, manifest, version, previous=None):
    cards = tables["CardMaster"]
    def keyed(name, minimum):
        result = {}
        for row in tables[name]:
            if not isinstance(row, list) or len(row) < minimum:
                raise ValueError(f"{name} 字段结构发生变化，未更新索引")
            result[row[0]] = row
        return result
    resources, texts = keyed("CardResourceMaster", 3), keyed("CardText", 2)
    labels = {row[0]: row[1] for row in keyed("MasterTextLabel", 2).values()}
    assets = {}
    for entry in manifest["assets"]:
        if entry["name"].startswith("Assets/_Wizard2Resources/Card/Textures/"):
            ident = entry["name"].rsplit("/", 1)[-1]
            if ident in assets:
                raise ValueError("资源清单包含重复的纹理编号，需更新工具处理规则")
            assets[ident] = dict(entry)
    links = {}
    for card in cards:
        if not isinstance(card, list) or len(card) < 6 or type(card[0]) is not int:
            raise ValueError("CardMaster 字段结构发生变化，未更新索引")
        resource, text = resources.get(card[2]), texts.get(card[4])
        if not resource or not text or text[1] not in labels:
            continue
        ident = str(resource[1])
        if ident in assets:
            links.setdefault(ident, []).append({"id": card[0], "name": labels[text[1]]})
    if not links:
        raise ValueError("无法关联中文名与卡图，可能主数据字段已变更，旧索引已保留")
    previous_fingerprints = {}
    if previous:
        validate_catalog(previous)
        for row in previous["cards"]:
            asset = row["asset"]
            previous_fingerprints[(asset["hash"], asset["key"], asset["size"])] = asset.get("original_sha256")
    families = {}
    for ident in links:
        families.setdefault(ident[:-1], []).append(ident)
    rows = []
    for ident, asset in assets.items():
        mapped, relation = links.get(ident, []), "主数据直接关联"
        if not mapped:
            candidates = families.get(ident[:-1], [])
            if len(candidates) == 1:
                mapped, relation = links[candidates[0]], "同组纹理候选（请核对预览）"
        names = list(dict.fromkeys(item["name"] for item in mapped))
        asset["original_sha256"] = previous_fingerprints.get((asset["hash"], asset["key"], asset["size"]))
        rows.append({"texture_id": ident, "name": " / ".join(names) or f"未关联纹理 {ident}",
                     "card_ids": list(dict.fromkeys(item["id"] for item in mapped)), "relation": relation, "asset": asset})
    result = {"schema": 2 if str(version).startswith("local:") else 1, "version": str(version), "cards": rows}
    if result["schema"] == 2:
        result["source"] = "local"
    return validate_catalog(result)
