"""Transactional OFFLINE index refreshes from the installed game's resource DB."""
from contextlib import contextmanager
import json
from pathlib import Path
import re

from .catalog import build_catalog, empty_catalog, validate_catalog
from .core import atomic_write, write_json, sha
from .formats import parse_master
from .localmeta import LocalReader


class IndexStore:
    def __init__(self, game_dir):
        self.game_dir = Path(game_dir).resolve()
        self.root = self.game_dir / "SVWBModData/index"

    @contextmanager
    def locked(self):
        import msvcrt
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "update.lock").open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("另一窗口正在更新索引，请稍后再试。") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def read_object(self, filename):
        pointer = json.loads((self.root / filename).read_text(encoding="utf-8"))
        ident = pointer["object"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{64}", ident):
            raise ValueError("索引快照标识无效")
        raw = (self.root / "objects" / f"{ident}.json").read_bytes()
        if sha(raw) != ident:
            raise ValueError("索引快照校验失败")
        index = validate_catalog(json.loads(raw.decode("utf-8")))
        if index.get("schema") != 2 or index.get("source") != "local":
            raise ValueError("旧在线索引不再用于检索，请刷新本地索引")
        return index

    def load(self):
        errors = []
        for filename in ("active.json", "previous.json"):
            if not (self.root / filename).exists():
                continue
            try:
                return self.read_object(filename), "；".join(errors)
            except Exception as exc:
                errors.append(f"{filename} 无法读取：{exc}")
        return empty_catalog(), "；".join(errors)

    def has_previous(self):
        try:
            self.read_object("previous.json")
            return True
        except Exception:
            return False

    def save_object(self, index):
        validate_catalog(index)
        raw = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ident = sha(raw)
        directory = self.root / "objects"
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write(directory / f"{ident}.json", raw)
        return {"object": ident, "version": index["version"]}

    def publish(self, index, previous):
        # Immutable content-addressed files first; the active pointer is the final commit.
        new_pointer = self.save_object(index)
        old_pointer = self.save_object(previous) if previous["cards"] else None
        if new_pointer == old_pointer:
            return
        if old_pointer:
            write_json(self.root / "previous.json", old_pointer)
        write_json(self.root / "active.json", new_pointer)

    def rollback(self, current):
        with self.locked():
            previous = self.read_object("previous.json")
            self.publish(previous, current)
            return previous

    def update(self, current, force=False):
        with self.locked():
            manifest = LocalReader(self.game_dir).read()
            master = manifest["master"]
            path = self.game_dir / "ShadowverseWB_Data/Persistent/dat" / master["hash"][:2] / master["hash"]
            if not path.is_file():
                raise ValueError("本地主数据未缓存，请先进入游戏完成资源下载。")
            raw_master = path.read_bytes()
            if len(raw_master) != master["size"]:
                raise ValueError("本地主数据大小不匹配，可能尚未下载完成；旧索引未改变。")
            identity = {"manifest": manifest, "master_sha256": sha(raw_master)}
            version = "local:" + sha(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
            if version == current["version"] and not force:
                return {"updated": False, "index": current,
                        "message": "本地清单与主数据未变化，继续使用当前索引；全程未联网。"}
            tables = parse_master(raw_master)
            index = build_catalog(tables, manifest, version, current)
            index["local"] = {"roots": manifest["roots"], "master_sha256": sha(raw_master)}
            # Re-read the DB state to reject a mixed snapshot if the game updated meanwhile.
            if LocalReader(self.game_dir).read() != manifest:
                raise ValueError("游戏清单在读取过程中改变，请等待游戏下载完成后重试。")
            if sha(path.read_bytes()) != sha(raw_master):
                raise ValueError("主数据在读取过程中改变，旧索引未改变。")
            self.publish(index, current)
            return {"updated": True, "index": index,
                    "message": f"已从本地清单和主数据生成 {len(index['cards'])} 条卡图索引；未联网、未修改游戏资源。"}
