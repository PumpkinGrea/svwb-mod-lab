"""Read-only backup inventory and explicitly selected, guarded restores."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .core import ModError, sha


HASH = re.compile(r"[a-f0-9]{64}")


def timestamp(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def valid_time(value):
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value)
            return value
        except ValueError:
            pass
    return None


def scan_backups(manager, cards):
    """Never decode or write game resources; a bad entry cannot hide other backups."""
    by_hash = {card["asset"]["hash"]: card for card in cards}
    by_texture = {card["texture_id"]: card for card in cards}
    root = manager.data_dir / "backups"
    if not root.exists():
        return []
    if not root.resolve().is_relative_to(manager.data_dir.resolve()):
        raise ModError("备份根目录指向数据目录之外，已停止检查。")
    rows = []
    for directory in sorted(root.iterdir()):
        row = {"id": directory.name, "name": "未记录卡名", "texture_id": "",
               "state": "invalid", "status": "记录或备份异常", "reason": "",
               "restorable": False, "current_sha": None, "backup_bytes": 0,
               "created_at": None, "modified_at": None, "time_estimated": False,
               "backup_path": str(directory), "asset": None}
        rows.append(row)
        try:
            if not directory.is_dir() or directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
                raise ModError("不是正常的备份子目录，未读取其内容。")
            record_path, original_path = directory / "record.json", directory / "original.bin"
            for path in (record_path, original_path):
                if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                    raise ModError("备份文件路径异常，未读取。")
            if not record_path.is_file():
                raise ModError("缺少 record.json；可能是未完成的操作。保留备份，请勿删除。")
            if record_path.stat().st_size > 2 * 1024 * 1024:
                raise ModError("备份记录过大。")
            record = json.loads(record_path.read_text(encoding="utf-8"))
            asset = record["asset"]
            if directory.resolve() != manager.backup_dir(asset) or asset["hash"] != directory.name:
                raise ModError("备份目录与记录中的资源标识不符。")
            if type(asset.get("key")) is not int or type(asset.get("size")) is not int or not 0 < asset["size"] <= 128 * 1024 * 1024:
                raise ModError("备份资源参数无效。")
            original_sha, modified_shas = record["original_sha"], record["modded_shas"]
            if not isinstance(original_sha, str) or not HASH.fullmatch(original_sha) or not isinstance(modified_shas, list) or not all(isinstance(x, str) and HASH.fullmatch(x) for x in modified_shas):
                raise ModError("备份指纹记录无效。")
            row["asset"] = asset
            context = record.get("context")
            context = context if isinstance(context, dict) else {}
            logical_name = str(asset.get("name", ""))
            ident = str(context.get("texture_id") or logical_name.rsplit("/", 1)[-1])
            card = by_hash.get(asset["hash"])
            if not ident and card:
                ident = card["texture_id"]
            row["texture_id"] = ident
            row["name"] = str(card["name"] if card else context.get("name") or (by_texture.get(ident) or {}).get("name") or "未记录卡名")
            row["created_at"] = valid_time(record.get("created_at"))
            row["modified_at"] = valid_time(record.get("modified_at"))
            row["time_estimated"] = bool(record.get("created_at_estimated"))
            if original_path.is_file():
                row["backup_bytes"] = original_path.stat().st_size
                if not row["created_at"]:
                    row["created_at"] = timestamp(original_path)
                    row["time_estimated"] = True
            if not row["modified_at"]:
                row["modified_at"] = timestamp(record_path)
                row["time_estimated"] = True
            if not original_path.is_file() or row["backup_bytes"] != asset["size"] or sha(original_path.read_bytes()) != original_sha:
                raise ModError("首次备份缺失、大小不符或校验失败，禁止恢复。")
            target = manager.target(asset)
            if not target.is_file():
                row.update(state="missing", status="缓存缺失", reason="原缓存已不存在，可能被清理或更新；不创建旧文件。")
                continue
            if target.stat().st_size > 128 * 1024 * 1024:
                raise ModError("当前缓存超过检查大小上限。")
            current_sha = sha(target.read_bytes())
            row["current_sha"] = current_sha
            # A present old cache is not evidence that the latest game still uses it.
            if cards and (not card or any(card["asset"].get(k) != asset.get(k) for k in ("hash", "key", "size"))):
                row.update(state="outdated", status="与当前索引不匹配", reason="该资源不在当前索引中或参数已变化，可能属于旧版本。请先刷新本地索引；不写回旧备份。")
            elif current_sha == original_sha:
                row.update(state="restored", status="已恢复", reason="当前缓存与首次备份完全一致，无需再次恢复。")
            elif current_sha in modified_shas:
                reason = "首次备份校验通过，当前缓存与工具记录的修改指纹一致。恢复前仍会复检。"
                if not cards:
                    reason += " 尚无可用本地索引，仅能核对文件指纹，不能确认游戏仍使用该资源。"
                row.update(state="modified", status="已修改 · 可恢复", reason=reason, restorable=True)
            else:
                row.update(state="external", status="外部变更", reason="当前缓存不匹配首次备份或本工具的修改记录，无法区分游戏更新与其他工具修改；不覆盖。")
        except Exception as exc:
            row["reason"] = str(exc)
    return rows


def restore_entries(manager, cards, entries):
    """Restore only the requested hashes and unchanged, freshly checked inventory rows."""
    restored, errors = 0, []
    requested = {entry["id"]: entry for entry in entries}
    if not requested:
        return restored, errors
    with manager.locked():
        fresh = {row["id"]: row for row in scan_backups(manager, cards)}
        for ident, expected in requested.items():
            try:
                row = fresh.get(ident)
                if row is None or not row["restorable"]:
                    raise ModError(row["reason"] if row else "备份记录已不存在，请刷新列表。")
                if row["current_sha"] != expected.get("current_sha"):
                    raise ModError("列表检查后缓存发生变化，请刷新后重新确认。")
                restored += int(manager._restore(row["asset"], expected_sha=row["current_sha"]))
            except Exception as exc:
                errors.append(f"{ident}: {exc}")
    return restored, errors
