# 离线剧情 Regex 用户名补丁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让离线 Novel 播放路径拦截 IL2CPP Regex 的 null replacement，避免 `NovelCmdMessageTextCenter` 崩溃。

**Architecture:** 保留现有离线模式开关和用户名归一化逻辑，把 Harmony 目标从普通 CLR Regex 换成客户端 IL2CPP Regex，并为四参数、五参数静态 Replace 分别安装 Prefix。纯函数测试继续验证归一化边界；客户端运行日志验证真实调用链。

**Tech Stack:** C#/.NET 6、BepInEx IL2CPP、HarmonyLib、PowerShell、dotnet build。

## Global Constraints

- 仅离线 `OfflineApi=true` 时启用补丁。
- `null` replacement 使用 `司令官`；非空昵称和空字符串保持原样。
- 不修改剧情脚本和在线模式行为。
- 不启动常驻服务，不提交 Git 历史。

---

### Task 1: 用例与补丁目标

**Files:**
- Modify: `tools/client-mod/StoryViewer.Tests/Program.cs`
- Modify: `tools/client-mod/StoryViewer/Patches/OfflineNovelUserNamePatch.cs`

**Interfaces:**
- Consumes: `OfflineUserName.Resolve(string?)` and client interop types from `client/BepInEx/interop`.
- Produces: IL2CPP Regex four-parameter and five-parameter Harmony targets with identical null normalization.

- [x] **Step 1: Add/retain boundary assertions** for null, non-empty, empty string, and a replacement result in `Program.cs`.
- [x] **Step 2: Run the test before the production target change** with `dotnet run --project tools/client-mod/StoryViewer.Tests/StoryViewer.Tests.csproj`; the test failed because `ResolveReplacement` was absent, and static inspection confirmed the old target mismatch.
- [x] **Step 3: Change the production patch target** to `Il2CppSystem.Text.RegularExpressions.Regex`, adding the four-parameter overload alongside the existing timeout overload and sharing one normalization helper.
- [x] **Step 4: Build the StoryViewer project** and inspect the compiled target with `ilspycmd`; both IL2CPP overload signatures are present.
- [x] **Step 5: Run the boundary tests again**; they pass.

### Task 2: Deploy and verify on the client

**Files:**
- Modify: `client/BepInEx/plugins/StoryViewer/StoryViewer.dll` (generated deployment artifact)

**Interfaces:**
- Consumes: Release DLL from Task 1.
- Produces: deployed DLL with matching SHA-256 and runtime evidence from `Player.log`/`LogOutput.log`.

- [x] **Step 1: Deploy with** `pwsh -File tools/client-mod/build.ps1`.
- [x] **Step 2: Compare source and deployed DLL SHA-256** and verify the final deployed assembly contains `OfflineNovelUserNamePatch`.
- [x] **Step 3: Have the user start the offline client and play `mas_1001040501`**; runtime verification was performed from the fresh client logs.
- [x] **Step 4: Read the fresh logs**; they contain the expected `NovelId` and patch-hit marker, and no new `replacement` exception.
