# 源码构建与发布

## Windows x64 构建

需要 Python 3.12 x64、PowerShell 和 Git。`build-mod.ps1` 创建 `tools/build-env` 虚拟环境、安装固定版本依赖、收集许可声明，然后使用 PyInstaller 打包。源码入口为 `svwbmod.py`，发行启动入口为 `mod-entry.py`。

1. 克隆仓库，在仓库根目录执行后续命令。
2. 创建 `local-keys` 目录。将同版本 Release 内 `SVWBCardMod/_internal/app-data/bundle-base.bin` 复制到 `local-keys/bundle-base.bin`。它是卡图 XOR 的基础格式参数，不是账号或 API 密钥。也可通过 README 中的参考文件方法自行准备。
3. 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-mod.ps1
```

输出为 `dist/SVWBCardMod/`，必须整目录分发。已安装游戏和完整缓存是运行条件，构建本身不需要游戏卡表、meta 副本或游戏运行。源码运行时也需要构建脚本生成的 `input/mod-app-data/bundle-base.bin`。

## 检查

```powershell
.\tools\build-env\Scripts\python.exe -m unittest discover -s tests -v
.\tools\build-env\Scripts\python.exe test-fetch-manifest.py
```

部分资源和 GUI 测试需要未提交的本地测试素材；缺失时会跳过，不能把跳过视为已验证替换。测试替换使用临时缓存副本，不应向真实游戏写测试图片。

构建自动执行启动检查。可额外对安装目录执行磁盘读取检查：

```powershell
.\dist\SVWBCardMod\SVWBCardMod.exe --game-dir "你的游戏目录" --smoke-test "检查报告的绝对路径.json" --verify-disk
```

该检查刷新本地索引、预览并在内存中重新封包，不写卡图。报告和旁边的截图用于核对；游戏无需运行。

## 发布内容

Release ZIP 含完整程序目录、使用说明、第三方声明和依赖许可。源码通过仓库及 GitHub 标签提供，不包含缓存、导出素材、个人备份、测试输入、Python 环境或构建中间产物。SHA256SUMS.txt 用于下载完整性校验。

更新程序时替换 `SVWBCardMod/`，保留同级 `SVWBModData/`，特别是 `backups/`。游戏更新后先刷新本地索引。兼容性由实际解析及校验决定，不按客户端哈希白名单拒绝；格式变化仍可能需要更新工具。
