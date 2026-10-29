"""Texture-only edits, immutable backups and guarded cache replacement."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps
import UnityPy
import UnityPy.config
from UnityPy.export.Texture2DConverter import image_to_texture2d
from UnityPy.streams import EndianBinaryReader

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"
MASK = (1 << 64) - 1


class ModError(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(data, key, base):
    if not base:
        raise ModError("缺少解密基础参数。请使用完整的本地程序包。")
    key_bytes = (key & MASK).to_bytes(8, "little")
    result = bytearray(data)
    for offset in range(256, len(result)):
        result[offset] ^= base[(offset // 8) % len(base)] ^ key_bytes[offset % 8]
    return bytes(result)


def atomic_write(path, data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="svwbmod-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def require_game_closed():
    if sys.platform != "win32":
        raise ModError("当前应用替换与恢复仅支持 Windows。")
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq ShadowverseWB.exe", "/FO", "CSV", "/NH"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )
    if result.returncode:
        raise ModError("无法检查游戏进程，为安全起见未修改文件。")
    if b'"shadowversewb.exe"' in result.stdout.lower():
        raise ModError("请先完全关闭 ShadowverseWB，再应用替换或恢复。")


def fit_image(image, size, mode="cover", zoom=1.0, center=(0.5, 0.5)):
    image = ImageOps.exif_transpose(image).convert("RGBA")
    if mode == "stretch":
        return image.resize(size, Image.Resampling.LANCZOS)
    if mode == "contain":
        fitted = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
        result = Image.new("RGBA", size, (0, 0, 0, 255))
        result.alpha_composite(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
        return result
    factor = max(size[0] / image.width, size[1] / image.height) * max(1.0, zoom)
    crop_w, crop_h = size[0] / factor, size[1] / factor
    left = max(0.0, min(1.0, center[0])) * (image.width - crop_w)
    top = max(0.0, min(1.0, center[1])) * (image.height - crop_h)
    return image.resize(size, Image.Resampling.LANCZOS, box=(left, top, left + crop_w, top + crop_h))


class TextureDocument:
    def __init__(self, encrypted, asset, base):
        self.asset = asset
        self.base = base
        self.encrypted = encrypted
        self.plain = transform(encrypted, asset["key"], base)
        self.env = UnityPy.load(self.plain)
        if len(self.env.files) != 1:
            raise ModError("尚不支持该资源的多容器结构，未修改任何文件。")
        self.bundle = next(iter(self.env.files.values()))
        if getattr(self.bundle, "signature", None) != "UnityFS":
            raise ModError("不是受支持的 UnityFS 资源包。")
        textures = [obj.read() for obj in self.env.objects if obj.type.name == "Texture2D"]
        if len(textures) != 1:
            raise ModError("该资源含有多张纹理或没有纹理，当前版本不支持替换。")
        self.texture = textures[0]
        self.original_objects = {obj.path_id: obj.get_raw_data() for obj in self.env.objects}

    def image(self):
        return self.texture.image.convert("RGBA")

    def validate_original(self):
        if not self.asset.get("original_sha256"):
            raise ModError("该资源没有已核对的原始指纹，当前版本仅允许预览，不允许替换。")
        if len(self.encrypted) != self.asset["size"] or sha(self.encrypted) != self.asset["original_sha256"]:
            raise ModError("缓存不匹配保存的原件指纹，可能已被其他 Mod 修改或游戏已更新。未覆盖文件。")

    def rebuild(self, image):
        texture = self.texture
        stream = texture.m_StreamData
        if texture.image_data or not stream or not stream.path or not stream.size:
            raise ModError("当前版本只支持独立外部纹理流；此卡图结构尚未验证。")
        if image.size != (texture.m_Width, texture.m_Height):
            raise ModError("替换图片尺寸与原始纹理不一致。")
        if texture.m_TextureFormat not in (10, 12, 25):
            raise ModError(f"当前仅验证了 BC/DXT 纹理编码，此格式暂不支持：{texture.m_TextureFormat}")
        encoded_mips = []
        for level in range(texture.m_MipCount or 1):
            size = (max(1, image.width >> level), max(1, image.height >> level))
            mip = image if level == 0 else image.resize(size, Image.Resampling.LANCZOS)
            encoded, actual_format = image_to_texture2d(mip, texture.m_TextureFormat,
                                                       texture.object_reader.platform, texture.m_PlatformBlob)
            if int(actual_format) != texture.m_TextureFormat:
                raise ModError("纹理编码格式发生变化，已停止。")
            encoded_mips.append(encoded)
        encoded = b"".join(encoded_mips)
        if len(encoded) != stream.size:
            raise ModError("重编码后的纹理大小不匹配，已停止。")
        stream_name = stream.path.rsplit("/", 1)[-1]
        if stream_name not in self.bundle.files:
            raise ModError("纹理依赖其他资源包，当前版本不支持。")
        original_stream = self.bundle.files[stream_name]
        stream_bytes = original_stream.bytes
        if stream.offset < 0 or stream.offset + stream.size > len(stream_bytes):
            raise ModError("纹理流范围异常。")
        changed = stream_bytes[:stream.offset] + encoded + stream_bytes[stream.offset + stream.size:]
        reader = EndianBinaryReader(changed)
        reader.flags = original_stream.flags
        self.bundle.files[stream_name] = reader
        try:
            rebuilt = self.bundle.save(packer="original")
        finally:
            self.bundle.files[stream_name] = original_stream
        encrypted = transform(rebuilt, self.asset["key"], self.base)
        checked = TextureDocument(encrypted, self.asset, self.base)
        if set(checked.bundle.files) != set(self.bundle.files) or checked.original_objects != self.original_objects:
            raise ModError("重打包改变了对象结构，校验失败。")
        for name, file in self.bundle.files.items():
            if name == stream_name:
                if checked.bundle.files[name].bytes != changed:
                    raise ModError("纹理数据回读失败。")
            elif name.endswith(".resS") and checked.bundle.files[name].bytes != file.bytes:
                raise ModError("其他纹理流意外发生变化。")
        preview = checked.image()
        if preview.size != image.size:
            raise ModError("回读图片尺寸错误。")
        return encrypted, preview


class ModManager:
    def __init__(self, game_dir, base):
        self.game_dir = Path(game_dir).resolve()
        self.cache = self.game_dir / "ShadowverseWB_Data/Persistent/dat"
        if not (self.game_dir / "ShadowverseWB.exe").is_file() or not self.cache.is_dir():
            raise ModError("请选择含 ShadowverseWB.exe 和资源缓存的游戏安装目录。")
        self.base = base
        self.data_dir = self.game_dir / "SVWBModData"

    def target(self, asset):
        value = asset["hash"]
        if not re.fullmatch(r"[A-Z0-9]{8,80}", value):
            raise ModError("资源索引中的文件名无效。")
        path = (self.cache / value[:2] / value).resolve()
        if not path.is_relative_to(self.cache.resolve()):
            raise ModError("目标不在游戏缓存目录中。")
        return path

    def backup_dir(self, asset):
        self.target(asset)
        path = (self.data_dir / "backups" / asset["hash"]).resolve()
        if not path.is_relative_to(self.data_dir.resolve()):
            raise ModError("备份路径异常。")
        return path

    def metadata(self, asset):
        path = self.backup_dir(asset) / "record.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["asset"]["hash"] != asset["hash"]:
            raise ModError("备份记录与资源不匹配。")
        return record

    def backup_bytes(self, asset, record):
        data = (self.backup_dir(asset) / "original.bin").read_bytes()
        if sha(data) != record["original_sha"]:
            raise ModError("原始备份校验失败，禁止覆盖游戏文件。")
        return data

    def reference_asset(self, asset, record=None):
        """Only saved fingerprints/backups are trusted; never download a reference."""
        if asset.get("original_sha256"):
            return asset
        effective = dict(asset)
        if record and all(record["asset"].get(key) == asset.get(key) for key in ("hash", "key", "size")):
            # A verified immutable backup remains valid for an unchanged hash/key/size.
            effective["original_sha256"] = record["original_sha"]
            return effective
        return effective

    @contextmanager
    def locked(self):
        require_game_closed()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        import msvcrt
        with (self.data_dir / "write.lock").open("a+b") as lock:
            if lock.seek(0, 2) == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ModError("另一个窗口正在修改资源，请稍后再试。") from exc
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def read(self, asset):
        target = self.target(asset)
        if not target.is_file():
            raise ModError("该卡图未在本地缓存中找到。请在游戏中预览该卡，或确认索引版本是否匹配。")
        current = target.read_bytes()
        record = self.metadata(asset)
        if record:
            original = self.backup_bytes(asset, record)
            if sha(current) not in [record["original_sha"], *record["modded_shas"]]:
                raise ModError("缓存已被游戏或其他工具改动。保留备份，但不自动覆盖。")
        else:
            original = current
        effective = self.reference_asset(asset, record)
        if not effective.get("original_sha256"):
            if record:
                raise ModError("备份与本地清单参数不匹配，未继续读取或覆盖。")
            if len(original) != effective["size"]:
                raise ModError("本地纹理大小与清单不同，可能已被外部修改，未登记为原件。")
            effective = dict(effective, original_sha256=sha(original), fingerprint_source="unconfirmed_local")
        if len(original) != effective["size"] or sha(original) != effective["original_sha256"]:
            raise ModError("本地文件与已保存的恢复基准指纹不同，可能被其他工具修改；未继续操作。")
        doc = TextureDocument(original, effective, self.base)
        doc.validate_original()
        current_image = doc.image() if current == original else TextureDocument(current, effective, self.base).image()
        return doc, current_image, sha(current)

    def apply(self, asset, image, expected_sha, trust_local=False, context=None):
        with self.locked():
            doc, _, current_sha = self.read(asset)
            if current_sha != expected_sha:
                raise ModError("预览后游戏文件发生变化，请重新选择卡图再操作。")
            if doc.asset.get("fingerprint_source") == "unconfirmed_local":
                if not trust_local:
                    raise ModError("此资源没有已知原件指纹。请先明确确认将当前本地文件作为恢复基准。")
                doc.asset = dict(doc.asset, fingerprint_source="user_confirmed_local")
            modified, preview = doc.rebuild(image)
            directory = self.backup_dir(asset)
            directory.mkdir(parents=True, exist_ok=True)
            record = self.metadata(asset)
            if record is None:
                backup = directory / "original.bin"
                if backup.exists() and backup.read_bytes() != doc.encrypted:
                    raise ModError("发现不同的历史备份，未覆盖备份或游戏文件。")
                if not backup.exists():
                    with backup.open("xb") as output:
                        output.write(doc.encrypted)
                        output.flush()
                        os.fsync(output.fileno())
                record = {"asset": doc.asset, "original_sha": sha(doc.encrypted), "modded_shas": [],
                          "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self.backup_bytes(asset, record)
            modified_sha = sha(modified)
            if modified_sha not in record["modded_shas"]:
                record["modded_shas"].append(modified_sha)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            # For legacy records, keep an honest approximate first-backup time.
            if not record.get("created_at"):
                record["created_at"] = datetime.fromtimestamp((directory / "original.bin").stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
                record["created_at_estimated"] = True
            record["modified_at"] = now
            if context:
                record["context"] = {key: context[key] for key in ("name", "texture_id", "index_version") if key in context}
            # Journal the intended hash before writing so a crash remains recoverable.
            write_json(directory / "record.json", record)
            require_game_closed()
            target = self.target(asset)
            if sha(target.read_bytes()) != current_sha:
                raise ModError("写入前缓存发生变化，已停止。")
            atomic_write(target, modified)
            if sha(target.read_bytes()) != modified_sha:
                raise ModError("写入后校验失败；原始备份仍保留，请执行恢复。")
            return preview

    def _restore(self, asset, expected_sha=None):
        record = self.metadata(asset)
        if record is None:
            raise ModError("此卡图没有本工具创建的备份。")
        original = self.backup_bytes(asset, record)
        target = self.target(asset)
        if not target.is_file():
            raise ModError("原资源已不存在，可能游戏已更新；未写回旧版本资源。")
        current_sha = sha(target.read_bytes())
        if expected_sha is not None and current_sha != expected_sha:
            raise ModError("确认恢复后缓存发生变化，请刷新管理列表。")
        if current_sha == record["original_sha"]:
            return False
        if current_sha not in record["modded_shas"]:
            raise ModError("资源已被外部更新或修改，未强行覆盖；原始备份仍保留。")
        require_game_closed()
        if sha(target.read_bytes()) != current_sha:
            raise ModError("恢复前资源发生变化，已停止。")
        atomic_write(target, original)
        if sha(target.read_bytes()) != record["original_sha"]:
            raise ModError("恢复后校验失败。")
        return True

    def restore(self, asset):
        with self.locked():
            return self._restore(asset)

    def restore_all(self):
        restored, errors = 0, []
        with self.locked():
            for path in sorted((self.data_dir / "backups").glob("*/record.json")):
                try:
                    asset = json.loads(path.read_text(encoding="utf-8"))["asset"]
                    if path.parent.resolve() != self.backup_dir(asset):
                        raise ModError("备份记录目录不匹配。")
                    restored += int(self._restore(asset))
                except Exception as exc:
                    errors.append(f"{path.parent.name}: {exc}")
        return restored, errors

    def state(self, asset):
        target = self.target(asset)
        if not target.exists():
            return "未缓存"
        record = self.metadata(asset)
        if record is None:
            return "未修改"
        current = sha(target.read_bytes())
        if current == record["original_sha"]:
            return "已恢复"
        return "已替换" if current in record["modded_shas"] else "外部变更"
