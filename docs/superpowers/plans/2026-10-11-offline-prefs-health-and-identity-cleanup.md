# 离线包存档健康修复与身份清理 Implementation Plan

> **For agentic workers:** 按项目子代理路由规则(`AGENTS.md`)决定派发或内联执行。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 让离线启动器在启动前把游戏**解不开的注册表设置值**隔离掉(防黑屏复发),并清掉实测无效的身份隔离与死播种。

**Architecture:** 在 `dotabyss_offline_core.py` 里加一层「纯分类 + 可注入存储」:判断某个值是不是合法 AES 密文是**纯函数**,注册表 I/O 单独一层、可用环境变量指向 JSON 假存储以便单测。身份路径改为按**真实**身份推导(不再依赖 `app.info` 改名,并对已发出去的 `_offline` 包名做归一化)。启动器在「开始游戏」前调用修复。

**Tech Stack:** Python 3.13、`winreg`、`unittest`(仓库既有风格)、tkinter 启动器。

**Spec:** 本次会话实测结论 —— `docs/离线版实现说明_开发者必读.md` §2.1 / §2.3 的「2026-10-11 实测更正」,以及用户选定的方案 C。

## Global Constraints

- 只操作 `HKCU\Software\EXNOA LLC.\ドットアビスX` 这一个键,**绝不碰**同级其它子键。
- **绝不碰** `unity` 开头的键(Unity 自己的数据)。
- 删除任何值前**必须先成功写出备份**;备份失败则**中止**,不删。
- 修复必须**幂等**:重复运行结果一致。
- 不提交(项目规则:未经用户明确要求不 commit)。
- 面向用户的文案、代码注释、docstring 一律简体中文;每个函数都要 docstring。

## Review Focus

- 值是 REG_DWORD / REG_SZ(非 bytes):应**跳过**,不得误删。
- 值是合法 base64 但长度不是 16 的倍数(明文 `AQ==` / `AAAAPw==`):必须判为**待隔离**。
- 值是合法 base64 且长度是 16 的倍数(正常密文):**不得动**。
- 键名不是十六进制(第三方写入的键):应跳过而非抛异常。
- 备份文件写不进(磁盘满 / 权限):必须**中止删除**并如实报告。
- `app.info` 已被旧版改成 `*_offline` 的老包:身份路径必须仍推导到**真实**目录。

---

### Task 1: 存档分类与健康检查(纯逻辑 + 可注入存储,只读)

**Files:**
- Modify: `tools/launcher/dotabyss_offline_core.py`(常量段后新增函数)
- Test: `tools/launcher/test_offline_core.py`(新增 `PrefsStoreTest`)

**Interfaces:**
- Produces:
  - `PREFS_COMPANY_KEY: str` = `r"Software\EXNOA LLC."`
  - `PREFS_GAME_KEY: str` = `r"Software\EXNOA LLC.\ドットアビスX"`
  - `PREFS_STORE_ENV: str` = `"DOTABYSS_PREFS_STORE_FILE"`(测试用假存储)
  - `PREFS_UNITY_PREFIX: str` = `"unity"`
  - `load_prefs_store() -> dict`(键名 → `bytes`;不可读返回 `{}` 并置 `LAST_PREFS_ERROR`)
  - `classify_prefs_value(name: str, data) -> str` → `"cipher"` / `"plain"` / `"skip"`
  - `prefs_store_health() -> tuple` → `(ok: bool, detail: str, plain_names: list)`

- [ ] **Step 1: 写失败测试**

