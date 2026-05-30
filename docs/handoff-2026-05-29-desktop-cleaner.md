# DesktopCleaner 项目交接文档

日期：2026-05-29
项目路径：`D:\code\tool`
GitHub 正式仓库：`https://github.com/Dmosen-Chen/desktop-cleaner`
当前版本：`1.0.18`

## 当前状态

- 当前分支：`main`
- 当前工作区：准备发布今日版本
- 最新提交：发布后以 `main` 最新提交为准
- 最新 Release：`v1.0.18`
- Release 页面：`https://github.com/Dmosen-Chen/desktop-cleaner/releases/tag/v1.0.18`
- Release 附件：`DesktopCleaner.exe`
- 本地 exe：`D:\code\tool\dist\DesktopCleaner.exe`

## 产品定位

DesktopCleaner 是一个 Windows 桌面入口面板工具：

- 管理桌面入口、快捷方式、文件夹、文档、图片、压缩包、应用等分类显示。
- 支持透明桌面面板、标签组、功能面板、桌面接管、托盘常驻、单实例、半自动更新。
- 核心安全边界：不移动、不复制、不删除真实文件。分类只是显示归属和虚拟引用。

不要再使用“小智桌面”相关命名、资源或描述。公开仓库保持独立品牌 `DesktopCleaner`。

## 用户偏好和协作约定

- 用户倾向中文沟通。
- 用户现在更希望 Codex 自己改代码，不要默认委派 Cursor 或 Claude。
- 除非用户明确说“推送 GitHub”或“上传”，否则不要自动 push。
- 做大改动前先说明方案；设置中心 UI 这类设计问题可以先用 HTML 视觉稿对齐。
- 用户很在意桌面图标恢复安全，任何构建、接管相关操作都要优先避免 Explorer 桌面图标卡住或隐藏不恢复。

## 重要已实现能力

### 核心面板

- PySide6 重构完成，`main.py` 已是正式 Qt 入口。
- 面板支持：
  - 标签切换、重命名、新建、删除。
  - 拖动、边缘缩放、磁吸。
  - 锁定、收起。
  - 文件/文件夹/快捷方式双击打开。
  - Windows Shell 图标和缩略图。
  - 右键尽量走 Windows 原生 Shell 菜单。
  - `Ctrl + 滚轮` 调整图标大小。

### 分类规则

- 旧“桌面整理”已经语义调整为“分类规则”。
- 含默认规则：文件夹、文档、图片、压缩包、应用、其它。
- 支持自定义类型：创建同名标签和分类规则。
- 删除自定义类型只删除规则，不删除标签，也不影响真实文件。
- 其它规则作为兜底，新出现且未命中规则的桌面项目进入“其它”。

### 桌面接管

- 桌面接管默认关闭。
- 启用后会尝试挂载到桌面层并隐藏 Explorer 原桌面图标。
- 退出、禁用接管、异常恢复时会尝试恢复 Explorer 图标。
- 有构建前恢复保护脚本，避免开发构建时桌面图标残留隐藏。

### 设置中心

当前设置中心仍在多轮打磨中，现状包括：

- 左侧页面：面板、分类规则、面板历史、功能面板、诊断与恢复、其他。
- “基础设置”已并入“其他”。
- 面板页合并了面板管理和外观控制。
- 面板历史保留最近 10 条，并支持 5 分钟内同类布局变化合并。
- 诊断与恢复页可导出诊断包、恢复桌面图标、查看日志。
- 其他页包含桌面路径、接管、开机自启、软件更新、恢复工具等。

### 功能面板

- 功能面板已模块化到 `desktop_tidy/widgets/`。
- 当前内置 `clock` 时间面板。
- `WidgetDefinition` / `WidgetVisualPreset` 用于后续天气、待办、日历等功能面板扩展。
- 最近用户要求把时间面板视觉“改回去”：现在时间面板恢复为稳定的透明桌面大文字样式，不再显示紫色卡片。

### 半自动更新

- 更新源：GitHub Releases latest API。
- 当前仓库：`Dmosen-Chen/desktop-cleaner`
- 当前版本常量：`desktop_tidy/version.py`
- 设置中心“其他”页有软件更新分组：
  - 检查更新
  - 下载更新
  - 打开更新文件夹
  - 打包 exe 模式下替换并重启
