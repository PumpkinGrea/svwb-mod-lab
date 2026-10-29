# 本地资源索引实现

桌面编辑器现在只读取安装目录，不再从社区发现版本、请求官方 CDN 或使用内置在线卡表。普通操作见 [使用说明](../USER_GUIDE.md)。SQLite3MC 接口参考 [wbunpacker 的 metadb 模块](https://github.com/Hypnos-PD/wbunpacker/blob/master/crates/metadb/src/lib.rs)（MIT）。

## 数据路径

```text
data.unity3d → ProjectPrefs 配置 → 解码数据库参数
                                     ↓
Persistent/meta（只读 SQLite3MC）
  → 主数据 hash → dat/<前两字符>/<hash> → MasterMemory 表
  → 卡图逻辑名、hash、大小、XOR key          ↓
                     卡名 ↔ 卡牌 ID ↔ 纹理 ID
                                      ↓
                       SVWBModData/index/ 本地快照
```

`meta` 是加密数据库，使用安装目录的 `ShadowverseWB_Data/Plugins/x86_64/libnative.dll` 在独立工具进程中打开，`sqlite3_open_v2` 仅设置只读标志。使用 cipher 3、资源数据库参数，通过只读事务获得一致的查询结果，不执行 rekey、DDL 或 UPDATE。

已核对字段：`a.n` 是逻辑名，`a.h` 是缓存 hash，`a.l` 是字节大小，`a.e` 是资源 XOR key，**不是 `a.c`**。缓存路径为 `Persistent/dat/<hash前两字符>/<hash>`。`c` 表保存 `//root` 等清单标识；`i.version` 不能直接当作 CDN 数字版本，根 hash 的生成算法也未确认。`ln`、`r`、`le` 等表不是当前卡图检索所必需的。

主数据解析读取 `CardMaster`、`CardResourceMaster`、`CardText`、`MasterTextLabel`。名称语言来自本地安装，不另行下载简体中文表。2026-10-20 验证的数据包含 39,974 条资源、1,843 条卡图纹理；数量只是该安装状态的观测，不是固定常量。

## 直接从磁盘取得配置

`modtool/diskprefs.py` 使用 UnityPy 读取安装目录的 `ShadowverseWB_Data/data.unity3d`，通过 MonoBehaviour 的脚本类型 `Cute.Core.ProjectPrefs` 定位配置对象，不固定对象的 path ID，也不使用进程内存地址。

当前支持的序列化布局为 MonoBehaviour 基础字段、对齐的名称字符串、配置条目数以及成对的长度前缀字符串。每个字符串按 4 字节对齐；检查边界、重复项、数量和末尾剩余字节，未知结构直接报错。配置名 `sqlite3mcKey` 和对应值使用 Base64、Rijndael-CBC（256 位块/密钥和 IV、PKCS7）处理，区别于普通 AES 的 128 位块。解码后重新加密回算，再通过实际只读数据库查询验证。解码值直接传给 SQLite3MC，不再做第二次 Base64 解码。

配置解码方法及固定格式参数参考 [ProjectPrefs 技术文章](https://linux.do/t/topic/1737538)，本项目自行实现磁盘对象定位、边界校验及读取流程。数据库参数仅在本次解析内存中使用，不写参数文件、不输出日志。未调用游戏进程 API，不要求启动游戏，不依赖 DPAPI 或任何旧初始化结果。

兼容性由实际配置解码、数据库表字段、主数据关联和纹理回读校验决定，取消客户端二进制哈希白名单。版本号变化本身不会拒绝读取；配置格式、数据库实现或资源变换方式改变仍可能需要适配。缺失的安装或下载资源不能由工具凭空生成。

2026-10-29 对更新后的安装文件验证，游戏未运行时读出 1,998 条纹理记录及 2,081,406 字节主数据；数量仅为该次安装状态的观测。

## 索引提交和安全边界

- `modtool/updater.py` 将本地资源映射和主数据 SHA-256 组合生成 `local:<SHA-256>` 标识，构造 schema 2、`source=local` 的索引。该标识不是官方资源版本。
- 同一索引目录使用文件锁避免并发提交；解析后重新读取清单和主数据，拒绝更新过程中的混合快照。
- 快照按内容哈希保存，最后原子切换当前指针。失败保留旧索引；可回退上一份本地快照。不接受旧在线索引或内置卡表作为搜索来源。
- 刷新不下载游戏资源，也不修改 Mod 或备份。主数据必须已缓存，单张图片未缓存时需先让游戏下载。
- 本地清单提供定位和解码参数，但目前没有独立验证本地文件为官方原件的依据。未知指纹纹理可预览，首次替换必须额外确认以当前本地文件为恢复基准，记录为 `user_confirmed_local`，不冒充官方指纹。已有首次备份保持不变。
- 客户端更新、表结构、基础 XOR 参数或纹理格式变化都可能需要适配程序，不能仅靠刷新解决。

## 实现文件

| 文件 | 责任 |
| --- | --- |
| `modtool/diskprefs.py` | 安装资源中的 ProjectPrefs 定位与配置解码 |
| `modtool/localmeta.py` | 使用磁盘配置只读查询 SQLite3MC |
| `modtool/formats.py` | 本地主数据 MasterMemory 解码 |
| `modtool/catalog.py` | 卡名/卡牌/纹理关联及索引校验 |
| `modtool/updater.py` | 本地刷新、原子快照与回退 |
| `modtool/core.py` | 缓存解码、预览、基准备份和替换恢复 |
| `svwbmod.py` | 界面入口与用户确认 |
| `tests/` | 临时缓存测试、禁止网络的本地刷新测试及界面流程 |

原先的在线更新模块、内置搜索 catalog 生成脚本和一次性本地探测脚本已移除。仓库保留的 `fetch-manifest.py` 是独立资源研究脚本，不被桌面编辑器导入或调用。
