# Shadowverse: Worlds Beyond 资源解析

本项目的解包算法、数据格式和音频映射实现主要参考开源项目 **[Hypnos-PD/wbunpacker](https://github.com/Hypnos-PD/wbunpacker)**（MIT），并以 Python 脚本实现相关资源的解析与导出。本项目不是该项目的官方分支，也不是从零独立发现所有加密方式。

主要参考：

- [清单解析](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/manifest/src/lib.rs)：MasterMemory、MessagePack 和 LZ4。
- [AssetBundle 解密](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/asset/src/lib.rs)：资源 XOR 变换。
- [音频解析](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/audio/src/lib.rs)与 [Wwise 映射](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/audio/src/wwise.rs)：音频提取、事件名称表和 SoundBank 引用。
- [卡牌语音配置](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/audio/src/card_voices.rs)与 [主数据解析](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/master-data/src/lib.rs)：卡牌、文本和资源的关联。

Unity 对象与纹理由 [UnityPy](https://github.com/K0lb3/UnityPy) 解析，音频由 [vgmstream](https://github.com/vgmstream/vgmstream) 解码。第三方版权与许可声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

项目后续会持续维护，随游戏资源变化更新解析方法与说明；不保证每次游戏更新后立即兼容。

## 1. 游戏目录与资源组织

以下路径以游戏安装目录为根：

```text
ShadowverseWB/
├── ShadowverseWB.exe
├── GameAssembly.dll                 编译后的游戏逻辑
└── ShadowverseWB_Data/
    ├── data.unity3d                  随安装提供的 Unity 资源
    ├── StreamingAssets/PreinResource/
    │   ├── sound/                    内置音频
    │   └── movie/                    内置视频
    └── Persistent/
        ├── dat/
        │   └── <hash前两字符>/<hash>  运行时下载的资源缓存
        ├── meta                      内部格式与用途尚未解析
        └── 其他运行时数据
```

`dat` 是包含大量无扩展名文件的目录，不是一个大文件。文件按清单中的 hash 前两字符分目录存放；这个前缀不代表资源类别，hash 的具体生成算法尚未确认。

缓存并非统一格式：其中有 Unity AssetBundle、Wwise 音频包、字体和其他数据。没有后缀不代表没有内部格式，也不能对所有文件使用同一种解密或解包方法。部分静态资源、内置音视频和程序代码位于缓存之外。

游戏使用逻辑资源名，而非直接使用磁盘路径。例如：

```text
Assets/_Wizard2Resources/Card/Textures/<卡图资源编号>
    → 清单记录中的 hash
    → Persistent/dat/<hash前两字符>/<hash>
```

Unity AssetBundle 是容器，可以包含 Texture2D、Sprite、Material、GameObject、动画等多个对象，并依赖其他资源包。导出完整场景或角色需要同时处理包依赖与对象引用；读取 MonoBehaviour 数据不等于恢复原始 C# 源码。

## 2. 官方清单与资源定位

Windows 简体中文清单地址：

```text
https://shadowverse-wb.akamaized.net/dl/manifests/Windows/{资源版本}/assetbundle.Chs.manifest
```

其他语言后缀为 `Cht`、`Eng`、`Kor`；日语使用不带语言后缀的 `assetbundle.manifest`。资源版本号不同于应用版本号，需提供准确版本；当前未实现自动发现最新版本。

清单结构为 MessagePack 表目录（TOC）、各表数据和末尾 16 字节 MD5。TOC 记录表名、相对偏移及长度，表起点为 `TOC结束位置 + 相对偏移`。小表直接使用 MessagePack 数组；压缩表使用 Ext(99)，其中先保存 MessagePack 格式的解压大小，再保存 LZ4 数据。

`fetch-manifest.py` 校验 MD5、偏移和解压大小后导出 JSON，主要包含：

| 表 | 内容 |
| --- | --- |
| `assets` | Unity 资源的逻辑名、hash、内部编号、依赖、解密 key、大小、分类和校验字段 |
| `raw_assets` | 音频包、视频、字体及数据文件等的名称与 hash；未知列保留为 `extra_5` |
| `load_names` | 加载名称映射 |
| `config` | 清单配置 |

`assets.asset_id` 是清单内部编号，不是卡牌 ID。`raw_assets` 只是相对 Unity 包的分类，不保证文件内部没有封装或加密。MD5 用于一致性检查，不是发布者身份认证。

实际资源下载地址由清单 hash 组成：

```text
https://shadowverse-wb.akamaized.net/dl/assetbundles/Windows/{hash前两字符}/{hash}
```

清单只负责描述与定位资源，下载清单不会同时下载全部素材。

## 3. Unity 资源与卡图解包

部分缓存虽然以 `UnityFS` 开头，但从第 256 字节起仍有 XOR 变换。直接改成 `.ab` 后缀并不能解密，普通工具可能在解压数据块时失败。

解密使用共享字节数组 `base` 和清单中该资源的 64 位 `key`：

```python
key_bytes = (asset_key & ((1 << 64) - 1)).to_bytes(8, "little")
data = bytearray(encrypted)
for p in range(256, len(data)):
    data[p] ^= base[(p // 8) % len(base)] ^ key_bytes[p % 8]
```

前 256 字节不变，`p` 是文件绝对偏移。Key 按 8 字节循环，base 每 8 个文件字节切换到下一项。当前本地 base 长度为 11，组合掩码周期为 88 字节；XOR 变换可逆且不改变文件长度。

`base` 存于本地 `local-keys/bundle-base.bin`，不随仓库分发。`verify-transform.py` 可以利用同一资源的密文、已解密文件及清单 key 恢复并核对 base，关系为：

```text
base对应字节 = 密文字节 XOR 明文字节 XOR key对应字节
```

参考明文使用 [SVWB-home-illustration-mod-tools](https://github.com/north-sight/SVWB-home-illustration-mod-tools) 提供的 BYD 程序取得；该仓库公开了外围脚本，但未找到核心解包程序的源码。base 与资源格式都可能随版本变化。

后续导出流程：

```text
缓存文件 → 撤销 XOR → UnityFS 数据块解压 → Unity 对象解析
         → Texture2D 纹理解码 → PNG
```

UnityPy 负责解密后的解压、对象解析和纹理解码；资源包压缩与纹理编码是不同层级，并非直接从包中截出 PNG。缺少有效 Unity 版本字符串时，脚本使用 `2022.3.62f2` 回退。

此方法不只用于卡图，也适用于已验证的其他 Unity 包，但不保证兼容全部资源。项目目前负责解析与导出，未实现或验证 Mod 重新封包及游戏内替换。

## 4. 音频提取与事件映射

日语卡牌语音的逻辑路径形如 `sound/Windows/d/Japanese(JP)/dx_<编号>.pck`。已验证的 PCK 以 `AKPK` 开头，不需要卡图 XOR 处理。

解析器读取包头及媒体索引；已支持布局中，每条媒体记录为 20 字节，包含媒体 ID、块大小、媒体大小、块偏移和语言 ID。媒体起点为 `块大小 × 块偏移`，按媒体大小截取并检查 RIFF/WAVE 标记后得到 WEM，再由 vgmstream 解码成 PCM WAV。

PCK 是包含多段媒体的容器，WEM 是提取出的音频片段，WAV 是片段解码后的表示，并非三套不同录音。WEM 使用 RIFF/WAVE 封装但不一定是 PCM，不能仅修改后缀当作普通 WAV。解析器目前仅覆盖已验证的 Wwise 包布局。

事件名称来自 `sound/WwiseIdMapping.bytes`：前 32 字节为 AES-256 key，随后 16 字节为 IV，其余部分为 AES-CBC 密文。解密并移除 PKCS7 填充后，先读取小端 u32 记录数，再依次读取 `[u32事件ID, u32名称字节长度, UTF-8名称]`。这是该文件的专用格式，与卡图 XOR 无关，也不是所有 `.bytes` 文件的通用格式。

名称表只负责“事件 ID → 名称”；事件与录音的对应关系来自 PCK 内以 `BKHD` 开头的 SoundBank。解析其 HIRC 对象，沿 Event（类型 4）、Play Action（类型 3）、Sound（类型 2）的引用得到媒体 ID：

```text
事件名称 ↔ 事件 ID → 播放动作 ID → 声音对象 ID → 媒体 ID → WEM/WAV
```

当前实现支持的播放动作标记为 `0x0403`。关联结果保留多对多关系，不假定一个事件只对应一段录音。事件名中 `_1`、`_2`、`_3`、`_3_sp`、`_4` 通常对应登场、攻击、进化、超进化和退场，具体用途需结合卡牌资源表声明，不能通过媒体编号大小推断。

## 5. 卡名、卡图与语音的关联

官方清单中的 `Master/mastermemory.bytes` 保存主数据，使用 MasterMemory、MessagePack 和 LZ4 表结构，不是 Unity 包，也不需要卡图 XOR。其尾部不能直接套用 manifest 的 MD5 规则；解析时依据 TOC 在完整文件中读取各表。

主要使用 `CardMaster`、`CardResourceMaster`、`CardText` 和 `MasterTextLabel` 四张表。当前版本核对的数组下标从 0 开始：

| 字段 | 用途 |
| --- | --- |
| `CardMaster[0]`、`[1]` | 卡牌 ID、基础卡牌 ID |
| `CardMaster[2]` | 关联 `CardResourceMaster[0]` |
| `CardMaster[4]` | 关联 `CardText[0]` |
| `CardText[1]` | 卡名文本键，关联 MasterTextLabel 中的中文名称 |
| `CardResourceMaster[1]` | 已验证资源中的卡图编号 |
| `CardResourceMaster[38]` | `dx_...` 语音前缀 |
| `CardResourceMaster[39]`、`[41]`、`[43]`、`[45]` | 登场、攻击、进化相关、退场相关事件声明 |

其他语音槽位见 `link-card-resources.py`。列号需要随数据版本核对，不应视为永远固定的协议。

通过文本表得到卡名，通过 CardMaster 找资源配置，再分别关联卡图清单、语音包及事件映射。卡牌 ID、卡图编号、语音前缀和媒体 ID 是不同概念；多个卡牌可以共用资源，不能单纯通过给卡牌 ID 添加数字来推导所有路径。

## 6. 项目文件用途

仓库只分发源代码与文档。以下输入、参数、依赖及导出目录均已忽略，新克隆的仓库不会自带其中内容。Python 脚本依赖 msgpack、lz4、UnityPy、cryptography 等库，音频解码另需 vgmstream。

| 目录或文件 | 用途 |
| --- | --- |
| `cache-copy/dat/` | 游戏缓存副本，作为解析输入，避免修改游戏原文件 |
| `official-manifests/<版本>/<语言>/` | 官方清单原件、解析 JSON 和校验报告 |
| `local-keys/bundle-base.bin` | 本地 XOR 基础参数 |
| `independent-export/<卡图编号>/` | 解密后的 `.ab` 与导出的 PNG |
| `audio-export/` | PCK、WEM、WAV、事件映射、日志与报告 |
| `master-data/` | 主数据原件、导出的表和卡牌资源关联结果 |
| `other-export/` | 其他资源的导出结果 |
| `tools/python/`、`tools/vgmstream/` | 本地 Python 依赖与音频解码器 |
| `card-probe/` | 参考文件对、旧清单及 BYD 工具输入输出 |

| 脚本或文档 | 用途 |
| --- | --- |
| `fetch-manifest.py` | 按指定资源版本下载、校验并解析清单，也支持离线解析 |
| `test-fetch-manifest.py` | 清单解析的离线测试 |
| `unpack-card.py` | 按卡图资源编号定位缓存、解密并导出图片；可用 `--manifest` 指定清单 |
| `unpack-audio.py` | 按日语 dx 包编号提取并解码音频；可用 `--manifest` 指定清单 |
| `map-voice-events.py` | 解密事件名称表、解析 SoundBank 并建立媒体关联 |
| `inspect-card-master.py` | 从主数据中导出卡牌、资源和文本表 |
| `link-card-resources.py` | 生成卡名、卡牌 ID、卡图和语音的关联结果 |
| `inspect-unity.py` | 查看 Unity 资源包内的对象 |
| `probe-other-resources.py` | 检查其他 Unity 包及字体资源 |
| `verify-transform.py` | 通过参考文件对恢复与验证 XOR base |
| `prepare-card-manifest.py`、`run-card-probe.py` | BYD 单卡处理的辅助脚本，独立解包不必运行 |
| `.gitignore` | 排除游戏资源、导出文件、依赖、本地参数与 Python 缓存 |
| `THIRD_PARTY_NOTICES.md` | 第三方代码的版权与许可声明 |

部分映射脚本仍使用固定版本、路径或预设卡牌列表，尚非通用全量导出工具；更换资源版本时应检查脚本输入与表字段。

游戏素材及相关权利归原权利人所有，本仓库不分发游戏素材。如有侵权，请权利人通过 Issue 联系，核实后及时删除。
