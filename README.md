# Shadowverse: Worlds Beyond 资源解析实验

本项目的解包算法、数据格式和音频映射实现主要参考开源项目 **[Hypnos-PD/wbunpacker](https://github.com/Hypnos-PD/wbunpacker)**（MIT）。本项目不是从零独立发现所有加密方式，也不是该项目的官方分支；在参考公开实现后，编写了 Python 实验脚本，并使用本机资源副本核对结果。

具体参考位置：

- [资源清单格式与解析](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/manifest/src/lib.rs)：MasterMemory、MessagePack、LZ4。
- [AssetBundle XOR 解密](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/asset/src/lib.rs)：前 256 字节保留、基础参数与资源 Key 的组合。
- [音频包提取](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/audio/src/lib.rs)：Wwise 媒体提取与解码流程。
- [事件名称表解密和音频引用关系](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/audio/src/wwise.rs)：AES-CBC、SoundBank/HIRC。
- [卡牌语音配置](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/audio/src/card_voices.rs)与[主数据解析](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/master-data/src/lib.rs)：卡牌、文本、语音配置关联。部分列号不能直接照搬，须按实际版本核对。

其他来源与依赖：

- [SVWB-home-illustration-mod-tools](https://github.com/north-sight/SVWB-home-illustration-mod-tools)：其仓库提供的 `byd_mod_studio.exe` 用于第一份解密样本。外围脚本公开，核心解包程序源码在本次检查中未找到；不能将其核心视为已开源。
- [Hypnos-PD/svwb_manifests](https://github.com/Hypnos-PD/svwb_manifests)：最初的公开 JSON 清单与资源版本号线索。后续已从官方 CDN 独立下载并解析同版本清单。
- [UnityPy](https://github.com/K0lb3/UnityPy)：Unity 容器、序列化对象和纹理解析。
- [vgmstream](https://github.com/vgmstream/vgmstream)：游戏音频解码；本地测试使用 [r2117 Windows x64 发布包](https://github.com/vgmstream/vgmstream/releases/tag/r2117)。

更新日期：2026-10-20。所有修改和导出均在资源副本上进行，不修改游戏或机器人项目。本文路径均相对于项目根目录；游戏文件布局以游戏安装目录为根展示。本文是本项目唯一的自写说明入口；第三方工具自带说明、许可证另行保留。

### 维护与更新

本项目后续会持续维护和更新，随游戏资源变化逐步核对清单格式、解包方法、卡牌与音频映射，并同步更新使用说明。更新需要实际测试，不承诺每次游戏更新后立即兼容，也不表示脚本会自动跟踪最新版。

Git 仓库仅保存源码、文档和忽略规则。Python 缓存、游戏缓存副本、清单与主数据、导出素材、本地解密参数、下载工具和依赖均不上传；这些目录在本文中描述其本地用途，但新克隆的仓库不会自带。复用开源实现的版权和许可声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 1. 已验证范围与边界

- 已完成：指定资源版本下载官方清单、解析 JSON、卡图解密并导出 PNG、日语 PCK 提取 WEM 并解码 WAV、媒体与事件关联、三个样本的中文卡名/正式卡牌 ID/卡图/语音配置关联。
- 验证样本：最初两张卡图、后续三张关联卡图；日语包 `dx_10001110` 及三个新样本；一个界面包和一个原始字体样本。不是全量导出测试。
- 尚未完成：自动发现最新资源版本、通用批量管线、全部资源类别与版本兼容、模型/场景完整还原、Mod 导入封包及游戏内替换验证。
- 解密成功不等于游戏接受修改。清单存在校验数据，但尚未确认客户端执行校验的时机和行为。
- 解包工具的开源许可证不代表游戏素材获得了公开再分发授权。

## 2. 游戏文件怎样组织

```text
ShadowverseWB/
├── ShadowverseWB.exe                 启动程序
├── GameAssembly.dll                  编译后的游戏逻辑，不是卡图容器
└── ShadowverseWB_Data/
    ├── data.unity3d                  随安装提供的静态 Unity 资源
    ├── StreamingAssets/
    │   └── PreinResource/
    │       ├── sound/                内置音频
    │       └── movie/                内置视频
    └── Persistent/
        ├── dat/                      运行时下载资源的缓存目录
        │   ├── T3/
        │   │   └── T3CNCIECZBPCG2DVHKAEVI566I
        │   └── ……
        ├── meta                      存在该文件，内部格式和用途未解析
        └── 其他运行时数据
```

`dat` 是目录，不是一个大文件。复制时共有 38,643 个文件、26,961,434,433 字节（约 25.11 GiB）。缓存按文件标识前两个字符分目录；这个前缀不是资源类别。

不是所有资源都在 `dat` 中：静态资源、内置音视频、程序代码与部分配置位于其他路径。缓存里的文件也不是统一格式，仅仅统一采用无扩展名的存储命名。资源没有后缀，不代表没有内部格式。

清单路径能看到 UI、Card、Prefabs、3d、Battle、Story、Talk3D、Sleeve、Scenes、Font、Atlas、Shaders 等类别。它们涉及界面、卡牌表现、角色动画、战斗效果、剧情、卡背、场景、字体、图集等；这些是路径分类，不代表每个包都已完整解析。

### 2.1 逻辑路径与真实文件名

游戏使用逻辑资源名，例如：

```text
Assets/_Wizard2Resources/Card/Textures/100011300
```

它是资源系统的名称，不要求磁盘存在同名文件夹。清单将它对应到文件标识：

```text
逻辑名 → 清单记录 → hash → dat/<hash前两字符>/<hash>

Assets/.../Textures/100011300
→ T3CNCIECZBPCG2DVHKAEVI566I
→ dat/T3/T3CNCIECZBPCG2DVHKAEVI566I
```

本项目使用清单提供的 hash 定位文件，未验证其具体生成算法，不能默认它是 MD5 或 SHA256。

### 2.2 一个文件可以有多个对象，也可以依赖其他文件

Unity AssetBundle 是容器，可以包含 Texture2D、Sprite、Material、GameObject、动画等多个对象；它不是一张图片。测试卡图包有一个 AssetBundle 对象和一个 Texture2D，对应一张导出图片。界面样本则有 104 个对象。

一个包还可能引用其他包里的材质、纹理等资源。清单的包依赖与 Unity 内部的对象引用是不同层级；导出完整角色、场景通常需要处理两者。读出 MonoBehaviour 数据也不等于恢复原始 C# 源码。

## 3. 官方清单：下载、解析和定位资源

### 3.1 下载地址与版本

```text
https://shadowverse-wb.akamaized.net/dl/manifests/Windows/{资源版本}/assetbundle.Chs.manifest
```

语言支持 Chs、Cht、Eng、Kor；Jpn 在已参考的规则中使用不带语言后缀的 `assetbundle.manifest`。本项目实际下载验证了 Chs。

已验证版本为 `722884456691`，线索来自公开仓库的 `1.9.10:ver.722884456691` 提交，不是通过官方版本接口自动发现。资源版本号不同于应用版本号；官方 Version/info 本次请求超时，不能宣称上述版本永远是最新版。

获得新资源版本号后可重复下载。下载清单本身不下载图片或录音；还需准备对应版本资源文件。

### 3.2 二进制清单如何变成 JSON

本样本的结构为：

```text
MessagePack TOC（表目录）
    + 四张表的数据
    + 末尾 16 字节 MD5
```

TOC 为“表名 → [相对偏移, 长度]”；表的实际起点是 `TOC结束位置 + 相对偏移`。小表直接是 MessagePack 数组，大表为 Ext(99)：先读表示解压大小的 MessagePack 整数，再解压后面的 LZ4 数据，得到行数组。

`fetch-manifest.py` 校验 MD5，检查偏移、解压大小和行结构，再按字段位置生成 JSON，保留 64 位整数精度。未知结构直接报错，不静默猜字段。MD5 可检查本样本传输/内容的一致性，不是数字签名或发布者身份认证。

本次原件 2,704,766 字节，MD5 通过，解析出：

| JSON 部分 | 数量 | 用途 |
| --- | ---: | --- |
| `assets` | 34,826 | Unity 资源包记录 |
| `raw_assets` | 5,125 | 音频包、视频、字体、数据文件等记录 |
| `load_names` | 129 | 加载名称映射 |
| `config` | 1 | 清单配置 |

`assets` 主要字段：`name` 逻辑名、`hash` 文件标识、`asset_id` 清单内部编号、`all_dependencies` 依赖、`key` 单资源解密参数、`size` 大小、`category/group` 分类分组、`checksum` 校验值。`asset_id` 不是卡牌 ID；本项目不根据分组数值推断业务含义。

`raw_assets` 包含名称、hash、大小、分类、分组；官方原件还有一个参考 JSON 未保留的第六列，暂命名 `extra_5` 原样保存，未确定含义。raw 只是相对 Unity 包而言，不保证内部不封装或不加密。

### 3.3 下载实际资源

```text
https://shadowverse-wb.akamaized.net/dl/assetbundles/Windows/{hash前两字符}/{hash}
```

官方主数据就是通过该地址取得；多数测试资源读取自 `cache-copy/dat`。当前工具没有自动补齐全部缺失缓存的功能。

## 4. Unity 包与卡图的解密、解包

### 4.1 识别格式，而不是改后缀

测试缓存以 `UnityFS` 开头，但前 256 字节以后的数据仍经过 XOR。普通工具虽然认出容器，却会把未还原的内容当作压缩数据，导致 LZ4 失败。改名为 `.ab` 不能完成解密。

这不是“只有卡图加密”：同一方法也解开了界面预制体包。其他资源是否都兼容，仍需分别验证。

### 4.2 撤销 XOR 的准确规则

参数包括共享的基础字节数组 `base` 和清单中该资源自己的 64 位 `key`：

```python
key_bytes = (asset_key & ((1 << 64) - 1)).to_bytes(8, "little")
data = bytearray(encrypted)
for p in range(256, len(data)):
    data[p] ^= base[(p // 8) % len(base)] ^ key_bytes[p % 8]
```

- 前 256 字节原样保留。
- `p` 是从文件开头计算的绝对偏移，不在 256 处重新归零。
- Key 的 8 个字节逐个循环；base 每 8 个文件位置使用一个字节，再切换到下一字节。
- 本次 base 长度为 11，组合掩码周期为 88 字节；p=256 使用 base[10] 和 key_bytes[0]。
- XOR 与相同掩码作用两次恢复原值，因此加密/解密的字节变换可逆，文件长度不变。

### 4.3 base 从何而来

公开 wbunpacker 给出算法，但示例配置的基础参数为空。本项目先用 BYD 程序得到一份卡图明文，再利用：

```text
base对应字节 = 缓存字节 XOR 明文字节 XOR Key对应字节
```

`verify-transform.py` 检查每 8 字节的规律和重复周期，恢复出 11 字节 base，保存在 `local-keys/bundle-base.bin`。独立解密结果与 BYD 的 1,365,233 字节输出完全一致；随后不调用 BYD，成功导出其他卡图和界面包。没有附加游戏调试器或从进程提取密钥。

保留的 BYD 程序 SHA256 为 `E222CB00CA7FB0C6306AC2DD10FBF3F71B349B1CCDF29ABE89ED8E0404662C05`，仅用于标识本次样本程序，不代表安全认证。算法参数可能随版本变化，当前结果不保证未来通用。

### 4.4 从正常资源包到 PNG

```text
缓存 → 撤销 XOR → UnityFS → 解压数据块 → 解析 Unity 对象
     → 找到 Texture2D → 解码纹理 → 保存 PNG
```

后半段由 UnityPy 完成。Unity 包的数据块压缩和 Texture2D 自身的纹理编码是不同层：资源包解压后，纹理仍需解码，不一定存在可直接截出的 PNG。

样本省略有效 Unity 版本字符串，脚本使用 `2022.3.62f2` 作为回退。输出 `.ab` 是解密资源包，`.png` 是转换后的图片；添加扩展名仅方便辨认。

## 5. 音频包：PCK → WEM → WAV

日语卡牌语音逻辑路径示例：

```text
sound/Windows/d/Japanese(JP)/dx_10974110.pck
```

这些样本属于 raw_assets，文件头为 Wwise 的 `AKPK`，不需要卡图 XOR。处理步骤：

1. 读取小端包头，获得语言表、bank 索引、媒体索引等区段大小。
2. 媒体索引中每条已验证记录为 20 字节：媒体 ID、块大小、媒体大小、块偏移、语言 ID。
3. 媒体实际位置为 `块大小 × 块偏移`。检查范围与 RIFF/WAVE 标识、长度后提取 `.wem`。
4. 调用 vgmstream 将 WEM 解码为普通 PCM WAV，并记录采样率、声道、时长、大小。

一个 PCK 包含多段媒体；本次每个 WEM 是一段录音。WEM 虽然使用 RIFF/WAVE 标记，但编码不一定是普通 PCM；抽查三个包的首段均为 Wwise Custom Vorbis，不能只改成 `.wav` 后缀。导出的 WAV 均通过结构检查，为 48kHz、单声道、16-bit PCM；尚未逐段试听。

这些文件不是三套录音：PCK 是容器，WEM 是包内原始片段，WAV 是该片段解码后的表示。WAV 更大；将来可按用途转 MP3 或 SILK，当前没有在本项目实现这一步。

## 6. 媒体 ID、事件 ID、事件名称的关联

- **媒体 ID**：标识录音，如 `128602213.wem` 的编号；前文“音频 ID”统一指它。
- **事件 ID**：标识一个声音事件，不等于媒体 ID。
- **事件名称**：同一事件的可读名字，如 `Play_dx_10974110_3_sp`。
- **卡牌 ID**：标识卡牌，是另一套编号。

不要根据数字相似、文件排序或媒体 ID 大小推断用途。需要组合两类数据。

### 6.1 名称表：事件 ID → 名称

`sound/WwiseIdMapping.bytes` 在本版本清单中对应 `TSMVBMRGBE3BNCMKU7HARGFZAQ`，从缓存副本读取。其结构为：前 32 字节 AES-256 key，接着 16 字节 IV，其余为 AES-CBC 密文。

脚本调用 cryptography 解密并验证/移除 PKCS7 填充；明文开头是小端 u32 记录数，随后每条为 `[u32事件ID, u32名称字节长度, UTF-8名称]`。检查范围和结尾后得到 19,383 条名称记录。这是该文件的专用格式，不是所有 `.bytes` 或所有 Wwise 文件的统一格式；也与卡图 base 无关。

密钥随文件保存，所以这里是按已知格式还原数据，不是暴力破解 AES。此表不包含录音、台词或中文用途标签。

### 6.2 SoundBank：事件 ID → 录音

按 PCK 的 bank 索引取出以 `BKHD` 开始的 SoundBank，再解析其 `HIRC` 对象。对当前样本：Sound 对象（类型2）引用媒体 ID；Play Action（类型3，支持的动作标记 0x0403）引用 Sound；Event（类型4）引用动作列表。脚本按 ID 引用建立：

```text
事件名称 ↔ 事件 ID → 播放动作 ID → 声音对象 ID → 媒体 ID → WEM
  名称表负责前段           SoundBank 引用关系负责中段
```

解析时保留集合，允许多个事件共用录音或一个事件关联多条媒体，不强制一对一。当前样本三份包的 18 段媒体全部关联到事件名。`by-event/` 是按名称保存的 WAV 副本，ID 文件仍保留。

用途主要根据事件后缀和卡牌资源表的声明核对：`_1` 登场、`_2` 攻击、`_3` 进化、`_3_sp` 超进化、`_4` 破坏/退场、`_9_<编号>` 联动类事件。名称和配置声明已读取，尚未在游戏内逐条验证实际播放条件。

## 7. 卡名与卡图、语音怎样对应

### 7.1 主数据来源与格式

官方清单记录 `Master/mastermemory.bytes`，hash 为 `PHRTVQGOS7FKFWXXYTQNDBTN4Y`。缓存副本未匹配到它，因此从官方 CDN 下载原件，大小与清单一致，为 1,914,107 字节。

它也是 MasterMemory/MessagePack/LZ4 表结构，不是 Unity 包，不需要卡图 XOR。本次 TOC 有 201 张表，仅导出四张：CardMaster 5,552 行、CardResourceMaster 4,030 行、CardText 2,011 行、MasterTextLabel 29,748 行。

注意：本主数据样本的尾部 16 字节不等于前文 MD5，不能照搬 manifest 的尾部规则。脚本根据 TOC 在完整原始文件中取表，做范围及解析检查，记录 SHA256；不宣称完成了主数据的校验和验证。

### 7.2 当前版本核对过的关联字段

表记录是数组，下标从 0 开始：

| 来源 | 对应目标或用途 |
| --- | --- |
| `CardMaster[0]`、`[1]` | 正式 card_id、base_card_id |
| `CardMaster[2]` | 对应 `CardResourceMaster[0]`，找到资源配置 |
| `CardMaster[4]` | 对应 `CardText[0]`，找到文本配置 |
| `CardText[1]` | 卡名文本键，在 MasterTextLabel 中查询中文名称 |
| `CardResourceMaster[1]` | 在已测样本中对应卡图路径末段编号，已定位并导出 |
| `CardResourceMaster[38]` | 语音前缀，如 dx_10974110 |
| `[39]`、`[41]`、`[43]`、`[45]` | 登场相关、攻击、进化/超进化、退场相关事件声明 |

其他语音槽位见 `link-card-resources.py`。公开工具部分示例使用 `cm[9]` 关联资源，但不适用于本次表记录，不能直接照搬。上述列号须随版本重新检查，不是保证永远不变的协议。

```text
中文卡名 ← 文本表 ← CardMaster（卡牌 ID）
                         ↓ 资源引用
                 CardResourceMaster
                   ├── 卡图编号 → 清单 → 缓存 → PNG
                   └── 语音前缀与事件声明 → PCK/名称表 → WEM/WAV
```

多个 card_id 可以共用同一资源或录音，不能简单地给卡牌 ID 加减数字来生成全部资源路径。

### 7.3 完整关联验证结果

| 中文卡名（主数据原文） | card_id | 卡图编号 | 语音前缀 | 声明事件匹配 |
| --- | --- | --- | --- | --- |
| 束刃的罪人·卡特斯罗特 | 10974110 | 109741100 | dx_10974110 | 7/7 |
| 神纹的罪人·艾尔拉德 | 10964110 | 109641100 | dx_10964110 | 6/6 |
| 伊斯坦戴德 对 玛尔奇盖特 | 10954110 | 109541100 | dx_10954110 | 5/5 |

三张图均已导出为 1024×1024 PNG。结果 `master-data/card-resource-links.json` 包含卡名、ID、资源路径/hash、声明事件及媒体 ID/WAV 路径。样本匹配全部声明不代表所有版本、衍生卡和变体都已收齐。

## 8. 本项目目录与脚本

| 路径 | 用途 |
| --- | --- |
| `cache-copy/dat/` | 完整缓存副本，只作为输入 |
| `official-manifests/<版本>/<语言>/` | 官方原始清单、解析 JSON、来源及校验报告 |
| `local-keys/bundle-base.bin` | 当前 XOR 基础参数，11 字节；独立解密需要它 |
| `independent-export/<卡图编号>/` | 解密 `.ab` 和导出 `.png` |
| `audio-export/dx_<编号>-jp/` | PCK、WEM、WAV、报告、解码日志、事件命名副本 |
| `audio-export/event-map.json` | 三份包的媒体与事件关联 |
| `master-data/` | 主数据原件、四张表、关联结果与原件报告 |
| `other-export/` | 界面包、OTF 字体及验证报告 |
| `tools/python/` | UnityPy 等本地依赖 |
| `tools/vgmstream/` | 官方音频解码器及依赖 |
| `card-probe/` | 参数恢复的参考样本、旧公开清单、BYD 程序及首张卡图结果 |
| `fetch-manifest.py`、`test-fetch-manifest.py` | 官方清单下载解析、5 项离线测试 |
| `unpack-card.py` | 按卡图资源编号定位、解密、导出 |
| `unpack-audio.py` | 按日语 dx 包编号提取和解码音频 |
| `map-voice-events.py` | 名称表解密、SoundBank 引用解析和样本事件关联 |
| `inspect-card-master.py` | 从已下载主数据中导出四张表并打印样本 |
| `link-card-resources.py` | 生成三张卡牌的完整资源关联 |
| `inspect-unity.py`、`probe-other-resources.py` | 对象查看、非卡图包和字体验证 |
| `verify-transform.py` | 基于参考文件对恢复并验证 base |
| `prepare-card-manifest.py`、`run-card-probe.py` | 早期 BYD 单卡验证，当前独立导出不必运行 |

字体样本直接是带 OTTO 头部的 OTF；界面样本 BattleCardCounter 用 XOR 还原后读出 104 个对象。其他格式需单独选择解析器，不能全部送进 UnityPy 或全部执行 XOR。

## 9. 复现工作流

以下命令在项目根目录执行，以 Windows PowerShell 和 `py -3` 为例。需要 msgpack、lz4、UnityPy、cryptography 及其依赖，并保留 tools/vgmstream。依赖须能被 Python 导入；部分脚本会额外从 tools/python 加载依赖。项目尚未提供经过全新环境验证的依赖锁定和一键安装。

### 9.1 下载清单

```powershell
py -3 .\fetch-manifest.py --version 722884456691 --variant Chs
py -3 .\test-fetch-manifest.py
```

可用 `--compare 旧JSON路径` 对比清单；`--input 原始清单路径` 可离线解析。原始下载与解析输出按版本分开，不自动替换早期参考清单。

### 9.2 导出卡图

```powershell
py -3 .\unpack-card.py 109741100 --manifest .\official-manifests\722884456691\Chs\assetbundle.Chs.manifest.json
```

这里传入的是卡图资源编号，不是 card_id。显式传官方清单，避免默认使用 `card-probe/manifest-public.json` 的早期副本。结果在 `independent-export/109741100/`。

### 9.3 提取样本语音并建立事件映射

```powershell
py -3 .\unpack-audio.py 10974110
py -3 .\unpack-audio.py 10964110
py -3 .\unpack-audio.py 10954110
py -3 .\map-voice-events.py
```

`unpack-audio.py` 可用 `--manifest` 指定清单；当前默认 722884456691。这里的参数是 dx 包编号；虽然三个样本与基础卡牌 ID 相同，不能据此推广到全部资源。PCK 解析仅支持已验证布局，不能宣称兼容所有 PCK 变体。

### 9.4 主数据与完整关联

`mastermemory.bytes` 已下载到 `master-data/`。需要重新下载当前样本时：

```powershell
Invoke-WebRequest -Uri 'https://shadowverse-wb.akamaized.net/dl/assetbundles/Windows/PH/PHRTVQGOS7FKFWXXYTQNDBTN4Y' -OutFile .\master-data\mastermemory.bytes
py -3 .\inspect-card-master.py
py -3 .\link-card-resources.py
```

该 URL 只对应已验证版本中的资源。未来必须先从新清单查到 Master/mastermemory.bytes 的新 hash，不要永久沿用旧地址。

## 10. 更新版本时必须检查什么

1. 获得准确的资源版本号，下载该版本、该语言的清单；当前没有自动发现最新版。
2. 准备匹配的缓存副本，或按清单下载缺失资源。不要将旧文件强行改名当成新 hash。
3. 从新清单获取主数据与事件名称表的新 hash，重新解析对应文件。
4. 先选少量已知卡测试 XOR、Unity 格式、PCK 布局、主数据列结构及事件关联。
5. 当前 `map-voice-events.py`、`link-card-resources.py` 等仍写死版本和三个样本，`inspect-card-master.py` 读取固定主数据路径；更新时需明确修改输入，不能只换清单就声称整个流程已更新。
6. 确认中文卡名、资源归属、声明事件覆盖与导出文件正常，再扩展批量处理。记录缺失与失败，不静默丢弃。

当前没有通用的全量下载/导出、增量更新、MP3/SILK 发布及机器人接入管线，也没有执行 GitHub 素材上传。本文中的“已验证”只指列出的样本与版本；后续开发应在这些边界上逐步扩展。
