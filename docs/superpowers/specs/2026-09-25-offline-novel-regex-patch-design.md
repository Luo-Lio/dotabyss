# 离线剧情 Regex 用户名补丁设计

## 背景

离线客户端播放 Novel 时，原生 `NovelCmdMessageTextCenter` 会把缺失的用户昵称作为 `null` 传给 `Regex.Replace`，导致 `ArgumentNullException: replacement`。现有 `StoryViewer 0.7.17` 补丁目标是普通托管 `System.Text.RegularExpressions.Regex`，没有命中 IL2CPP 客户端实际调用的互操作类型；此外只覆盖了五参数重载。

## 方案

将补丁目标改为客户端互操作程序集中的 `Il2CppSystem.Text.RegularExpressions.Regex`，分别为四参数和五参数静态 `Replace` 重载安装 Harmony Prefix。两个 Prefix 共用同一个归一化函数：仅将 `null` replacement 转为 `司令官`，非空字符串（包括空字符串）原样保留；补丁仍仅在 `OfflineApi=true` 时安装。

## 验证

- 测试项目验证 `null`、非空昵称、空字符串和实际 Regex 替换结果。
- 构建后反编译最终 DLL，确认目标类型为 `Il2CppSystem.Text.RegularExpressions.Regex` 且两个重载均存在。
- 部署到 `client/BepInEx/plugins/StoryViewer/` 并核对源 DLL 与部署 DLL SHA-256 一致。
- 启动客户端后播放 `mas_1001040501`，确认日志出现补丁命中记录且不再出现 `replacement` 异常。

## 范围与限制

本次不改剧情脚本、不改在线模式行为、不改变 Addressables 兜底策略，也不提交 Git 历史。若运行时仍不命中，将依据新的补丁安装/运行日志继续定位，不把编译通过当作实机验证通过。
