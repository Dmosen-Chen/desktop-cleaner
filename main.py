"""

简洁桌面整理：按后缀规则整理桌面文件；可选系统托盘、开机启动、桌面分区悬浮窗。

依赖：Python 3.10+、tkinter；托盘需 pystray、pillow；直接拖入面板为 windnd 实验功能。



运行：python main.py

"""



from __future__ import annotations


import json

import os

import sys

import uuid

import webbrowser

from copy import deepcopy

from pathlib import Path

from tkinter import END, colorchooser, filedialog, messagebox, scrolledtext, simpledialog, ttk

import tkinter as tk



from organizer import (

    default_config_path,

    desktop_dir,

    ensure_extension_key,

    load_config,

    resolve_archive_root,

    save_config,

    undo_last_batch,

    undo_log_path,

)

from partition_overlay import (
    DEFAULT_PARTITIONS,
    DEFAULT_PANEL_ALPHA,
    DEFAULT_PANEL_COLOR,
    DROP_AVAILABLE,
    PartitionOverlay,
    make_item_from_path,
    normalize_extensions,
    normalize_partition_list,
    normalize_items,
)

from tray_support import start_tray, tray_supported

from windows_native import is_startup_enabled, set_startup_enabled





def _bundle_root() -> Path:

    if getattr(sys, "frozen", False):

        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

    return Path(__file__).resolve().parent





def merge_default_rules(cfg: dict) -> dict:

    default_path = _bundle_root() / "config.default.json"

    if not default_path.is_file():

        return cfg

    with default_path.open(encoding="utf-8") as f:

        base = json.load(f)

    rules = dict(base.get("rules") or {})

    rules.update(cfg.get("rules") or {})

    out = dict(cfg)

    out["rules"] = rules

    if not (out.get("archive_root") or "").strip():

        out["archive_root"] = base.get("archive_root") or ""

    if not (out.get("desktop") or "").strip():

        out["desktop"] = base.get("desktop") or str(desktop_dir({}))

    return out





DEFAULT_DOC_EXTS = (
    ".txt .pdf .doc .docx .ppt .pptx .xls .xlsx .csv .wps .xml .rtf .wtf "
    ".dot .dotm .xps .htm .html .mht .mhtml .odt .xlsb .xltx .xltm .xlt "
    ".prn .dif .slk .xlam .xla .ods .pptm .pot .potm .potx .ppsx .pps "
    ".ppsm .ppam .thmx .ppa .xmsl .xlsm .md"
)
DEFAULT_PIC_EXTS = (
    ".img .jpg .jpeg .png .psd .gif .webp .bmp .svg .ai .tif .tiff .dib "
    ".eps .raw .pxr .mac .tga .vst .pcd .pct .fpx .cal .wi .ico .cr2 "
    ".crw .cur .ani .psb .sai"
)
DEFAULT_ZIP_EXTS = (
    ".zip .rar .7z .dmg .gz .001 .a .apm .ar .arj .bz2 .bzip2 .cab "
    ".cpio .cramfs .deb .epub .esd .ext .ext2 .ext3 .ext4 .gpt .zipx "
    ".gzip .hfs .hfsx .hxi .hxq .hxr .hxs .hxw .ihex .iso .jar .lha "
    ".lib .lit .lzh .lzma .lzma86 .ova .pkg .pmd .qcow .qcow2 .qcow2c "
    ".r00 .scap .squashfs .swm .tar .taz .tbz .tbz2 .txz .uefif .vdi "
    ".vmdk .wim .xar .xip .xpi .xz .z .z01"
)
DEFAULT_AUDIO_EXTS = (
    ".mp3 .midi .wma .cd .amr .au .cda .wav .wave .aiff .mpeg .mp3pro "
    ".mpeg-4 .realaudio .vqf .ogg .oggvorbis .ape .flac .aac .ra .mod"
)
DEFAULT_VIDEO_EXTS = (
    ".mp4 .avi .mov .flv .mod .m4v .rm .ram .rmvb .3gp .mpeg .mpg .asf "
    ".wmv .navi .realvideo .mkv .f4v .dat .divx .dv .vob .qt .cpk .fli"
)


COLLECT_RULE_PRESETS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("文件夹", "folder", "", ("文件夹",)),
    ("压缩包", "extension", DEFAULT_ZIP_EXTS, ("压缩包",)),
    ("文档", "extension", DEFAULT_DOC_EXTS, ("文档",)),
    ("图片", "extension", DEFAULT_PIC_EXTS, ("图片",)),
    ("快捷方式", "extension", ".lnk", ("电脑", "工具")),
    ("网页链接", "extension", ".url", ("电脑", "工具")),
    ("音频", "extension", DEFAULT_AUDIO_EXTS, ("音频", "图片")),
    ("视频", "extension", DEFAULT_VIDEO_EXTS, ("视频", "图片")),
    ("其它", "other", "", ("draft", "其它")),
]


def _workspace_id_by_names(partitions: list[dict[str, object]], names: tuple[str, ...]) -> str:
    wanted = {name.casefold() for name in names}
    for part in partitions:
        name = str(part.get("name") or "").strip().casefold()
        folder = str(part.get("folder") or "").strip().casefold()
        if name in wanted or folder in wanted:
            return str(part.get("id") or "")
    return ""


def _default_collect_rules(partitions: list[dict[str, object]]) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    for label, kind, ext_text, target_names in COLLECT_RULE_PRESETS:
        target_id = _workspace_id_by_names(partitions, target_names)
        rules.append(
            {
                "id": uuid.uuid4().hex,
                "type": label,
                "kind": kind,
                "exts": normalize_extensions(ext_text),
                "target_id": target_id,
                "enabled": bool(target_id) and kind != "other",
            }
        )
    return rules


