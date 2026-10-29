"""Read installed resource DB using disk ProjectPrefs; no process access.

SQLite3MC interface reference: Hypnos-PD/wbunpacker, MIT.
"""
from contextlib import contextmanager
import ctypes as C
import os
from pathlib import Path
import re

from .core import ModError


class LocalReader:
    def __init__(self, game_dir):
        self.game_dir = Path(game_dir).resolve()
        self.native = self.game_dir / "ShadowverseWB_Data/Plugins/x86_64/libnative.dll"

    def initialize(self):
        self.read()
        return "已从磁盘配置验证本地清单；无需启动游戏或读取进程。"

    @contextmanager
    def connection(self, key):
        # Only the selected installation's game-provided SQLite implementation.
        with os.add_dll_directory(str(self.native.parent)), os.add_dll_directory(str(self.game_dir)):
            dll = C.CDLL(str(self.native))
        db = C.c_void_p()
        dll.sqlite3_open_v2.argtypes = [C.c_char_p, C.POINTER(C.c_void_p), C.c_int, C.c_char_p]
        dll.sqlite3_close.argtypes = [C.c_void_p]
        dll.sqlite3mc_config.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
        dll.sqlite3_key.argtypes = [C.c_void_p, C.c_void_p, C.c_int]
        path = self.game_dir / "ShadowverseWB_Data/Persistent/meta"
        if dll.sqlite3_open_v2(str(path).encode("utf-8"), C.byref(db), 1, None):
            if db:
                dll.sqlite3_close(db)
            raise ModError("无法以只读方式打开本地 meta 清单。")
        try:
            if dll.sqlite3mc_config(db, b"cipher", 3) != 3 or dll.sqlite3_key(db, key, len(key)):
                raise ModError("本地清单参数不匹配，未修改游戏。")
            callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.POINTER(C.c_char_p), C.POINTER(C.c_char_p))
            dll.sqlite3_exec.argtypes = [C.c_void_p, C.c_char_p, callback_type, C.c_void_p, C.POINTER(C.c_char_p)]
            def query(sql):
                rows, errors = [], []
                @callback_type
                def callback(_, n, values, names):
                    try:
                        if len(rows) >= 200000:
                            raise ValueError("本地清单超过记录数量限制")
                        rows.append({names[i].decode(): values[i].decode("utf-8", "strict") if values[i] else None for i in range(n)})
                        return 0
                    except Exception as exc:
                        errors.append(exc)
                        return 1
                code = dll.sqlite3_exec(db, sql.encode(), callback, None, None)
                if code or errors:
                    raise ModError(f"本地清单读取失败（{code}）；可能正在更新、参数不匹配或结构变化。")
                return rows
            query("BEGIN")  # Consistent read-only transaction; no rekey/DDL/UPDATE.
            yield query
        finally:
            dll.sqlite3_close(db)

    def read(self, key=None):
        if key is None:
            from .diskprefs import disk_key
            key = disk_key(self.game_dir)
        with self.connection(key) as query:
            columns = {r["name"] for r in query("PRAGMA table_info(a)")}
            if not {"n", "h", "l", "e"}.issubset(columns):
                raise ModError("本地清单结构已改变，需要适配工具。")
            rows = query("SELECT n,h,l,e FROM a WHERE n LIKE 'Assets/_Wizard2Resources/Card/Textures/%' OR n='Master/mastermemory.bytes' ORDER BY n")
            roots = query("SELECT n,h FROM c ORDER BY n")
        assets, master = [], None
        for row in rows:
            if not row["h"] or not re.fullmatch(r"[A-Z0-9]{8,80}", row["h"]):
                raise ModError("本地清单文件标识无效。")
            item = {"name": row["n"], "hash": row["h"], "size": int(row["l"]), "key": int(row["e"])}
            if not 0 < item["size"] <= 128 * 1024 * 1024 or not -(1 << 63) <= item["key"] < (1 << 64):
                raise ModError("本地清单资源参数超出支持范围。")
            if item["name"] == "Master/mastermemory.bytes":
                master = item
            else:
                assets.append(item)
        if not assets or master is None:
            raise ModError("本地清单缺少卡图或主数据记录，请先让游戏完成资源下载。")
        return {"assets": assets, "master": master, "roots": roots}