```python
class PrefsStoreTest(unittest.TestCase):
    """存档值分类与健康检查:密文/明文/异类三态与边界。"""

    def test_cipher_needs_base64_multiple_of_16(self):
        data = base64.b64encode(bytes(32))
        self.assertEqual(core.classify_prefs_value("64", data), "cipher")

    def test_plain_short_base64_is_flagged(self):
        self.assertEqual(core.classify_prefs_value("64", b"AQ=="), "plain")
        self.assertEqual(core.classify_prefs_value("64", b"AAAAPw=="), "plain")

    def test_empty_and_non_base64_are_plain(self):
        self.assertEqual(core.classify_prefs_value("64", b""), "plain")
        self.assertEqual(core.classify_prefs_value("64", b"not base64!!"), "plain")

    def test_unity_keys_are_skipped(self):
        self.assertEqual(core.classify_prefs_value("unity.player_session_count_h1", b"AQ=="), "skip")

    def test_non_bytes_are_skipped(self):
        self.assertEqual(core.classify_prefs_value("64", 12345), "skip")
        self.assertEqual(core.classify_prefs_value("64", None), "skip")

    def test_trailing_nul_is_stripped(self):
        data = base64.b64encode(bytes(16)) + b"\x00"
        self.assertEqual(core.classify_prefs_value("64", data), "cipher")

    def test_health_reports_plain_names(self):
        # 假存储经 DOTABYSS_PREFS_STORE_FILE 注入,避免碰真实注册表
        ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `D:\Python\python.exe -m unittest test_offline_core.PrefsStoreTest -v`(在 `tools\launcher` 下)
Expected: FAIL —— `AttributeError: module 'dotabyss_offline_core' has no attribute 'classify_prefs_value'`

- [ ] **Step 3: 实现**

要点(签名与测试已定,只补不明显的部分):
- `load_prefs_store()`:先看 `os.environ.get(PREFS_STORE_ENV)` —— 有值时读 JSON `{name: hexstr}` 并返回 `{name: bytes}`;否则用 `winreg.OpenKey(HKEY_CURRENT_USER, PREFS_GAME_KEY)` + `EnumValue` 取 `(name, data, type)`,只收 `REG_BINARY`/`REG_SZ` 的原始 bytes;任何 `OSError` → 返回 `{}` 并把原因写进模块级 `LAST_PREFS_ERROR`。
- `classify_prefs_value(name, data)`:`data` 非 `bytes` → `"skip"`;`name` 以 `PREFS_UNITY_PREFIX` 开头 → `"skip"`;`data.rstrip(b"\x00")` 后 base64 严格解码(`validate=True`),解不开或长度非 16 的倍数或为 0 → `"plain"`;否则 `"cipher"`。
- `prefs_store_health()`:空存储且 `LAST_PREFS_ERROR` 非空 → `(False, "注册表不可读:…", [])`;否则按分类汇总,有 `"plain"` 即 `ok=False`。

- [ ] **Step 4: 跑测试确认通过**

Run: `D:\Python\python.exe -m unittest test_offline_core -v`
Expected: PASS(全绿)

### Task 2: 存档隔离修复(备份 + 删除)与启动器接入

**Files:**
- Modify: `tools/launcher/dotabyss_offline_core.py`(新增 `repair_prefs_store`)
- Modify: `tools/launcher/dotabyss_launcher.py`(`_ensure_local_ready` 调用;高级区新增「存档修复」按钮)
- Test: `tools/launcher/test_offline_core.py`

**Interfaces:**
- Consumes: Task 1 的 `load_prefs_store` / `classify_prefs_value` / `prefs_store_health`
- Produces: `repair_prefs_store(game_dir: str, store=None) -> list`(中文日志行;`store` 为测试注入)

- [ ] **Step 1: 写失败测试**
  - 假存储含 1 个密文 + 2 个明文 + 1 个 `unity*` → 修复后**只剩密文与 `unity*`**,备份文件存在且含被删的键与十六进制原值,返回日志含「隔离」字样。
  - 备份写不进(把备份目录指向不可写路径)→ **不删任何值**,日志含「中止」。
  - 再跑一次 → 无变化(幂等),日志含「无需修复」。

- [ ] **Step 2: 跑测试确认失败**
Run: `D:\Python\python.exe -m unittest test_offline_core.PrefsRepairTest -v` → FAIL(`has no attribute 'repair_prefs_store'`)

- [ ] **Step 3: 实现**
  - `repair_prefs_store`:先 `prefs_store_health()`;无待隔离项 → `["存档设置全部可解密,无需修复"]`;否则**先写备份** `BepInEx\prefs_backup_<stamp>.json`(内容:`{"store": "HKCU\\…", "deleted": {name: hex}}`),写失败 → `["存档修复中止:备份写入失败(…),未删除任何值"]`;成功后逐个 `winreg.DeleteValue`(假存储模式下直接改内存 dict),返回逐条日志。
  - 启动器:`_ensure_local_ready` 里在启动前调用并 `log` 结果;高级区加「存档修复」按钮调用同一函数(手动触发)。

- [ ] **Step 4: 跑测试确认通过**
Run: `D:\Python\python.exe -m unittest test_offline_core -v` → PASS

### Task 3: 身份清理(停用 app.info 改名 + 路径归一化)

**Files:**
- Modify: `tools/launcher/dotabyss_offline_core.py`(`local_low_dir`/`local_low_catalog_dirs`/`source_catalog_pair`/`safe_repair`;删除 `ensure_offline_identity`)
- Modify: `tools/launcher/dotabyss_launcher.py`(`_ensure_local_ready` 去掉身份步骤)
- Test: `tools/launcher/test_offline_core.py`(更新既有 `_offline` 相关断言)

**Interfaces:**
- Produces:
  - `REAL_COMPANY_DIR: str` = `"EXNOA LLC_"`、`REAL_PRODUCT_DIR: str` = `"ドットアビスX"`(缺 `app.info` 时的回退)
  - `real_product_name(game_dir) -> str`(读 `app.info` 产品名并 `removesuffix("_offline")`;缺失回退 `REAL_PRODUCT_DIR`)

- [ ] **Step 1: 写失败测试**
  - `app.info` 产品名 `ドットアビスX_offline` → `local_low_dir` 仍指向 `…\EXNOA LLC_\ドットアビスX`(归一化)。
  - `app.info` 缺失 → 回退常量,路径为 `…\EXNOA LLC_\ドットアビスX`。
  - `safe_repair` 后 `app.info` **内容不变**(不再改名)。
  - `local_low_catalog_dirs` 不再把 `_offline` 目录排在前。

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**
  - `local_low_dir` 用 `real_product_name()` + `REAL_COMPANY_DIR`;`local_low_catalog_dirs` 只返回真实目录;`source_catalog_pair` 同样只认真实目录。
  - 删除 `ensure_offline_identity` 及 `safe_repair` / `_ensure_local_ready` 里的调用;`IDENTITY_SUFFIX` 仅保留给归一化使用。
  - 更新既有测试中断言「改名为 `_offline`」的用例。

- [ ] **Step 4: 跑测试确认通过** → `test_offline_core` + `test_launcher_layout` 全绿

### Task 4: 打包不再改 app.info,并还原现有包

**Files:**
- Modify: `tools/launcher/build_full_pack.py`(去掉改名与「删备份」步骤)
- Data: `client\ドットアビスX_Data\app.info`、`dist\ドットアビスX离线版\ドットアビスX_Data\app.info`(还原为 `ドットアビスX`)
- Test: `tools/launcher/test_pack_tools.py`

- [ ] **Step 1: 写失败测试**:打包元数据/清单校验里断言 `app.info` 产品名**保持原样**(无 `_offline` 后缀)。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现**:`build_full_pack.py` 不再调用改名逻辑、不再把 `app.info.bak_original` 列入排除;用 `.bak_original`(若存在)或直接写回 `ドットアビスX` 还原两处 `app.info`;备份文件按需删除。
- [ ] **Step 4: 跑测试确认通过** → `test_pack_tools` 全绿;并 `Get-Content` 复核两处 `app.info` 第二行为 `ドットアビスX`。

### Task 5: 文档收尾

**Files:**
- Modify: `docs\离线版实现说明_开发者必读.md`(§2.1 / §2.2 去掉「待办未决」改为「已按方案 C 处理」;新增存档修复小节)
- Modify: `README.md`、`docs\日常更新流程.md`(第 20/92/96/102/109/248 行)、`docs\GitHub更新流程.md`(第 141 行)
- Modify: `docs\日常更新流程.md`(测试计数)

- [ ] **Step 1**:把 §2.1 的「待办(未决)」改为「2026-10-11 按方案 C 落地:不做真隔离,改为启动前隔离不可解密值 + 清掉无效改名」,并写明后果与恢复方式。
- [ ] **Step 2**:更新所有把 `_offline` 当作有效隔离的描述(逐处改为「真实身份目录」)。
- [ ] **Step 3**:复核 §2.3 / §2.4 与实现一致;更新测试计数。
- [ ] **Step 4**:通读改后文档,确认没有残留「已隔离 / 互不干扰 / 完全分开」的说法。