def normalize_collect_rules(value: object, partitions: list[dict[str, object]]) -> list[dict[str, object]]:
    target_ids = {str(part.get("id")) for part in partitions}
    raw_rules: list[dict[str, object]] = []

    if isinstance(value, list):
        raw_rules = [dict(item) for item in value if isinstance(item, dict)]
        if not raw_rules:
            return []
    else:
        for part in partitions:
            exts = normalize_extensions(part.get("match_exts"))
            if not exts:
                continue
            raw_rules.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": str(part.get("name") or "自定义"),
                    "kind": "extension",
                    "exts": exts,
                    "target_id": str(part.get("id") or ""),
                    "enabled": True,
                }
            )
        if not raw_rules:
            return _default_collect_rules(partitions)

    normalized: list[dict[str, object]] = []
    for item in raw_rules:
        kind = str(item.get("kind") or "extension")
        if kind not in {"extension", "folder", "other"}:
            kind = "extension"
        target_id = str(item.get("target_id") or item.get("target") or "")
        if target_id not in target_ids:
            target_id = ""
        normalized.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "type": str(item.get("type") or item.get("name") or "自定义"),
                "kind": kind,
                "exts": normalize_extensions(item.get("exts")),
                "target_id": target_id,
                "enabled": bool(item.get("enabled", False)) and bool(target_id),
            }
        )
    return normalized


def merge_ui(cfg: dict) -> dict:

    out = dict(cfg)

    ui = dict(out.get("ui") or {})

    if not ui.get("partitions"):

        ui["partitions"] = deepcopy(DEFAULT_PARTITIONS)

    ui["partitions"] = normalize_partition_list(ui["partitions"])

    if "minimize_to_tray" not in ui:

        ui["minimize_to_tray"] = True

    if "overlay_visible" not in ui:

        ui["overlay_visible"] = False

    ui["collect_rules"] = normalize_collect_rules(ui.get("collect_rules"), ui["partitions"])

    ui["startup_enabled"] = is_startup_enabled()

    out["ui"] = ui

    return out