- 更新下载目录：`%LOCALAPPDATA%\DesktopCleaner\updates\`

## 重要路径

- 主入口：`D:\code\tool\main.py`
- 应用协调层：`D:\code\tool\desktop_tidy\application.py`
- 设置中心：`D:\code\tool\desktop_tidy\ui\settings_window.py`
- 桌面面板：`D:\code\tool\desktop_tidy\ui\panel_group.py`
- 功能面板模块：`D:\code\tool\desktop_tidy\widgets\`
- 更新服务：`D:\code\tool\desktop_tidy\services\updates.py`
- 版本常量：`D:\code\tool\desktop_tidy\version.py`
- 构建脚本：`D:\code\tool\scripts\build_exe.bat`
- 构建保护脚本：`D:\code\tool\scripts\prepare_build.py`
- 本地配置目录：`%LOCALAPPDATA%\DesktopCleaner\`
- 日志目录：`%LOCALAPPDATA%\DesktopCleaner\logs\`

## 设计文档和视觉稿

- UI 规则：`D:\code\tool\docs\design\desktop-cleaner-ui-rules.md`
- 设置 dashboard 视觉稿：`D:\code\tool\docs\design\v1.0.8-settings-dashboard-mockup.html`
- 设置重设计视觉稿：`D:\code\tool\docs\design\v1.0.14-settings-redesign-mockup.html`
- 磨砂控制台视觉稿：`D:\code\tool\docs\design\v1.0.16-settings-frosted-console-mockup.html`

注意：用户对设置中心视觉还没有完全满意。最近的方向是不要整窗过透明，因为会看不清；但用户仍希望“能看到后面变化”的透明感。普通文件入口面板不要重做，主要改设置中心和时间功能面板。

## 最近已验证命令

全量测试：

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -B -m unittest discover -s tests -p 'test_*.py' -v
```

最近结果：`318 tests OK`

格式检查：

```powershell
git diff --check
```

最近结果：通过，只有 LF/CRLF 警告。

构建 exe：

```powershell
scripts\build_exe.bat
```

构建脚本会先恢复桌面图标并停止旧的 `DesktopCleaner.exe` 实例。

## 最近发布记录

`v1.0.18` 发布目标：

- 提交：以今日发布提交为准
- 标签：`v1.0.18`
- Release：`https://github.com/Dmosen-Chen/desktop-cleaner/releases/tag/v1.0.18`
- 附件：`DesktopCleaner.exe`
- 版本常量已升到 `APP_VERSION = "1.0.18"`

## 当前用户刚提出的新问题

用户发现：

> 开机自启动的时候好像很慢。

这还没有开始诊断。下一轮建议先用系统化调试，不要直接猜修：

1. 确认开机启动注册项实际指向的是哪个 exe。
2. 看 `%LOCALAPPDATA%\DesktopCleaner\logs\desktop-cleaner.log` 里启动阶段耗时或错误。
3. 区分慢在哪里：
   - 单文件 PyInstaller 解包慢。
   - 首次桌面索引扫描慢。
   - Shell 图标提取慢。
   - 桌面接管恢复/隐藏图标慢。
   - 开机时 Explorer / Shell 尚未准备好导致重试。
4. 加启动阶段打点日志：
   - 进程启动
   - 配置加载
   - 恢复 guard
   - 桌面索引
   - 面板创建
   - 图标加载
   - 桌面接管
   - 托盘初始化
5. 再决定是否做延迟加载、图标懒加载、启动后延迟接管或拆成 onedir 构建。

推荐下一轮使用技能：

- `systematic-debugging`：定位开机自启慢的真实瓶颈。
- `test-driven-development`：给启动计时/日志服务补测试。
- `verification-before-completion`：修完后再声明完成。

## 可能的下一步优化方向

### 开机启动性能

优先级最高。建议新增 `StartupProfiler` 或轻量启动打点，写日志但不影响用户。

可能优化：

- 启动先显示托盘和空面板，再异步加载图标。
- 桌面索引和图标提取分阶段。
- 接管延迟几秒等待 Explorer 稳定。
- Shell 图标缓存更积极。
- 单文件 exe 启动慢如果明显，可考虑同时提供 onedir 版本。

### 设置中心视觉

仍未完全定稿。用户喜欢透明感，但不能看不清。建议方案：

- 窗口外壳 92%-96% 不透明。
- 卡片 96%-98% 不透明。
- 只在边缘、标题栏、预览区做轻透明。
- 文字和控件永远不透明。

### 面板历史

用户希望：

- 预览能看出面板位置、颜色、透明度变化。
- 同类变化 5 分钟内合并，不要每拖一下就一条。
- 卡片随窗口宽度变成 1/2/3 列。

相关代码和测试已经存在，但如有 UI 不满意，继续改 `settings_window.py` 和预览组件。

### 功能面板

当前只有时间。后续可加：

- 天气
- 待办
- 日历
- 快捷状态卡

应放在 `desktop_tidy/widgets/`，通过 registry 注册，不要在设置页硬编码。

## 风险提醒

- 不要把 `dist\DesktopCleaner.exe` 直接加入 Git；它应只作为 GitHub Release 附件。
- 不要自动推送 GitHub，除非用户明确要求。
- 涉及桌面接管、构建、启动项时要注意 Explorer 图标恢复。
- 右键菜单如果改动，务必避免误触真实删除/移动行为。
- 分类规则永远不能移动、复制、删除真实文件。
