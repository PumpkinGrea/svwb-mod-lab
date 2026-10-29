# SVWB 卡图工坊

本项目的资源解包算法主要参考 **[Hypnos-PD/wbunpacker](https://github.com/Hypnos-PD/wbunpacker)**（MIT）。Unity 资源由 [UnityPy](https://github.com/K0lb3/UnityPy) 解析，第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

用于《Shadowverse: Worlds Beyond》的 Windows 卡图编辑器，支持按卡名查找、原图与替换图预览、裁剪缩放、自动备份及恢复。直接读取已安装游戏的本地资源，无需联网或启动游戏初始化。

## 下载与安装

1. 在 [Releases](https://github.com/PumpkinGrea/svwb-mod-lab/releases) 下载 Windows x64 程序压缩包。
2. 将完整的 `SVWBCardMod` 文件夹解压到游戏目录，与 `ShadowverseWB.exe` 同级。
3. 运行文件夹内的 `SVWBCardMod.exe`。无需安装 Python，不能删除 `_internal` 或只复制 exe。

```text
游戏目录/
├── ShadowverseWB.exe
├── ShadowverseWB_Data/
└── SVWBCardMod/
    ├── SVWBCardMod.exe
    └── _internal/
```

## 编辑器使用方法

### 查找与替换

1. 打开程序，确认游戏目录正确；未识别时点击“选择游戏目录”。程序默认自动读取本地索引，也可点击“刷新本地索引”。
2. 输入卡名的一部分、卡牌 ID 或纹理 ID，选中目标卡图。名称跟随游戏本地语言，繁体卡名可能需要使用繁体字搜索。
3. 核对预览：左侧是恢复基准图，右侧是当前图；导入图片后，右侧显示待替换效果。
4. 点击“导入替换图片”，选择裁剪填满、完整保留或拉伸，并调整位置、缩放。
5. **完全退出游戏**，点击“备份并应用替换”，确认提示。完成后启动游戏查看效果。

默认只列出已缓存卡图。图片缺失时，先在游戏中查看该卡并完成下载，再退出游戏回到工具。同一纹理可能由多张卡共用；“同组纹理候选”需通过预览确认。

### 恢复与管理

- “恢复选中卡图”：恢复该图的首次备份。
- “一键恢复全部”：恢复检查通过的全部修改。
- “修改与备份管理”：查看修改状态、搜索记录，支持多选恢复；“恢复全部可恢复项”不受当前筛选影响。

**恢复前也须退出游戏。请保留游戏目录下的 `SVWBModData/backups/`，更新程序时不要删除。** 首次替换以当时的本地文件作为恢复基准；若此前已被其他工具修改，恢复也只能回到该状态。

游戏更新后先刷新本地索引。工具遇到外部改动、备份不匹配或不支持的格式时会停止覆盖，不要手动把旧备份写回新资源。更多操作与排错见 [完整使用说明](USER_GUIDE.md)。

## 资源处理要点

- **资源位置**：`ShadowverseWB_Data/Persistent/meta` 保存资源清单；下载的资源位于 `Persistent/dat/<hash前两字符>/<hash>`，文件通常没有扩展名。
- **卡名与定位**：从安装文件 `data.unity3d` 读取配置，只读打开本地清单，再通过主数据关联卡名、卡牌 ID、纹理 ID 和缓存路径。
- **卡图处理**：按清单参数撤销 XOR，解析 Unity 资源包并解码纹理；替换时保留尺寸、纹理编码和 mipmap，重新封包、校验后写入，并保留首次备份。
- **音频脚本**：从 Wwise PCK 提取 WEM，经 vgmstream 转为 WAV；通过事件表关联卡牌语音。桌面编辑器目前只提供卡图编辑。

兼容性依据实际文件格式校验，游戏版本号变化本身不会阻止读取；格式改变仍可能需要更新工具。实现说明见 [本地资源索引](docs/LOCAL_RESOURCE_INDEX.md)，配置解码参考 [ProjectPrefs 技术文章](https://linux.do/t/topic/1737538)。

## 源码与构建

| 文件 | 用途 |
| --- | --- |
| `svwbmod.py`、`mod-entry.py` | 编辑器界面与程序入口 |
| `modtool/` | 本地索引、资源解析、替换及备份管理 |
| `build-mod.ps1`、`requirements-mod.txt` | Windows 打包脚本与依赖 |
| `tests/` | 解析、替换恢复和界面测试 |
| `fetch-manifest.py`、`unpack-card.py`、`unpack-audio.py` 等 | 独立资源研究与导出脚本 |

构建步骤见 [构建与发布说明](docs/BUILD.md)。仓库不包含游戏素材、个人备份或缓存；构建所需的基础格式参数可从同版本 Release 获取。

项目后续会持续维护，随游戏资源变化更新。游戏素材及相关权利归原权利人所有，如有侵权，请通过 Issue 联系，核实后及时删除。
