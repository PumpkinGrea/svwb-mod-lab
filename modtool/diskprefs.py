"""Read ProjectPrefs from installed Unity assets; no running game required.

Decoder reference: https://linux.do/t/topic/1737538 (ProjectPrefs section).
Constants are format parameters, not account credentials or a client whitelist.
"""
import base64
import struct
from .core import ModError


def parse_entries(raw):
    def integer(offset):
        if offset < 0 or offset + 4 > len(raw):
            raise ModError("ProjectPrefs 数据不完整。")
        return struct.unpack_from('<i', raw, offset)[0]
    name_size = integer(28)
    if not 0 <= name_size <= 4096:
        raise ModError("ProjectPrefs 名称结构不受支持。")
    pos = (32 + name_size + 3) & ~3
    count = integer(pos)
    pos += 4
    if not 0 < count <= 10000:
        raise ModError("ProjectPrefs 集合结构不受支持。")
    result = {}
    for _ in range(count):
        pair = []
        for _ in range(2):
            size = integer(pos)
            pos += 4
            if not 0 < size <= min(1024 * 1024, len(raw) - pos):
                raise ModError("ProjectPrefs 字符串长度无效。")
            pair.append(raw[pos:pos + size])
            pos = (pos + size + 3) & ~3
        if pair[0] in result:
            raise ModError("ProjectPrefs 包含重复配置项。")
        result[pair[0]] = pair[1]
    if pos != len(raw):
        raise ModError("ProjectPrefs 存在未知字段，需要适配格式。")
    return result


def decode_key(entries):
    from py3rijndael import RijndaelCbc, Pkcs7Padding
    key = base64.b64decode('OnOFurwfBWIQHlCBf/2aHsQRvP2BGxGZcMfJf13Bcao=')
    iv = base64.b64decode('CNMAeKOLwe84toAHQcJBapYARVF4CZnbmk7aSsjIpHI=')
    def cipher():
        return RijndaelCbc(key, iv, Pkcs7Padding(32), block_size=32)
    name = base64.b64encode(cipher().encrypt(b'sqlite3mcKey'))
    try:
        encrypted = base64.b64decode(entries[name], validate=True)
        decoded = cipher().decrypt(encrypted)
        if not 0 < len(decoded) <= 512 or cipher().encrypt(decoded) != encrypted:
            raise ValueError('Invalid parameter')
        return decoded
    except (KeyError, ValueError, IndexError) as exc:
        raise ModError("磁盘配置解码失败；配置格式或加密参数可能已经变化。") from exc


def disk_key(game_dir):
    import UnityPy
    path = game_dir / 'ShadowverseWB_Data/data.unity3d'
    if not path.is_file():
        raise ModError("找不到游戏安装资源 data.unity3d。")
    env = UnityPy.load(str(path))
    matches = []
    for obj in env.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        try:
            # UnityPy knows the base fields; our bounded parser handles the
            # remaining serialized fields (this asset has no custom typetree).
            data = obj.read(check_read=False)
            script = data.m_Script.deref().read()
            hit = script.m_Name == 'ProjectPrefs' and script.m_Namespace == 'Cute.Core'
        except Exception:
            continue
        if hit:
            matches.append(obj.get_raw_data())
    if len(matches) != 1:
        raise ModError("无法唯一定位磁盘 ProjectPrefs 配置，需要适配资源结构。")
    return decode_key(parse_entries(matches[0]))
