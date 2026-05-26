# Desktop Cleaner

Desktop Cleaner 是一个 Windows 桌面入口面板工具。它把桌面上的文件、文件夹、快捷方式和外部路径引用显示在半透明分组面板里，方便分类和启动。

当前版本只管理入口引用，不移动、不复制、不删除源文件。

## 功能

- 默认分组：文件夹、文档、图片、压缩包、应用、其它
- 面板可移动、锁定、收起、边缘缩放和磁吸
- 标签可新建、删除、重命名、切换、拖出和合并
- 支持拖入任意文件或文件夹作为虚拟引用
- 双击项目用系统默认程序打开
- 支持 Windows 原生图标和图片缩略图
- 文件名隐藏常见后缀，长名称自动省略
- `Ctrl + 鼠标滚轮` 调整当前面板图标大小
- 一键整理会按规则重新分类当前桌面入口，不改动源文件
- 设置中心支持桌面路径、面板外观和分类规则

## 运行

```bash
pip install -r requirements.txt
python main.py
```

配置保存在：

```text
%LOCALAPPDATA%\DesktopCleaner\config.json
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
  application.py              Qt 应用生命周期和面板协调
  domain/                     配置模型、分类规则和工作区状态
  persistence/                配置读写与迁移
  services/                   桌面索引、图标、打开项目、右键菜单、屏幕信息
  ui/                         面板、项目网格和设置窗口
main.py                       应用入口
scripts/build_exe.bat         Windows 单文件 exe 打包脚本
tests/                        单元测试和 Qt 离屏测试
```

## 注意

- 当前版本不会接管 Windows 桌面层，也不会隐藏 Explorer 原生桌面图标。
- 右键菜单会尽量调用 Windows 原生菜单；如果系统菜单不可用，则只保留选中反馈。
- 仓库不包含壁纸、AI、云同步、账号登录或真实文件归档功能。