class App(tk.Tk):

    def __init__(self) -> None:

        super().__init__()

        self.title("桌面整理（简洁版）")

        self.minsize(520, 420)

        self.geometry("720x560")



        self.config_path = default_config_path()

        raw = load_config(self.config_path)

        self.cfg = merge_ui(merge_default_rules(raw))



        ui = self.cfg.get("ui") or {}

        self.var_minimize_tray = tk.BooleanVar(value=bool(ui.get("minimize_to_tray", True)))

        self.var_overlay = tk.BooleanVar(value=bool(ui.get("overlay_visible", False)))

        self.var_edit_overlay = tk.BooleanVar(value=False)

        self.var_startup = tk.BooleanVar(value=is_startup_enabled())

        self.desktop_var = tk.StringVar(value=str(desktop_dir(self.cfg)))



        parts = list(ui.get("partitions") or deepcopy(DEFAULT_PARTITIONS))

        self.overlay = PartitionOverlay(
            self,
            parts,
            on_drop=self._on_partition_drop,
            on_open_item=self._open_workspace_item,
            on_remove_item=self._remove_workspace_item,
            on_workspace_action=self._on_workspace_action,
            on_layout_change=self._on_workspace_layout_change,
        )



        self.tray_icon = None



        self._build()

        self._refresh_rules_ui()



        self.protocol("WM_DELETE_WINDOW", self._on_close)



        if tray_supported():

            self.tray_icon = start_tray(

                title="桌面整理",

                on_open=lambda: self.after(0, self._show_main_window),

                on_organize=lambda: self.after(0, self._run_organize),

                on_toggle_overlay=lambda: self.after(0, self._tray_toggle_overlay),

                on_toggle_startup=lambda: self.after(0, self._tray_toggle_startup),

                on_quit=lambda: self.after(0, self._quit_app),

                overlay_checked=lambda: self.var_overlay.get(),

                startup_checked=lambda: self.var_startup.get(),

            )

        else:

            self.after(

                100,

                lambda: self._log_line(

                    "提示：安装 pystray 与 Pillow 后可使用系统托盘：pip install pystray pillow"

                ),

            )

        if not DROP_AVAILABLE:

            self.after(120, lambda: self._log_line("提示：直接拖入面板已默认关闭以避免 windnd 崩溃；请用面板 ... 里的「添加文件/添加文件夹」。"))



        if self.var_overlay.get():

            self.after(300, self._sync_overlay_from_var)



    def _build(self) -> None:

        top = ttk.Frame(self, padding=8)

        top.pack(fill=tk.X)



        ttk.Label(top, text="归档根目录（整理后的文件放这里）:").pack(anchor=tk.W)

        row = ttk.Frame(top)

        row.pack(fill=tk.X, pady=(0, 6))

        self.archive_var = tk.StringVar(value=self._archive_display())

        entry = ttk.Entry(row, textvariable=self.archive_var)

        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(row, text="浏览…", command=self._pick_archive).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(row, text="打开文件夹", command=self._open_archive).pack(side=tk.LEFT, padx=(6, 0))



        ttk.Label(top, text="桌面路径（面板入口和一键整理使用这里）:").pack(anchor=tk.W, pady=(4, 0))

        desktop_row = ttk.Frame(top)

        desktop_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Entry(desktop_row, textvariable=self.desktop_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(desktop_row, text="浏览…", command=self._pick_desktop).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(desktop_row, text="打开桌面", command=self._open_desktop).pack(side=tk.LEFT, padx=(6, 0))



        extra = ttk.LabelFrame(top, text="托盘与桌面分区（B3 / B4）", padding=8)

        extra.pack(fill=tk.X, pady=(8, 0))



        tray_tip = (

            "关闭窗口时最小化到托盘"

            if tray_supported()

            else "关闭窗口时最小化到托盘（需安装 pystray、pillow）"

        )

        self.chk_tray = ttk.Checkbutton(

            extra,

            text=tray_tip,

            variable=self.var_minimize_tray,

            command=self._persist_ui_only,

        )

        self.chk_tray.pack(anchor=tk.W)

        if not tray_supported():

            self.chk_tray.state(["disabled"])



        ttk.Checkbutton(

            extra,

            text="开机自动启动（当前用户启动文件夹）",

            variable=self.var_startup,

            command=self._apply_startup_choice,

        ).pack(anchor=tk.W, pady=(4, 0))



        row_o = ttk.Frame(extra)

        row_o.pack(fill=tk.X, pady=(4, 0))

        ttk.Checkbutton(

            row_o,

            text="显示桌面工作区（从面板 ... 添加入口，不移动源文件）",

            variable=self.var_overlay,

            command=self._on_overlay_toggle,

        ).pack(side=tk.LEFT)

        ttk.Checkbutton(

            row_o,

            text="编辑工作区",

            variable=self.var_edit_overlay,

            command=self._on_workspace_edit_toggle,

        ).pack(side=tk.LEFT, padx=(12, 0))

        ttk.Button(row_o, text="刷新分区位置", command=self._refresh_overlay_layout).pack(

            side=tk.LEFT, padx=(12, 0)

        )

        ttk.Button(row_o, text="管理工作区", command=self._manage_workspaces).pack(

            side=tk.LEFT, padx=(12, 0)

        )
        ttk.Button(row_o, text="设置中心", command=self._open_settings_center).pack(

            side=tk.LEFT, padx=(12, 0)

        )



        mid = ttk.Frame(self, padding=(8, 0))

        mid.pack(fill=tk.BOTH, expand=True)



        left = ttk.LabelFrame(mid, text="整理规则（设置中心）", padding=6)

        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



        cols = ("ext", "folder")

        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=11)

        self.tree.heading("ext", text="类型 / 后缀")

        self.tree.heading("folder", text="目标面板 / 状态")

        self.tree.column("ext", width=120, anchor=tk.W)

        self.tree.column("folder", width=220, anchor=tk.W)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



        sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)

        self.tree.configure(yscrollcommand=sb.set)

        sb.pack(side=tk.RIGHT, fill=tk.Y)



        btn_col = ttk.Frame(mid, padding=(8, 0))

        btn_col.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Button(btn_col, text="打开设置中心", command=self._open_settings_center).pack(fill=tk.X, pady=(0, 6))

        ttk.Button(btn_col, text="刷新规则", command=self._refresh_rules_ui).pack(fill=tk.X, pady=(0, 6))

        ttk.Separator(btn_col, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Button(btn_col, text="保存配置", command=self._save_cfg).pack(fill=tk.X, pady=(0, 6))



        bottom = ttk.Frame(self, padding=8)

        bottom.pack(fill=tk.BOTH)



        action_row = ttk.Frame(bottom)

        action_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(action_row, text="预览整理", command=self._preview_organize).pack(side=tk.LEFT)

        ttk.Button(action_row, text="一键整理桌面", command=self._run_organize).pack(side=tk.LEFT)

        ttk.Button(action_row, text="撤销上一次整理", command=self._run_undo).pack(side=tk.LEFT, padx=(8, 0))



        self.log = scrolledtext.ScrolledText(bottom, height=9, wrap=tk.WORD)

        self.log.pack(fill=tk.BOTH, expand=True)



        self._log_line(f"配置文件: {self.config_path}")



    def _archive_display(self) -> str:

        root = resolve_archive_root(self.cfg)

        return str(root)



    def _persist_ui_only(self) -> None:

        self.cfg.setdefault("ui", {})

        self.cfg["ui"]["minimize_to_tray"] = self.var_minimize_tray.get()

        self.cfg["ui"]["overlay_visible"] = self.var_overlay.get()

        self.cfg["ui"]["startup_enabled"] = self.var_startup.get()

        self.cfg["ui"]["partitions"] = list(self.overlay.partitions)

        if "desktop_var" in self.__dict__:

            self.cfg["desktop"] = self.desktop_var.get().strip()

        save_config(self.config_path, self.cfg)



    def _save_workspaces(self, partitions: list[dict[str, object]]) -> None:

        normalized = normalize_partition_list(partitions)

        self.cfg.setdefault("ui", {})

        self.cfg["ui"]["partitions"] = normalized
        self.cfg["ui"]["collect_rules"] = normalize_collect_rules(self.cfg["ui"].get("collect_rules"), normalized)

        self.overlay.set_partitions(normalized)

        save_config(self.config_path, self.cfg)



    def _sync_overlay_from_var(self) -> None:

        if self.var_overlay.get():

            self.overlay.set_partitions(self.cfg.get("ui", {}).get("partitions") or DEFAULT_PARTITIONS)

            self.overlay.show()



    def _on_overlay_toggle(self) -> None:

        self.cfg.setdefault("ui", {})

        self.cfg["ui"]["overlay_visible"] = self.var_overlay.get()

        self.overlay.set_partitions(self.cfg["ui"].get("partitions") or DEFAULT_PARTITIONS)

        if self.var_overlay.get():

            self.overlay.show()

        else:

            self.overlay.hide()

        self._persist_ui_only()



    def _on_workspace_edit_toggle(self) -> None:

        if self.var_edit_overlay.get() and not self.var_overlay.get():

            self.var_overlay.set(True)

        self.overlay.set_partitions(self.cfg.get("ui", {}).get("partitions") or DEFAULT_PARTITIONS)

        self.overlay.set_edit_mode(self.var_edit_overlay.get())

        if self.var_overlay.get() and not self.overlay.visible():

            self.overlay.show()

        self._persist_ui_only()

        mode = "编辑模式：拖动工作区可移动，靠近边缘会吸附，松开后自动保存。" if self.var_edit_overlay.get() else "已退出工作区编辑模式。"

        self._log_line(mode)



    def _on_workspace_layout_change(self, partitions: list[dict[str, object]]) -> None:

        self._save_workspaces(partitions)

        self._log_line("工作区位置已保存。")



    def _refresh_overlay_layout(self) -> None:

        if not self.var_overlay.get():

            self._log_line("请先勾选「显示桌面工作区」。")

            return

        self.overlay.set_partitions(self.cfg.get("ui", {}).get("partitions") or DEFAULT_PARTITIONS)

        self.overlay.hide()

        self.overlay.show()

        self._log_line("已按当前屏幕工作区刷新分区位置。")



    def _sync_workspaces(self, partitions: list[dict[str, object]]) -> None:

        self._save_workspaces(partitions)

        if self.var_overlay.get():

            self.overlay.show()



    def _new_workspace_template(self, name: str) -> dict[str, object]:

        count = len(self.overlay.partitions)

        col = count % 3

        row = (count // 3) % 3

        return {

            "id": uuid.uuid4().hex,

            "name": name,

            "folder": name,

            "rx": round(0.05 + col * 0.28, 4),

            "ry": round(0.08 + row * 0.24, 4),

            "rw": 0.24,

            "rh": 0.18,

            "color": DEFAULT_PANEL_COLOR,

            "alpha": DEFAULT_PANEL_ALPHA,

            "locked": False,

            "collapsed": False,

            "match_exts": [],

        }



    def _find_workspace_index(self, workspace_id: str) -> int | None:

        for idx, part in enumerate(self.overlay.partitions):

            if str(part.get("id")) == workspace_id:

                return idx

        return None


    def _workspace_group_indexes(self, workspace_id: str) -> list[int]:

        idx = self._find_workspace_index(workspace_id)

        if idx is None:

            return []

        group_key = self.overlay._group_key(self.overlay.partitions[idx])

        return [i for i, part in enumerate(self.overlay.partitions) if self.overlay._group_key(part) == group_key]


    def _safe_desktop_entry_name(self, name: str) -> str:

        invalid = '<>:"/\\|?*'

        cleaned = "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in name).strip(" .")

        return cleaned or "入口"


    def _is_inside_desktop(self, path: Path, desktop: Path) -> bool:

        try:

            child = os.path.normcase(str(path.resolve()))

            parent = os.path.normcase(str(desktop.resolve()))

            return os.path.commonpath([child, parent]) == parent

        except Exception:

            return False


    def _unique_desktop_shortcut_path(self, source: Path) -> Path:

        self.cfg["desktop"] = self.desktop_var.get().strip() if "desktop_var" in self.__dict__ else self.cfg.get("desktop", "")

        desktop = desktop_dir(self.cfg)

        desktop.mkdir(parents=True, exist_ok=True)

        stem = self._safe_desktop_entry_name(source.stem if source.suffix else source.name)

        candidate = desktop / f"{stem}.url"

        counter = 2

        while candidate.exists():

            candidate = desktop / f"{stem} ({counter}).url"

            counter += 1

        return candidate


    def _desktop_entry_for_drop(self, source: Path) -> Path:

        self.cfg["desktop"] = self.desktop_var.get().strip() if "desktop_var" in self.__dict__ else self.cfg.get("desktop", "")

        desktop = desktop_dir(self.cfg)

        if self._is_inside_desktop(source, desktop):

            return source

        shortcut = self._unique_desktop_shortcut_path(source)

        shortcut.write_text(f"[InternetShortcut]\nURL={source.as_uri()}\n", encoding="utf-8")

        return shortcut



    def _add_workspace(self, parent: tk.Misc | None = None) -> None:

        parts = list(self.overlay.partitions)

        name = f"新建面板 {len(parts) + 1}"

        workspace = self._new_workspace_template(name)

        parts.append(workspace)

        self._sync_workspaces(parts)

        self.overlay.request_inline_rename(str(workspace["id"]))

        self._log_line(f"已新建面板：{name}")



    def _rename_workspace_by_id(self, workspace_id: str, parent: tk.Misc | None = None) -> None:

        idx = self._find_workspace_index(workspace_id)

        if idx is None:

            return

        current = self.overlay.partitions[idx]

        old_name = str(current.get("name", "工作区"))

        name = simpledialog.askstring("重命名面板", "请输入新的面板名称：", initialvalue=old_name, parent=parent or self)

        if not name:

            return

        name = name.strip()

        if not name:

            return

        parts = [dict(p) for p in self.overlay.partitions]

        parts[idx]["name"] = name

        parts[idx]["folder"] = name

        self._sync_workspaces(parts)

        self._log_line(f"已重命名面板：{old_name} → {name}")

    def _clear_workspace_by_id(self, workspace_id: str) -> None:

        idx = self._find_workspace_index(workspace_id)

        if idx is None:

            return

        name = str(self.overlay.partitions[idx].get("name", "工作区"))

        if not messagebox.askyesno("确认清空", f"清空「{name}」里的所有入口？源文件不会被删除。"):

            return

        parts = [dict(p) for p in self.overlay.partitions]

        parts[idx]["items"] = []

        self._sync_workspaces(parts)

        self._log_line(f"已清空面板入口：{name}")



    def _set_workspace_color(self, workspace_id: str) -> None:

        idx = self._find_workspace_index(workspace_id)

        if idx is None:

            return

        current = str(self.overlay.partitions[idx].get("color", "#336699"))

        _rgb, color = colorchooser.askcolor(color=current, title="选择面板颜色", parent=self)

        if not color:

            return

        parts = [dict(p) for p in self.overlay.partitions]

        for group_idx in self._workspace_group_indexes(workspace_id):

            parts[group_idx]["color"] = color

        self._sync_workspaces(parts)

        self._log_line(f"已更新面板颜色：{parts[idx].get('name', '工作区')}")



    def _set_workspace_alpha(self, workspace_id: str) -> None:

        idx = self._find_workspace_index(workspace_id)

        if idx is None:

            return

        current = float(self.overlay.partitions[idx].get("alpha", 0.42))

        value = simpledialog.askfloat(

            "设置透明度",

            "请输入透明度（20-95，数值越大越不透明）：",

            initialvalue=round(current * 100),

            minvalue=20,

            maxvalue=95,

            parent=self,

        )

        if value is None:

            return

        parts = [dict(p) for p in self.overlay.partitions]

        for group_idx in self._workspace_group_indexes(workspace_id):

            parts[group_idx]["alpha"] = round(value / 100, 2)

        self._sync_workspaces(parts)

        self._log_line(f"已更新面板透明度：{parts[idx].get('name', '工作区')} {int(value)}%")



    def _collect_rules(self) -> list[dict[str, object]]:

        self.cfg.setdefault("ui", {})

        rules = normalize_collect_rules(self.cfg["ui"].get("collect_rules"), self.overlay.partitions)

        self.cfg["ui"]["collect_rules"] = rules

        return [dict(rule) for rule in rules]


    def _workspace_name_map(self) -> dict[str, str]:

        return {str(part.get("id")): str(part.get("name") or "未命名面板") for part in self.overlay.partitions}


    def _open_settings_center(self, focus_workspace_id: str | None = None) -> None:

        rules = self._collect_rules()

        names = self._workspace_name_map()

        dlg = tk.Toplevel(self)

        dlg.title("设置中心")

        dlg.transient(self)

        dlg.geometry("820x520")

        shell = ttk.Frame(dlg, padding=12)

        shell.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(shell, width=150)

        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))

        ttk.Label(left, text="基础设置").pack(anchor=tk.W, pady=(0, 12))

        ttk.Label(left, text="桌面分区").pack(anchor=tk.W, pady=(0, 12))

        ttk.Label(left, text="桌面整理", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 12))

        ttk.Label(left, text="关于").pack(anchor=tk.W, pady=(0, 12))

        body = ttk.Frame(shell)

        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top_row = ttk.Frame(body)

        top_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top_row, text="整理规则", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        ttk.Button(top_row, text="+ 自定义规则", command=lambda: edit_rule(None)).pack(side=tk.RIGHT)
        ttk.Button(top_row, text="恢复默认分类", command=lambda: reset_default_rules()).pack(side=tk.RIGHT, padx=(0, 8))

        columns = ("type", "exts", "target", "enabled")

        tree = ttk.Treeview(body, columns=columns, show="headings", height=14)

        tree.heading("type", text="类型")

        tree.heading("exts", text="包含后缀")

        tree.heading("target", text="整理到对应面板")

        tree.heading("enabled", text="是否启用")

        tree.column("type", width=120, anchor=tk.CENTER)

        tree.column("exts", width=260, anchor=tk.W)

        tree.column("target", width=160, anchor=tk.CENTER)

        tree.column("enabled", width=90, anchor=tk.CENTER)

        tree.pack(fill=tk.BOTH, expand=True)

        def display_exts(rule: dict[str, object]) -> str:

            kind = str(rule.get("kind") or "extension")

            if kind == "folder":

                return "--"

            if kind == "other":

                return "不属于任何规则的文件"

            return ",".join(normalize_extensions(rule.get("exts")))


        def refresh() -> None:

            nonlocal names

            names = self._workspace_name_map()

            for item in tree.get_children():

                tree.delete(item)

            for rule in rules:

                target_id = str(rule.get("target_id") or "")

                tree.insert(

                    "",

                    END,

                    iid=str(rule["id"]),

                    values=(

                        str(rule.get("type") or "自定义"),

                        display_exts(rule),

                        names.get(target_id, "未选择"),

                        "启用" if rule.get("enabled") else "停用",

                    ),

                )


        def reset_default_rules() -> None:

            if not messagebox.askyesno("恢复默认分类", "用内置推荐分类覆盖当前整理规则？", parent=dlg):

                return

            rules[:] = _default_collect_rules(self.overlay.partitions)

            refresh()


        def selected_rule() -> dict[str, object] | None:

            selected = tree.selection()

            if not selected:

                messagebox.showinfo("提示", "请先选择一条规则。", parent=dlg)

                return None

            selected_id = selected[0]

            for rule in rules:

                if str(rule.get("id")) == selected_id:

                    return rule

            return None


        def save_rules() -> None:

            normalized = normalize_collect_rules(rules, self.overlay.partitions)

            self.cfg.setdefault("ui", {})

            self.cfg["ui"]["collect_rules"] = normalized

            save_config(self.config_path, self.cfg)

            self._refresh_rules_ui()

            self._log_line("设置中心：整理规则已保存。")


        def edit_rule(rule: dict[str, object] | None) -> None:

            is_new = rule is None

            data = {

                "id": uuid.uuid4().hex,

                "type": "自定义",

                "kind": "extension",

                "exts": [],

                "target_id": focus_workspace_id or (str(self.overlay.partitions[0].get("id")) if self.overlay.partitions else ""),

                "enabled": True,

            } if is_new else dict(rule)

            edit = tk.Toplevel(dlg)

            edit.title("编辑整理规则")

            edit.transient(dlg)

            edit.grab_set()

            edit.resizable(False, False)

            type_var = tk.StringVar(value=str(data.get("type") or "自定义"))

            kind_labels = {"后缀规则": "extension", "文件夹": "folder", "其它": "other"}

            current_kind = str(data.get("kind") or "extension")

            kind_var = tk.StringVar(value=next((label for label, value in kind_labels.items() if value == current_kind), "后缀规则"))

            ext_var = tk.StringVar(value=" ".join(normalize_extensions(data.get("exts"))))

            target_options = [f"{name} [{workspace_id[:6]}]" for workspace_id, name in names.items()]

            option_to_id = {f"{name} [{workspace_id[:6]}]": workspace_id for workspace_id, name in names.items()}

            initial_target = str(data.get("target_id") or "")

            target_var = tk.StringVar(value=next((text for text, workspace_id in option_to_id.items() if workspace_id == initial_target), target_options[0] if target_options else ""))

            enabled_var = tk.BooleanVar(value=bool(data.get("enabled", True)))

            ttk.Label(edit, text="类型名称").grid(row=0, column=0, sticky=tk.W, padx=10, pady=8)

            ttk.Entry(edit, textvariable=type_var, width=34).grid(row=0, column=1, padx=10, pady=8)

            ttk.Label(edit, text="规则类型").grid(row=1, column=0, sticky=tk.W, padx=10, pady=8)

            ttk.Combobox(edit, textvariable=kind_var, values=list(kind_labels.keys()), state="readonly", width=31).grid(row=1, column=1, padx=10, pady=8)

            ttk.Label(edit, text="包含后缀").grid(row=2, column=0, sticky=tk.W, padx=10, pady=8)

            ttk.Entry(edit, textvariable=ext_var, width=34).grid(row=2, column=1, padx=10, pady=8)

            ttk.Label(edit, text="整理到面板").grid(row=3, column=0, sticky=tk.W, padx=10, pady=8)

            ttk.Combobox(edit, textvariable=target_var, values=target_options, state="readonly", width=31).grid(row=3, column=1, padx=10, pady=8)

            ttk.Checkbutton(edit, text="启用这条规则", variable=enabled_var).grid(row=4, column=1, sticky=tk.W, padx=10, pady=8)

            def ok() -> None:

                target_id = option_to_id.get(target_var.get(), "")

                kind = kind_labels.get(kind_var.get(), "extension")

                if enabled_var.get() and not target_id:

                    messagebox.showwarning("提示", "启用规则前需要选择目标面板。", parent=edit)

                    return

                data["type"] = type_var.get().strip() or "自定义"

                data["kind"] = kind

                data["exts"] = normalize_extensions(ext_var.get()) if kind == "extension" else []

                data["target_id"] = target_id

                data["enabled"] = bool(enabled_var.get())

                if is_new:

                    rules.append(data)

                else:

                    rule.update(data)

                refresh()

                edit.destroy()

            buttons = ttk.Frame(edit)

            buttons.grid(row=5, column=0, columnspan=2, sticky=tk.E, padx=10, pady=(8, 10))

            ttk.Button(buttons, text="确定", command=ok).pack(side=tk.LEFT, padx=(0, 8))

            ttk.Button(buttons, text="取消", command=edit.destroy).pack(side=tk.LEFT)


        def edit_selected() -> None:

            rule = selected_rule()

            if rule:

                edit_rule(rule)


        def toggle_selected() -> None:

            rule = selected_rule()

            if not rule:

                return

            if not rule.get("target_id") and not rule.get("enabled"):

                messagebox.showwarning("提示", "请先编辑规则并选择目标面板。", parent=dlg)

                return

            rule["enabled"] = not bool(rule.get("enabled"))

            refresh()


        def delete_selected() -> None:

            rule = selected_rule()

            if not rule:

                return

            if not messagebox.askyesno("确认删除", f"删除规则「{rule.get('type', '自定义')}」？", parent=dlg):

                return

            rules.remove(rule)

            refresh()


        btn_row = ttk.Frame(body)

        btn_row.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(btn_row, text="编辑", command=edit_selected).pack(side=tk.LEFT)

        ttk.Button(btn_row, text="启用/停用", command=toggle_selected).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(btn_row, text="删除", command=delete_selected).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(btn_row, text="保存并关闭", command=lambda: (save_rules(), dlg.destroy())).pack(side=tk.RIGHT)

        ttk.Button(btn_row, text="保存", command=save_rules).pack(side=tk.RIGHT, padx=(0, 8))

        refresh()

        if focus_workspace_id:

            for rule in rules:

                if str(rule.get("target_id")) == focus_workspace_id:

                    tree.selection_set(str(rule["id"]))

                    tree.see(str(rule["id"]))

                    break


    def _set_workspace_rules(self, workspace_id: str) -> None:

        self._open_settings_center(workspace_id)



    def _delete_workspace_by_id(self, workspace_id: str) -> None:

        idx = self._find_workspace_index(workspace_id)

        if idx is None:

            return

        if len(self.overlay.partitions) <= 1:

            messagebox.showwarning("提示", "至少保留一个面板。")

            return

        name = str(self.overlay.partitions[idx].get("name", "工作区"))

        if not messagebox.askyesno("确认删除", f"删除面板「{name}」？源文件不会被删除。"):

            return

        parts = [dict(p) for i, p in enumerate(self.overlay.partitions) if i != idx]

        self._sync_workspaces(parts)

        self._log_line(f"已删除面板：{name}")


    def _add_files_to_workspace(self, workspace_id: str) -> None:

        paths = filedialog.askopenfilenames(title="选择要加入面板的文件", parent=self)

        if not paths:

            return

        self._on_partition_drop(workspace_id, [Path(path) for path in paths])


    def _add_folder_to_workspace(self, workspace_id: str) -> None:

        path = filedialog.askdirectory(title="选择要加入面板的文件夹", parent=self)

        if not path:

            return

        self._on_partition_drop(workspace_id, [Path(path)])


    def _add_path_to_workspace(self, workspace_id: str) -> None:

        raw = simpledialog.askstring("添加路径", "请输入文件、文件夹或快捷方式路径：", parent=self)

        if not raw:

            return

        self._on_partition_drop(workspace_id, [Path(raw.strip().strip('"'))])



    def _on_workspace_action(self, workspace_id: str, action: str) -> None:

        if action == "add_files":

            self._add_files_to_workspace(workspace_id)

        elif action == "add_folder":

            self._add_folder_to_workspace(workspace_id)

        elif action == "add_path":

            self._add_path_to_workspace(workspace_id)

        elif action == "new":

            self._add_workspace()

        elif action == "rename":

            self._rename_workspace_by_id(workspace_id)

        elif action == "clear":

            self._clear_workspace_by_id(workspace_id)

        elif action == "delete":

            self._delete_workspace_by_id(workspace_id)

        elif action == "color":

            self._set_workspace_color(workspace_id)

        elif action == "alpha":

            self._set_workspace_alpha(workspace_id)

        elif action == "rules":

            self._set_workspace_rules(workspace_id)



    def _manage_workspaces(self) -> None:

        dlg = tk.Toplevel(self)

        dlg.title("管理工作区")

        dlg.transient(self)

        dlg.grab_set()

        dlg.geometry("460x320")

        ttk.Label(dlg, text="工作区用于收纳快捷入口；从面板 ... 添加项目只保存路径引用，不移动源文件。").pack(anchor=tk.W, padx=10, pady=(10, 4))

        tree = ttk.Treeview(dlg, columns=("name", "count"), show="headings", height=8)

        tree.heading("name", text="名称")

        tree.heading("count", text="入口数量")

        tree.column("name", width=180, anchor=tk.W)

        tree.column("count", width=100, anchor=tk.W)

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        def refresh() -> None:

            for item in tree.get_children():

                tree.delete(item)

            for part in self.overlay.partitions:

                tree.insert("", END, iid=str(part["id"]), values=(part["name"], len(normalize_items(part.get("items")))))

        def selected_index() -> int | None:

            selected = tree.selection()

            if not selected:

                messagebox.showinfo("提示", "请先选择一个工作区。", parent=dlg)

                return None

            part_id = selected[0]

            for idx, part in enumerate(self.overlay.partitions):

                if str(part.get("id")) == part_id:

                    return idx

            return None

        def add_workspace() -> None:

            self._add_workspace(dlg)

            refresh()

        def rename_workspace() -> None:

            idx = selected_index()

            if idx is None:

                return

            workspace_id = str(self.overlay.partitions[idx].get("id"))

            self._rename_workspace_by_id(workspace_id, dlg)

            refresh()

        def delete_workspace() -> None:

            idx = selected_index()

            if idx is None:

                return

            workspace_id = str(self.overlay.partitions[idx].get("id"))

            self._delete_workspace_by_id(workspace_id)

            refresh()

        btns = ttk.Frame(dlg)

        btns.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(btns, text="新建", command=add_workspace).pack(side=tk.LEFT)

        ttk.Button(btns, text="重命名", command=rename_workspace).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(btns, text="删除", command=delete_workspace).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(btns, text="关闭", command=dlg.destroy).pack(side=tk.RIGHT)

        refresh()



    def _on_partition_drop(self, workspace_id: str, paths: list[Path]) -> None:

        if not paths:

            self._log_line("未接收到任何入口。")

            return

        added = 0

        parts = [dict(p) for p in self.overlay.partitions]

        for part in parts:

            if str(part.get("id")) != workspace_id:

                continue

            items = normalize_items(part.get("items"))

            existing_paths = {item["path"] for item in items}

            for raw in paths:

                try:

                    src = Path(os.path.expandvars(str(raw))).expanduser().resolve()

                except Exception as exc:

                    self._log_line(f"添加入口失败，已跳过: {raw}（{exc}）")

                    continue

                try:

                    entry_path = self._desktop_entry_for_drop(src)

                except Exception as exc:

                    self._log_line(f"创建桌面入口失败，已跳过: {src}（{exc}）")

                    continue

                path_text = str(entry_path)

                if path_text in existing_paths:

                    self._log_line(f"已存在，跳过: {path_text}")

                    continue

                try:

                    items.append(make_item_from_path(entry_path))

                except Exception as exc:

                    self._log_line(f"添加入口失败，已跳过: {src}（{exc}）")

                    continue

                existing_paths.add(path_text)

                added += 1

                if entry_path == src:

                    self._log_line(f"已添加入口: {src.name}（源文件未移动）")

                else:

                    self._log_line(f"已在桌面创建入口并添加到面板: {entry_path.name}（源文件未移动）")

            part["items"] = items

            break

        if added:

            self._save_workspaces(parts)

            if self.var_overlay.get():

                self.overlay.show()



    def _open_workspace_item(self, path_text: str) -> None:

        path = Path(path_text)

        try:

            os_startfile = getattr(os, "startfile", None)

            if os_startfile:

                os_startfile(path)

            else:

                webbrowser.open(path.as_uri())

            self._log_line(f"已打开: {path}")

        except Exception as e:

            messagebox.showerror("打开失败", str(e))



    def _remove_workspace_item(self, workspace_id: str, item_id: str) -> None:

        parts = [dict(p) for p in self.overlay.partitions]

        removed_name = ""

        for part in parts:

            if str(part.get("id")) != workspace_id:

                continue

            old_items = normalize_items(part.get("items"))

            new_items = []

            for item in old_items:

                if item["id"] == item_id:

                    removed_name = item["name"]

                    continue

                new_items.append(item)

            part["items"] = new_items

            break

        if not removed_name:

            return

        self._save_workspaces(parts)

        if self.var_overlay.get():

            self.overlay.show()

        self._log_line(f"已从工作区移除入口：{removed_name}（源文件未删除）")



    def _apply_startup_choice(self) -> None:

        ok, msg = set_startup_enabled(self.var_startup.get())

        self._log_line(msg)

        if not ok:

            self.var_startup.set(is_startup_enabled())

            return

        self.cfg.setdefault("ui", {})

        self.cfg["ui"]["startup_enabled"] = self.var_startup.get()

        save_config(self.config_path, self.cfg)



    def _show_main_window(self) -> None:

        self.deiconify()

        self.state("normal")

        self.lift()

        try:

            self.focus_force()

        except tk.TclError:

            pass



    def _on_close(self) -> None:

        if self.tray_icon and tray_supported() and self.var_minimize_tray.get():

            self.withdraw()

            return

        self._quit_app()



    def _quit_app(self) -> None:

        try:

            self.overlay.hide()

        except tk.TclError:

            pass

        if self.tray_icon is not None:

            try:

                self.tray_icon.stop()

            except Exception:

                pass

        self.destroy()



    def _tray_toggle_overlay(self) -> None:

        self.var_overlay.set(not self.var_overlay.get())

        self._on_overlay_toggle()



    def _tray_toggle_startup(self) -> None:

        self.var_startup.set(not self.var_startup.get())

        self._apply_startup_choice()



    def _pick_archive(self) -> None:

        path = filedialog.askdirectory(title="选择归档根目录")

        if path:

            self.archive_var.set(path)


    def _pick_desktop(self) -> None:

        path = filedialog.askdirectory(title="选择桌面路径")

        if path:

            self.desktop_var.set(path)

            self.cfg["desktop"] = path

            self._persist_ui_only()

            self._log_line(f"桌面路径已更新: {path}")


    def _open_desktop(self) -> None:

        path = Path(self.desktop_var.get().strip() or str(desktop_dir(self.cfg)))

        path.mkdir(parents=True, exist_ok=True)

        try:

            os_startfile = getattr(os, "startfile", None)

            if os_startfile:

                os_startfile(path)

            else:

                webbrowser.open(path.as_uri())

        except Exception as e:

            messagebox.showerror("打开失败", str(e))



    def _open_archive(self) -> None:

        path = Path(self.archive_var.get().strip() or self._archive_display())

        path.mkdir(parents=True, exist_ok=True)

        try:

            os_startfile = getattr(os, "startfile", None)

            if os_startfile:

                os_startfile(path)

            else:

                webbrowser.open(path.as_uri())

        except Exception as e:

            messagebox.showerror("打开失败", str(e))



    def _refresh_rules_ui(self) -> None:

        for i in self.tree.get_children():

            self.tree.delete(i)

        names = self._workspace_name_map()

        for rule in self._collect_rules():

            kind = str(rule.get("kind") or "extension")

            if kind == "folder":

                ext_text = "--"

            elif kind == "other":

                ext_text = "其它"

            else:

                ext_text = ",".join(normalize_extensions(rule.get("exts"))) or "--"

            target = names.get(str(rule.get("target_id") or ""), "未选择")

            status = "启用" if rule.get("enabled") else "停用"

            self.tree.insert("", END, values=(f"{rule.get('type', '自定义')}  {ext_text}", f"{target} / {status}"))



    def _add_rule(self) -> None:

        dlg = tk.Toplevel(self)

        dlg.title("添加规则")

        dlg.transient(self)

        dlg.grab_set()



        ttk.Label(dlg, text="后缀（如 pdf 或 .pdf）:").grid(row=0, column=0, sticky=tk.W, padx=8, pady=8)

        ext_var = tk.StringVar()

        ttk.Entry(dlg, textvariable=ext_var, width=28).grid(row=0, column=1, padx=8, pady=8)



        ttk.Label(dlg, text="子文件夹名:").grid(row=1, column=0, sticky=tk.W, padx=8, pady=8)

        folder_var = tk.StringVar()

        ttk.Entry(dlg, textvariable=folder_var, width=28).grid(row=1, column=1, padx=8, pady=8)



        def ok() -> None:

            ext = ensure_extension_key(ext_var.get())

            folder = folder_var.get().strip()

            if not ext or not folder:

                messagebox.showwarning("提示", "请填写后缀和文件夹名。")

                return

            rules = dict(self.cfg.get("rules") or {})

            rules[ext] = folder

            self.cfg["rules"] = rules

            self._refresh_rules_ui()

            dlg.destroy()



        btns = ttk.Frame(dlg)

        btns.grid(row=2, column=0, columnspan=2, pady=8)

        ttk.Button(btns, text="确定", command=ok).pack(side=tk.LEFT, padx=4)

        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=4)



    def _del_rule(self) -> None:

        sel = self.tree.selection()

        if not sel:

            messagebox.showinfo("提示", "请先选中一行规则。")

            return

        item = sel[0]

        ext, _folder = self.tree.item(item, "values")

        rules = dict(self.cfg.get("rules") or {})

        rules.pop(ext, None)

        self.cfg["rules"] = rules

        self._refresh_rules_ui()



    def _save_cfg(self) -> None:

        self.cfg["archive_root"] = self.archive_var.get().strip()

        self.cfg["desktop"] = self.desktop_var.get().strip()

        self._persist_ui_only()

        self._log_line("配置已保存。")



    def _plan_workspace_collect(self) -> tuple[list[tuple[int, Path]], list[str]]:

        if "desktop_var" in self.__dict__:

            self.cfg["desktop"] = self.desktop_var.get().strip()

        desktop = desktop_dir(self.cfg)

        if not desktop.is_dir():

            return [], [f"桌面路径不存在或不可访问: {desktop}"]

        plans: list[tuple[int, Path]] = []

        logs: list[str] = []

        rules = self._collect_rules()

        id_to_index = {str(part.get("id")): idx for idx, part in enumerate(self.overlay.partitions)}

        ext_owner: dict[str, int] = {}

        folder_owner: int | None = None

        other_owner: int | None = None

        for rule in rules:

            if not rule.get("enabled"):

                continue

            target_idx = id_to_index.get(str(rule.get("target_id") or ""))

            if target_idx is None:

                continue

            kind = str(rule.get("kind") or "extension")

            if kind == "folder":

                folder_owner = target_idx

            elif kind == "other":

                other_owner = target_idx

            else:

                for ext in normalize_extensions(rule.get("exts")):

                    if ext not in ext_owner:

                        ext_owner[ext] = target_idx

        if not ext_owner and folder_owner is None and other_owner is None:

            return [], ["还没有启用任何整理规则。请打开「设置中心 → 桌面整理」设置类型、后缀、目标面板和启用状态。"]

        existing_by_index = {

            idx: {item["path"] for item in normalize_items(part.get("items"))}

            for idx, part in enumerate(self.overlay.partitions)

        }

        for entry in sorted(desktop.iterdir(), key=lambda p: p.name.lower()):

            idx: int | None

            if entry.is_dir():

                idx = folder_owner if folder_owner is not None else other_owner

            elif entry.is_file():

                idx = ext_owner.get(entry.suffix.lower())

                if idx is None:

                    idx = other_owner

            else:

                idx = other_owner

            if idx is None:

                continue

            path_text = str(entry.resolve())

            panel_name = str(self.overlay.partitions[idx].get("name", "工作区"))

            if path_text in existing_by_index[idx]:

                logs.append(f"已存在，跳过「{panel_name}」: {entry.name}")

                continue

            plans.append((idx, entry.resolve()))

            logs.append(f"将添加到「{panel_name}」: {entry.name}")

        if not logs:

            logs.append("没有匹配设置中心整理规则的桌面项目。")

        return plans, logs



    def _preview_organize(self) -> None:

        plans, logs = self._plan_workspace_collect()

        self._log_line(f"预览结果：{len(plans)} 个桌面文件入口将被添加，源文件不会移动。")

        for line in logs:

            self._log_line(line)



    def _run_organize(self) -> None:

        plans, preview_logs = self._plan_workspace_collect()

        for line in preview_logs:

            self._log_line(line)

        if not plans:

            return

        if not messagebox.askyesno("确认整理", f"将添加 {len(plans)} 个入口到面板，源文件不会移动。是否继续？"):

            self._log_line("已取消整理。")

            return

        parts = [dict(p) for p in self.overlay.partitions]

        added = 0

        for idx, path in plans:

            items = normalize_items(parts[idx].get("items"))

            existing_paths = {item["path"] for item in items}

            path_text = str(path)

            if path_text in existing_paths:

                continue

            items.append(make_item_from_path(path))

            parts[idx]["items"] = items

            added += 1

        if added:

            self._save_workspaces(parts)

            if self.var_overlay.get():

                self.overlay.show()

        self._log_line(f"整理完成：已添加 {added} 个入口，源文件未移动。")



    def _run_undo(self) -> None:

        ok, logs = undo_last_batch(undo_log_path(self.config_path))

        for line in logs:

            self._log_line(line)

        if ok:

            self._log_line("撤销完成。")



    def _log_line(self, text: str) -> None:

        self.log.insert(END, text + "\n")

        self.log.see(END)





def main() -> None:

    App().mainloop()





if __name__ == "__main__":

    main()
