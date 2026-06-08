# Desktop Cleaner

Desktop Cleaner 是一个 Windows 桌面入口面板与整理工具。它把桌面上的文件、文件夹、快捷方式和外部路径引用显示在半透明分组面板里，方便分类、查看和启动。

当前版本只管理入口引用：不移动、不复制、不删除源文件。

## 功能

- 默认分类：文件夹、文档、图片、压缩包、应用、其它
- 面板可移动、锁定、收起、边缘缩放、磁吸和多屏切换
- 标签可新建、删除、重命名、切换、拖出和合并
- 拖入任意文件或文件夹时只保存应用内虚拟引用
- 桌面新增项目会先进入“其它”，点击“一键整理”后按规则重新分类
- 双击项目用系统默认程序打开，右键尽量调用 Windows 原生菜单
- 优先使用 Windows Shell 图标，图片显示缩略图，快捷方式图标有缓存和 fallback
- 文件名隐藏常见后缀，长名称自动省略
- `Ctrl + 鼠标滚轮` 调整当前面板图标大小
- 支持桌面接管：启用后隐藏 Explorer 原生桌面图标，退出或关闭接管时恢复
- 支持系统托盘菜单、开机启动和单实例运行
- 支持面板历史，可恢复之前的布局、标签和外观
- 支持全局唯一主标签页：包含时间概览、Windows 最近使用、本地日程提醒、网络收藏、月历和天气模块
- 支持内置功能面板架构，当前内置独立“时间”面板
- 可打包为无控制台单文件 Windows exe

## 安全边界

- 不移动、不复制、不删除源文件
- 从桌面外拖入的项目只保存为虚拟引用，不会创建快捷方式或写入真实桌面
- “一键整理”只改变应用内分类，不改变磁盘上的文件位置
- 面板历史只保存应用布局和元数据，不保存真实桌面文件清单
- 日志只写入本机 `%LOCALAPPDATA%\DesktopCleaner\logs\`
- 主标签页的“最近使用”只读取 Windows Recent 快捷方式和本应用打开记录，不扫描浏览器历史或系统隐私数据库
- 桌面接管失败时会降级为普通窗口；退出、关闭接管或下次启动恢复流程会尝试恢复 Explorer 桌面图标
- 仓库不包含壁纸、AI、云同步、账号登录或真实文件归档功能

## 运行

```bash
pip install -r requirements.txt
python main.py
```

配置与本地数据保存位置：

```text
%LOCALAPPDATA%\DesktopCleaner\config.json
%LOCALAPPDATA%\DesktopCleaner\layout-history.json
%LOCALAPPDATA%\DesktopCleaner\logs\desktop-cleaner.log
```

## 打包 exe

```bash
pip install -r requirements-build.txt
scripts\build_exe.bat
```

输出文件：

```text
dist\DesktopCleaner.exe
```

## 项目结构

```text
desktop_tidy/
  application.py              Qt 应用生命周期、面板、托盘和桌面接管协调
  domain/                     配置模型、分类规则和工作区状态
  persistence/                配置迁移、配置读写和面板历史
  services/                   桌面索引、图标、日志、右键菜单、启动项和 Windows 集成
  ui/                         面板、项目网格、设置窗口、托盘和内置功能面板
main.py                       应用入口
scripts/build_exe.bat         Windows 单文件 exe 打包脚本
tests/                        单元测试和 Qt 离屏测试
```

## 使用提示

- 第一次启用桌面接管时会弹出确认提示
- 程序隐藏后可以从系统托盘重新显示面板、打开设置、恢复桌面图标或退出
- 如果重复启动 exe，新进程会通知已有实例显示面板，然后直接退出
- 修改布局前后可在设置中心的“面板历史”里恢复到近期状态
