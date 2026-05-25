"""桌面工作区：半透明置顶启动器；拖入文件只保存路径引用。"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import tkinter as tk

from windows_native import primary_work_area

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [
            ("hIcon", wintypes.HANDLE),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", wintypes.DWORD),
            ("szDisplayName", wintypes.WCHAR * 260),
            ("szTypeName", wintypes.WCHAR * 80),
        ]

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HANDLE),
            ("hbmColor", wintypes.HANDLE),
        ]

    class BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", wintypes.LONG),
            ("bmWidth", wintypes.LONG),
            ("bmHeight", wintypes.LONG),
            ("bmWidthBytes", wintypes.LONG),
            ("bmPlanes", wintypes.WORD),
            ("bmBitsPixel", wintypes.WORD),
            ("bmBits", wintypes.LPVOID),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]
else:
    ctypes = None
    wintypes = None

try:
    import windnd

    WINDND_AVAILABLE = True
except ImportError:
    WINDND_AVAILABLE = False

# windnd is useful, but repeatedly hooking/destroying many Tk child widgets can
# leave Windows with stale HWND callbacks. Keep direct shell drop as an explicit
# opt-in while the stable path uses the panel menu to add files/folders.
DIRECT_WINDND_ENABLED = os.environ.get("DESKTOP_TIDY_ENABLE_WINDND", "").strip() == "1"
DROP_AVAILABLE = WINDND_AVAILABLE and DIRECT_WINDND_ENABLED


DEFAULT_PANEL_COLOR = "#111111"
DEFAULT_PANEL_ALPHA = 0.60
TRANSPARENT_COLOR = "#010203"
LEGACY_DEFAULT_COLORS = {"#336699", "#7b6794"}
IMAGE_PREVIEW_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
WORD_EXTS = {".doc", ".docx", ".rtf", ".wps", ".odt"}
SHEET_EXTS = {".xls", ".xlsx", ".csv", ".ods", ".xlsm"}
SLIDE_EXTS = {".ppt", ".pptx", ".pps", ".ppsx", ".pptm"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".iso"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}


DEFAULT_PARTITIONS: list[dict[str, object]] = [
    {"id": "study", "name": "学习", "folder": "学习", "rx": 0.03, "ry": 0.04, "rw": 0.62, "rh": 0.36, "color": DEFAULT_PANEL_COLOR, "alpha": DEFAULT_PANEL_ALPHA, "locked": False, "match_exts": [], "items": []},
    {"id": "tools", "name": "工具", "folder": "工具", "rx": 0.03, "ry": 0.44, "rw": 0.62, "rh": 0.36, "color": DEFAULT_PANEL_COLOR, "alpha": DEFAULT_PANEL_ALPHA, "locked": False, "match_exts": [], "items": []},
]


def _clamp_float(value: object, default: float, low: float, high: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = default
    return min(high, max(low, num))


def normalize_partition_list(partitions: list[dict[str, object]]) -> list[dict[str, object]]:
    """兼容旧配置，并补齐编辑工作区需要的字段。"""
    out: list[dict[str, object]] = []
    for index, p in enumerate(partitions):
        d = dict(p)
        name = str(d.get("name") or f"工作区 {index + 1}").strip() or f"工作区 {index + 1}"
        folder = str(d.get("folder") or "").strip() or name
        d["id"] = str(d.get("id") or uuid.uuid4().hex)
        d["name"] = name
        d["folder"] = folder
        d["rx"] = _clamp_float(d.get("rx"), 0.05, 0.0, 0.95)
        d["ry"] = _clamp_float(d.get("ry"), 0.05, 0.0, 0.95)
        d["rw"] = _clamp_float(d.get("rw"), 0.25, 0.08, 1.0)
        d["rh"] = _clamp_float(d.get("rh"), 0.2, 0.08, 1.0)
        raw_color = str(d.get("color") or "").strip()
        d["color"] = DEFAULT_PANEL_COLOR if not raw_color or raw_color.lower() in LEGACY_DEFAULT_COLORS else raw_color
        alpha = _clamp_float(d.get("alpha"), DEFAULT_PANEL_ALPHA, 0.18, 0.95)
        d["alpha"] = DEFAULT_PANEL_ALPHA if abs(alpha - 0.68) < 0.001 or abs(alpha - 0.90) < 0.001 else alpha
        d["locked"] = bool(d.get("locked", False))
        d["hidden"] = bool(d.get("hidden", False))
        d["collapsed"] = bool(d.get("collapsed", False))
        d["group_id"] = str(d.get("group_id") or "")
        d["match_exts"] = normalize_extensions(d.get("match_exts"))
        d["items"] = normalize_items(d.get("items"))
        out.append(d)
    return out


def normalize_extensions(value: object) -> list[str]:
    if isinstance(value, str):
        raw_parts = value.replace(",", " ").replace(";", " ").split()
    elif isinstance(value, list):
        raw_parts = [str(item) for item in value]
    else:
        raw_parts = []
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        ext = raw.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in seen:
            out.append(ext)
            seen.add(ext)
    return out


def normalize_items(items: object) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        name = str(item.get("name") or Path(path).stem or Path(path).name).strip()
        out.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "name": name or "入口",
                "path": path,
                "kind": str(item.get("kind") or "path"),
            }
        )
    return out


def make_item_from_path(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    kind = "shortcut" if suffix in {".lnk", ".url"} else "folder" if path.is_dir() else "file"
    return {
        "id": uuid.uuid4().hex,
        "name": path.stem if suffix in {".lnk", ".url"} else path.name,
        "path": str(path),
        "kind": kind,
    }


class PartitionOverlay:
    def __init__(
        self,
        root: tk.Tk,
        partitions: list[dict[str, object]] | None = None,
        *,
        on_drop: Callable[[str, list[Path]], None] | None = None,
        on_open_item: Callable[[str], None] | None = None,
        on_remove_item: Callable[[str, str], None] | None = None,
        on_workspace_action: Callable[[str, str], None] | None = None,
        on_layout_change: Callable[[list[dict[str, object]]], None] | None = None,
    ) -> None:
        self.root = root
        self.partitions: list[dict[str, object]] = normalize_partition_list(
            list(partitions) if partitions else list(DEFAULT_PARTITIONS)
        )
        self.on_drop = on_drop
        self.on_open_item = on_open_item
        self.on_remove_item = on_remove_item
        self.on_workspace_action = on_workspace_action
        self.on_layout_change = on_layout_change
        self.default_alpha = DEFAULT_PANEL_ALPHA
        self.edit_alpha = DEFAULT_PANEL_ALPHA
        self.snap_px = 14
        self.edit_mode = False
        self._windows: list[tk.Toplevel] = []
        self._drag: dict[str, Any] | None = None
        self._resize: dict[str, Any] | None = None
        self._active_groups: dict[str, str] = {}
        self._pending_rename_id: str | None = None
        self._drop_errors: list[str] = []
        self._image_refs: list[object] = []

    def set_partitions(self, partitions: list[dict[str, object]]) -> None:
        self.partitions = normalize_partition_list(
            list(partitions) if partitions else list(DEFAULT_PARTITIONS)
        )

    def set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = enabled
        if self.visible():
            self.show()

    def request_inline_rename(self, workspace_id: str) -> None:
        self._pending_rename_id = workspace_id
        if self.visible():
            self.show()

    def _toggle_lock(self, workspace_id: str) -> None:
        for index, part in enumerate(self.partitions):
            if str(part.get("id")) != workspace_id:
                continue
            updated = dict(part)
            updated["locked"] = not bool(updated.get("locked", True))
            self.partitions[index] = updated
            if self.on_layout_change:
                self.on_layout_change(self.partitions)
            self.show()
            return

    def _toggle_collapsed(self, workspace_id: str) -> str:
        for index, part in enumerate(self.partitions):
            if str(part.get("id")) != workspace_id:
                continue
            updated = dict(part)
            updated["collapsed"] = not bool(updated.get("collapsed", False))
            self.partitions[index] = updated
            if self.on_layout_change:
                self.on_layout_change(self.partitions)
            self.show()
            return "break"
        return "break"

    def _show_workspace_menu(self, event: tk.Event, workspace_id: str) -> None:
        if not self.on_workspace_action:
            return
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="添加文件...", command=lambda: self.on_workspace_action(workspace_id, "add_files"))
        menu.add_command(label="添加文件夹...", command=lambda: self.on_workspace_action(workspace_id, "add_folder"))
        menu.add_command(label="添加路径...", command=lambda: self.on_workspace_action(workspace_id, "add_path"))
        menu.add_separator()
        menu.add_command(label="新建面板", command=lambda: self.on_workspace_action(workspace_id, "new"))
        menu.add_command(label="重命名", command=lambda: self.on_workspace_action(workspace_id, "rename"))
        menu.add_command(label="整理规则", command=lambda: self.on_workspace_action(workspace_id, "rules"))
        menu.add_command(label="颜色", command=lambda: self.on_workspace_action(workspace_id, "color"))
        menu.add_command(label="透明度", command=lambda: self.on_workspace_action(workspace_id, "alpha"))
        menu.add_separator()
        menu.add_command(label="清空入口", command=lambda: self.on_workspace_action(workspace_id, "clear"))
        menu.add_command(label="删除面板", command=lambda: self.on_workspace_action(workspace_id, "delete"))
        menu.tk_popup(event.x_root, event.y_root)

    def _start_inline_rename(self, label: tk.Label, workspace_id: str, current_name: str) -> str:
        label.pack_forget()
        entry_var = tk.StringVar(value=current_name)
        entry = tk.Entry(
            label.master,
            textvariable=entry_var,
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT,
            bg="#ffffff",
            fg="#111111",
            insertbackground="#111111",
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 8), pady=7)
        entry.selection_range(0, tk.END)
        entry.focus_set()
        committed = {"done": False}

        def finish(save: bool) -> None:
            if committed["done"]:
                return
            committed["done"] = True
            new_name = entry_var.get().strip()
            if save and new_name and new_name != current_name:
                for index, part in enumerate(self.partitions):
                    if str(part.get("id")) != workspace_id:
                        continue
                    updated = dict(part)
                    updated["name"] = new_name
                    updated["folder"] = new_name
                    self.partitions[index] = updated
                    if self.on_layout_change:
                        self.on_layout_change(self.partitions)
                    break
            try:
                entry.destroy()
            except tk.TclError:
                pass
            self.show()

        entry.bind("<Return>", lambda _event: (finish(True), "break")[-1])
        entry.bind("<Escape>", lambda _event: (finish(False), "break")[-1])
        entry.bind("<FocusOut>", lambda _event: finish(True))
        return "break"

    def visible(self) -> bool:
        return bool(self._windows)

    def hide(self) -> None:
        for w in self._windows:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._windows.clear()
        self._drag = None
        self._resize = None
        self._image_refs.clear()

    def _make_drop_handler(self, workspace_id: str):
        def handler(files) -> None:
            def run() -> None:
                try:
                    if not self.on_drop:
                        return
                    paths: list[Path] = []
                    for f in files:
                        if isinstance(f, bytes):
                            paths.append(Path(os.fsdecode(f)))
                        else:
                            paths.append(Path(str(f)))
                    self.on_drop(workspace_id, paths)
                except Exception as exc:
                    self._drop_errors.append(str(exc))

            try:
                self.root.after(0, run)
            except Exception as exc:
                self._drop_errors.append(str(exc))

        return handler

    def _hook_drop(self, widget: tk.Widget, workspace_id: str) -> None:
        if not DROP_AVAILABLE or not self.on_drop:
            return
        try:
            windnd.hook_dropfiles(widget, func=self._make_drop_handler(workspace_id), force_unicode=True)
        except Exception:
            pass

    def _paired_backdrop(self, window: tk.Toplevel) -> tk.Toplevel | None:
        backdrop = getattr(window, "_panel_backdrop", None)
        return backdrop if isinstance(backdrop, tk.Toplevel) else None

    def _set_paired_geometry(self, window: tk.Toplevel, geometry: str) -> None:
        backdrop = self._paired_backdrop(window)
        if backdrop is not None:
            try:
                backdrop.geometry(geometry)
            except tk.TclError:
                pass
        window.geometry(geometry)

    def _item_icon(self, kind: str) -> str:
        if kind == "folder":
            return "[DIR]"
        if kind == "shortcut":
            return "[APP]"
        return "[FILE]"

    def _short_name(self, name: str, limit: int = 22) -> str:
        clean = " ".join(str(name or "入口").split())
        if len(clean) <= limit:
            return clean
        first = max(8, limit // 2)
        second = max(6, limit - first - 3)
        return f"{clean[:first]}\n{clean[first:first + second]}..."

    def _font(self, size: int, bold: bool = False):
        if not PIL_AVAILABLE:
            return None
        for name in ("arialbd.ttf" if bold else "arial.ttf", "segoeui.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _url_target(self, path: Path) -> Path | None:
        if path.suffix.lower() != ".url" or not path.is_file():
            return None
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.lower().startswith("url="):
                    continue
                raw = line.split("=", 1)[1].strip()
                parsed = urlparse(raw)
                if parsed.scheme == "file":
                    target = unquote(parsed.path)
                    if os.name == "nt" and target.startswith("/") and len(target) > 2 and target[2] == ":":
                        target = target[1:]
                    return Path(target)
        except OSError:
            return None
        return None

    def _display_path(self, item: dict[str, str]) -> Path:
        path = Path(str(item.get("path", "")))
        return self._url_target(path) or path

    def _hicon_image(self, hicon: int):
        if not PIL_AVAILABLE or ctypes is None:
            return None
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        iconinfo = ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(iconinfo)):
            return None
        try:
            if not iconinfo.hbmColor:
                return None
            bitmap = BITMAP()
            if not gdi32.GetObjectW(iconinfo.hbmColor, ctypes.sizeof(bitmap), ctypes.byref(bitmap)):
                return None
            width = int(bitmap.bmWidth)
            height = int(bitmap.bmHeight)
            if width <= 0 or height <= 0:
                return None

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            buffer = ctypes.create_string_buffer(width * height * 4)
            hdc = user32.GetDC(None)
            try:
                copied = gdi32.GetDIBits(
                    hdc,
                    iconinfo.hbmColor,
                    0,
                    height,
                    buffer,
                    ctypes.byref(bmi),
                    0,
                )
            finally:
                user32.ReleaseDC(None, hdc)
            if not copied:
                return None
            image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).copy()
            if image.getchannel("A").getextrema() == (0, 0):
                image.putalpha(255)
            image.thumbnail((54, 54), Image.LANCZOS)
            canvas = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
            canvas.paste(image, ((56 - image.width) // 2, (56 - image.height) // 2), image)
            return canvas
        finally:
            if iconinfo.hbmColor:
                gdi32.DeleteObject(iconinfo.hbmColor)
            if iconinfo.hbmMask:
                gdi32.DeleteObject(iconinfo.hbmMask)

    def _shell_icon_photo(self, item: dict[str, str]) -> object | None:
        if not PIL_AVAILABLE or ctypes is None:
            return None
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        path = self._display_path(item)
        kind = str(item.get("kind", "path"))
        flags = 0x000000100 | 0x000000000
        attrs = 0
        lookup = str(path)
        if not path.exists():
            flags |= 0x000000010
            attrs = 0x00000010 if kind == "folder" else 0x00000080
            lookup = path.suffix or path.name or ".txt"
        info = SHFILEINFOW()
        result = shell32.SHGetFileInfoW(lookup, attrs, ctypes.byref(info), ctypes.sizeof(info), flags)
        if not result or not info.hIcon:
            return None
        try:
            image = self._hicon_image(int(info.hIcon))
        finally:
            user32.DestroyIcon(info.hIcon)
        if image is None:
            return None
        photo = ImageTk.PhotoImage(image)
        self._image_refs.append(photo)
        return photo

    def _badge_for_item(self, item: dict[str, str]) -> tuple[str, str]:
        path = self._display_path(item)
        ext = path.suffix.lower()
        kind = str(item.get("kind", "path"))
        if kind == "folder" or path.is_dir():
            return "folder", "文件夹"
        if ext in PDF_EXTS:
            return "doc", "PDF"
        if ext in WORD_EXTS:
            return "doc", "W"
        if ext in SHEET_EXTS:
            return "sheet", "X"
        if ext in SLIDE_EXTS:
            return "slide", "P"
        if ext in ARCHIVE_EXTS:
            return "archive", "ZIP"
        if ext in AUDIO_EXTS:
            return "media", "MP3"
        if ext in VIDEO_EXTS:
            return "media", "MP4"
        if ext in {".exe", ".lnk", ".url"} or kind == "shortcut":
            return "app", "APP"
        return "doc", ext[1:4].upper() if ext else "FILE"

    def _draw_type_icon(self, item: dict[str, str]) -> object | None:
        if not PIL_AVAILABLE:
            return None
        icon_type, badge = self._badge_for_item(item)
        img = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        small = self._font(9, True)
        big = self._font(12, True)

        if icon_type == "folder":
            draw.rounded_rectangle((7, 16, 49, 45), radius=5, fill="#e7b84d", outline="#fff2a8", width=1)
            draw.rounded_rectangle((10, 10, 30, 20), radius=4, fill="#f1cf6f")
            draw.text((14, 30), "DIR", font=small, fill="#5b3a05")
        elif icon_type == "app":
            draw.rounded_rectangle((8, 8, 48, 48), radius=9, fill="#e9eef7", outline="#ffffff", width=1)
            draw.rounded_rectangle((14, 14, 42, 42), radius=7, fill="#4f7cff")
            draw.text((17, 25), "APP", font=small, fill="#ffffff")
        else:
            badge_colors = {
                "doc": "#e53935",
                "sheet": "#24a148",
                "slide": "#e68619",
                "archive": "#7b61ff",
                "media": "#2aa5d8",
            }
            badge_color = badge_colors.get(icon_type, "#607d8b")
            draw.rounded_rectangle((13, 5, 43, 49), radius=3, fill="#f5f7fb", outline="#ffffff", width=1)
            draw.polygon([(34, 5), (43, 14), (34, 14)], fill="#d8dce5")
            draw.rectangle((13, 31, 43, 45), fill=badge_color)
            tw = draw.textlength(badge, font=small)
            draw.text((28 - tw / 2, 34), badge, font=small, fill="#ffffff")
            if badge in {"W", "X", "P"}:
                draw.text((23, 17), badge, font=big, fill=badge_color)

        photo = ImageTk.PhotoImage(img)
        self._image_refs.append(photo)
        return photo

    def _thumbnail_icon(self, item: dict[str, str]) -> object | None:
        if not PIL_AVAILABLE:
            return None
        path = self._display_path(item)
        if path.suffix.lower() not in IMAGE_PREVIEW_EXTS or not path.is_file():
            return None
        try:
            with Image.open(path) as source:
                source.thumbnail((54, 54))
                img = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
                x = (56 - source.width) // 2
                y = (56 - source.height) // 2
                img.paste(source.convert("RGBA"), (x, y))
        except Exception:
            return None
        photo = ImageTk.PhotoImage(img)
        self._image_refs.append(photo)
        return photo

    def _item_photo(self, item: dict[str, str]) -> object | None:
        return self._thumbnail_icon(item) or self._shell_icon_photo(item) or self._draw_type_icon(item)

    def _show_item_menu(self, event: tk.Event, workspace_id: str, item_id: str) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        if self.on_open_item:
            item = self._find_item(workspace_id, item_id)
            if item:
                menu.add_command(label="打开", command=lambda: self.on_open_item(str(item["path"])))
        if self.on_remove_item:
            menu.add_command(label="从工作区移除", command=lambda: self.on_remove_item(workspace_id, item_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _find_item(self, workspace_id: str, item_id: str) -> dict[str, str] | None:
        for part in self.partitions:
            if str(part.get("id")) != workspace_id:
                continue
            for item in normalize_items(part.get("items")):
                if item["id"] == item_id:
                    return item
        return None

    def _group_key(self, part: dict[str, object]) -> str:
        return str(part.get("group_id") or part.get("id") or "")

    def _visible_groups(self) -> list[tuple[str, list[int], int]]:
        groups: dict[str, list[int]] = {}
        for index, part in enumerate(self.partitions):
            if bool(part.get("hidden", False)):
                continue
            groups.setdefault(self._group_key(part), []).append(index)

        result: list[tuple[str, list[int], int]] = []
        for key, indices in groups.items():
            active_id = self._active_groups.get(key)
            active_index = indices[0]
            if active_id:
                for index in indices:
                    if str(self.partitions[index].get("id")) == active_id:
                        active_index = index
                        break
            result.append((key, indices, active_index))
        return result

    def _group_style(self, group_indices: list[int], active_index: int) -> tuple[str, float]:
        if len(group_indices) > 1:
            base = self.partitions[group_indices[0]]
        else:
            base = self.partitions[active_index]
        return (
            str(base.get("color", DEFAULT_PANEL_COLOR)),
            _clamp_float(base.get("alpha"), DEFAULT_PANEL_ALPHA, 0.18, 0.95),
        )

    def _switch_group_tab(self, group_key: str, workspace_id: str) -> str:
        self._active_groups[group_key] = workspace_id
        self.show()
        return "break"

    def _bind_item(self, widget: tk.Widget, workspace_id: str, item: dict[str, str]) -> None:
        item_id = item["id"]
        path = item["path"]
        if self.on_open_item:
            widget.bind("<Double-Button-1>", lambda _event: self.on_open_item(path))
        widget.bind("<Button-3>", lambda event: self._show_item_menu(event, workspace_id, item_id))

    def _render_items(self, parent: tk.Frame, workspace_id: str, items: list[dict[str, str]], color: str, panel_width: int) -> None:
        grid = tk.Frame(parent, bg=color)
        grid.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 10))
        if not items:
            box = tk.Frame(grid, bg=color)
            box.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            hint = tk.Label(
                box,
                text="可通过面板菜单添加图标到此整理",
                fg="#ffffff",
                bg=color,
                font=("Segoe UI", 10),
                justify=tk.CENTER,
            )
            hint.pack(pady=(0, 14))

            add_folder = tk.Label(
                box,
                text="📁  添加文件夹",
                fg="#ffffff",
                bg="#26313a",
                font=("Segoe UI", 10),
                padx=24,
                pady=8,
                cursor="hand2",
                highlightbackground="#6f7b86",
                highlightthickness=1,
            )
            add_folder.pack(pady=(0, 10))
            add_folder.bind(
                "<Button-1>",
                lambda _event: self.on_workspace_action(workspace_id, "add_folder") if self.on_workspace_action else "break",
            )

            rules = tk.Label(
                box,
                text="设置整理规则",
                fg="#ffffff",
                bg="#26313a",
                font=("Segoe UI", 10),
                padx=28,
                pady=8,
                cursor="hand2",
                highlightbackground="#6f7b86",
                highlightthickness=1,
            )
            rules.pack()
            rules.bind(
                "<Button-1>",
                lambda _event: self.on_workspace_action(workspace_id, "rules") if self.on_workspace_action else "break",
            )
            return

        cell_w = 98
        cell_h = 112
        columns = max(1, int((max(140, panel_width) - 28) / cell_w))
        for col in range(columns):
            grid.columnconfigure(col, weight=0, minsize=cell_w)
        for idx, item in enumerate(items[:160]):
            cell = tk.Frame(grid, bg=color, width=cell_w, height=cell_h)
            cell.grid(row=idx // columns, column=idx % columns, padx=4, pady=6, sticky="n")
            cell.grid_propagate(False)
            photo = self._item_photo(item)
            if photo:
                icon = tk.Label(cell, image=photo, bg=color, width=58, height=58)
            else:
                icon = tk.Label(
                    cell,
                    text=self._item_icon(item.get("kind", "path")),
                    fg="#ffffff",
                    bg=color,
                    font=("Segoe UI", 9, "bold"),
                    width=7,
                    height=3,
                )
            icon.pack(pady=(2, 3))
            name = tk.Label(
                cell,
                text=self._short_name(str(item.get("name", "入口"))),
                fg="#ffffff",
                bg=color,
                font=("Segoe UI", 9),
                wraplength=90,
                justify=tk.CENTER,
            )
            name.pack()
            for widget in (cell, icon, name):
                self._bind_item(widget, workspace_id, item)

    def _bind_drag(self, widget: tk.Widget, index: int, tl: tk.Toplevel, width: int, height: int) -> None:
        widget.bind("<ButtonPress-1>", lambda event: self._start_drag(event, index, tl, width, height))
        widget.bind("<B1-Motion>", self._drag_motion)
        widget.bind("<ButtonRelease-1>", self._end_drag)

    def _bind_tab_drag(
        self,
        widget: tk.Widget,
        tab_index: int,
        active_index: int,
        tl: tk.Toplevel,
        width: int,
        height: int,
    ) -> None:
        widget.bind("<ButtonPress-1>", lambda event: self._start_tab_drag(event, tab_index, active_index, tl, width, height))
        widget.bind("<B1-Motion>", self._drag_motion)
        widget.bind("<ButtonRelease-1>", self._end_drag)

    def _bind_resize(self, widget: tk.Widget, index: int, tl: tk.Toplevel, width: int, height: int, mode: str) -> None:
        widget.bind("<ButtonPress-1>", lambda event: self._start_resize(event, index, tl, width, height, mode))
        widget.bind("<B1-Motion>", self._resize_motion)
        widget.bind("<ButtonRelease-1>", self._end_resize)

    def _start_drag(self, event: tk.Event, index: int, tl: tk.Toplevel, width: int, height: int) -> None:
        if bool(self.partitions[index].get("locked", True)) and not self.edit_mode:
            return None
        self._drag = {
            "index": index,
            "window": tl,
            "mouse_x": event.x_root,
            "mouse_y": event.y_root,
            "x": tl.winfo_x(),
            "y": tl.winfo_y(),
            "width": width,
            "height": height,
            "mode": "group",
        }
        return "break"

    def _start_tab_drag(
        self,
        event: tk.Event,
        tab_index: int,
        active_index: int,
        tl: tk.Toplevel,
        width: int,
        height: int,
    ) -> str | None:
        if bool(self.partitions[tab_index].get("locked", False)) and not self.edit_mode:
            return None
        self._drag = {
            "index": tab_index,
            "active_index": active_index,
            "window": tl,
            "mouse_x": event.x_root,
            "mouse_y": event.y_root,
            "x": tl.winfo_x(),
            "y": tl.winfo_y(),
            "width": width,
            "height": height,
            "mode": "tab",
        }
        return "break"

    def _tab_drag_started(self, event: tk.Event) -> bool:
        if not self._drag:
            return False
        return (
            abs(event.x_root - int(self._drag["mouse_x"])) > 8
            or abs(event.y_root - int(self._drag["mouse_y"])) > 8
        )

    def _create_tab_preview(self, index: int, width: int, height: int) -> tk.Toplevel:
        part = self.partitions[index]
        color = str(part.get("color", DEFAULT_PANEL_COLOR))
        preview = tk.Toplevel(self.root)
        preview.overrideredirect(True)
        preview.attributes("-topmost", True)
        preview.attributes("-alpha", 0.52)
        preview.configure(bg=color)
        frame = tk.Frame(preview, bg=color, highlightbackground="#ffffff", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            frame,
            text=str(part.get("name", "工作区")),
            fg="#ffffff",
            bg=color,
            font=("Segoe UI", 11, "bold"),
            anchor=tk.W,
        ).pack(fill=tk.X, padx=14, pady=10)
        tk.Label(
            frame,
            text="松开后拆成独立面板",
            fg="#d8d8d8",
            bg=color,
            font=("Segoe UI", 9),
        ).pack(expand=True)
        preview.geometry(f"{width}x{height}+{int(self._drag['x'])}+{int(self._drag['y'])}")
        return preview

    def _destroy_tab_preview(self) -> None:
        if not self._drag:
            return
        preview = self._drag.get("preview")
        if preview:
            try:
                preview.destroy()
            except tk.TclError:
                pass
            self._drag.pop("preview", None)

    def _drag_motion(self, event: tk.Event) -> None:
        if not self._drag:
            return None
        left, top, ww, hh = primary_work_area()
        width = int(self._drag["width"])
        height = int(self._drag["height"])
        raw_x = int(self._drag["x"] + event.x_root - self._drag["mouse_x"])
        raw_y = int(self._drag["y"] + event.y_root - self._drag["mouse_y"])
        self._drag["last_mouse_x"] = event.x_root
        self._drag["last_mouse_y"] = event.y_root
        if self._drag.get("mode") == "tab":
            if not self._tab_drag_started(event) and not self._drag.get("preview"):
                return "break"
            preview = self._drag.get("preview")
            if not preview:
                preview = self._create_tab_preview(int(self._drag["index"]), width, height)
                self._drag["preview"] = preview
            x = max(left, min(left + ww - width, raw_x))
            y = max(top, min(top + hh - height, raw_y))
            self._drag["preview_x"] = x
            self._drag["preview_y"] = y
            preview.geometry(f"{width}x{height}+{x}+{y}")
            return "break"

        tl: tk.Toplevel = self._drag["window"]
        x, y = self._snap_position(raw_x, raw_y, width, height, left, top, ww, hh, int(self._drag["index"]))
        x = max(left, min(left + ww - width, x))
        y = max(top, min(top + hh - height, y))
        self._set_paired_geometry(tl, f"{width}x{height}+{x}+{y}")
        return "break"

    def _end_drag(self, event: tk.Event) -> None:
        if not self._drag:
            return None
        index = int(self._drag["index"])
        left, top, ww, hh = primary_work_area()
        width = int(self._drag["width"])
        height = int(self._drag["height"])
        mouse_x = int(getattr(event, "x_root", self._drag.get("last_mouse_x", self._drag["mouse_x"])))
        mouse_y = int(getattr(event, "y_root", self._drag.get("last_mouse_y", self._drag["mouse_y"])))
        changed = False
        if self._drag.get("mode") == "tab":
            moved = bool(self._drag.get("preview")) or abs(mouse_x - int(self._drag["mouse_x"])) > 8 or abs(mouse_y - int(self._drag["mouse_y"])) > 8
            if moved:
                x = int(self._drag.get("preview_x", self._drag["x"] + mouse_x - int(self._drag["mouse_x"])))
                y = int(self._drag.get("preview_y", self._drag["y"] + mouse_y - int(self._drag["mouse_y"])))
                x = max(left, min(left + ww - width, x))
                y = max(top, min(top + hh - height, y))
                self._destroy_tab_preview()
                self._detach_tab(index, x, y, width, height, left, top, ww, hh)
                self._merge_by_pointer(index, event_x=mouse_x, event_y=mouse_y, left=left, top=top, ww=ww, hh=hh)
                changed = True
            else:
                self._destroy_tab_preview()
                active_index = int(self._drag.get("active_index", index))
                group_key = self._group_key(self.partitions[active_index])
                self._active_groups[group_key] = str(self.partitions[index].get("id"))
                self._drag = None
                self.show()
                return "break"
        else:
            tl: tk.Toplevel = self._drag["window"]
            x = max(left, min(left + ww - width, tl.winfo_x()))
            y = max(top, min(top + hh - height, tl.winfo_y()))
            self._apply_geometry(index, x, y, width, height, left, top, ww, hh)
            self._merge_by_pointer(index, event_x=mouse_x, event_y=mouse_y, left=left, top=top, ww=ww, hh=hh)
            changed = True
        self._drag = None
        if changed and self.on_layout_change:
            self.on_layout_change(self.partitions)
        if changed:
            self.root.after(0, self.show)
        return "break"

    def _start_resize(self, event: tk.Event, index: int, tl: tk.Toplevel, width: int, height: int, mode: str) -> None:
        if bool(self.partitions[index].get("locked", True)) and not self.edit_mode:
            return None
        self._drag = None
        self._resize = {
            "index": index,
            "window": tl,
            "mouse_x": event.x_root,
            "mouse_y": event.y_root,
            "x": tl.winfo_x(),
            "y": tl.winfo_y(),
            "width": width,
            "height": height,
            "mode": mode,
        }
        return "break"

    def _resize_motion(self, event: tk.Event) -> None:
        if not self._resize:
            return None
        tl: tk.Toplevel = self._resize["window"]
        left, top, ww, hh = primary_work_area()
        x = int(self._resize["x"])
        y = int(self._resize["y"])
        min_w = 240
        min_h = 150
        mode = str(self._resize.get("mode", "se"))
        raw_w = int(self._resize["width"])
        raw_h = int(self._resize["height"])
        if "e" in mode:
            raw_w += event.x_root - int(self._resize["mouse_x"])
        if "s" in mode:
            raw_h += event.y_root - int(self._resize["mouse_y"])
        width = max(min_w, min(left + ww - x, raw_w))
        height = max(min_h, min(top + hh - y, raw_h))
        width, height = self._snap_size(width, height, x, y, left, top, ww, hh, int(self._resize["index"]))
        width = max(min_w, min(left + ww - x, width))
        height = max(min_h, min(top + hh - y, height))
        self._set_paired_geometry(tl, f"{width}x{height}+{x}+{y}")
        return "break"

    def _end_resize(self, _event: tk.Event) -> None:
        if not self._resize:
            return None
        tl: tk.Toplevel = self._resize["window"]
        index = int(self._resize["index"])
        left, top, ww, hh = primary_work_area()
        self._apply_geometry(index, tl.winfo_x(), tl.winfo_y(), tl.winfo_width(), tl.winfo_height(), left, top, ww, hh)
        self._resize = None
        if self.on_layout_change:
            self.on_layout_change(self.partitions)
        self.root.after(0, self.show)
        return "break"

    def _apply_geometry(
        self,
        index: int,
        x: int,
        y: int,
        width: int,
        height: int,
        left: int,
        top: int,
        ww: int,
        hh: int,
    ) -> None:
        group_key = self._group_key(self.partitions[index])
        for i, part in enumerate(self.partitions):
            if self._group_key(part) != group_key:
                continue
            updated = dict(part)
            updated["rx"] = round((x - left) / ww, 4) if ww else 0
            updated["ry"] = round((y - top) / hh, 4) if hh else 0
            updated["rw"] = round(width / ww, 4) if ww else updated.get("rw", 0.25)
            if not bool(updated.get("collapsed", False)):
                updated["rh"] = round(height / hh, 4) if hh else updated.get("rh", 0.2)
            self.partitions[i] = updated

    def _detach_tab(
        self,
        index: int,
        x: int,
        y: int,
        width: int,
        height: int,
        left: int,
        top: int,
        ww: int,
        hh: int,
    ) -> None:
        old_key = self._group_key(self.partitions[index])
        updated = dict(self.partitions[index])
        updated["group_id"] = ""
        updated["rx"] = round((x - left) / ww, 4) if ww else 0
        updated["ry"] = round((y - top) / hh, 4) if hh else 0
        updated["rw"] = round(width / ww, 4) if ww else updated.get("rw", 0.25)
        if not bool(updated.get("collapsed", False)):
            updated["rh"] = round(height / hh, 4) if hh else updated.get("rh", 0.2)
        self.partitions[index] = updated
        if self._active_groups.get(old_key) == str(updated.get("id")):
            self._active_groups.pop(old_key, None)

    def _merge_by_pointer(
        self,
        index: int,
        *,
        event_x: int,
        event_y: int,
        left: int,
        top: int,
        ww: int,
        hh: int,
    ) -> bool:
        active = self.partitions[index]
        active_key = self._group_key(active)
        for i, part in enumerate(self.partitions):
            if i == index or bool(part.get("hidden", False)):
                continue
            other_key = self._group_key(part)
            if other_key == active_key:
                continue
            ox = int(left + float(part.get("rx", 0)) * ww)
            oy = int(top + float(part.get("ry", 0)) * hh)
            ow = max(120, int(float(part.get("rw", 0.25)) * ww))
            oh = 62 if bool(part.get("collapsed", False)) else max(88, int(float(part.get("rh", 0.25)) * hh))
            if ox <= event_x <= ox + ow and oy <= event_y <= oy + oh:
                target_key = other_key or str(part.get("id"))
                for p_index, p in enumerate(self.partitions):
                    if self._group_key(p) not in {active_key, other_key}:
                        continue
                    updated = dict(p)
                    updated["group_id"] = target_key
                    updated["rx"] = round((ox - left) / ww, 4) if ww else 0
                    updated["ry"] = round((oy - top) / hh, 4) if hh else 0
                    updated["rw"] = round(ow / ww, 4) if ww else updated.get("rw", 0.25)
                    if not bool(updated.get("collapsed", False)):
                        updated["rh"] = round(oh / hh, 4) if hh else updated.get("rh", 0.2)
                    updated["color"] = DEFAULT_PANEL_COLOR
                    updated["alpha"] = DEFAULT_PANEL_ALPHA
                    self.partitions[p_index] = updated
                self._active_groups[target_key] = str(active.get("id"))
                return True
        return False

    def _snap_position(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        left: int,
        top: int,
        ww: int,
        hh: int,
        active_index: int,
    ) -> tuple[int, int]:
        snap_x = [left, left + ww // 2 - width // 2, left + ww - width]
        snap_y = [top, top + hh // 2 - height // 2, top + hh - height]
        for i, part in enumerate(self.partitions):
            if i == active_index:
                continue
            px = int(left + float(part.get("rx", 0)) * ww)
            py = int(top + float(part.get("ry", 0)) * hh)
            pw = max(120, int(float(part.get("rw", 0.25)) * ww))
            ph = max(88, int(float(part.get("rh", 0.25)) * hh))
            snap_x.extend([px, px + pw, px - width, px + pw - width])
            snap_y.extend([py, py + ph, py - height, py + ph - height])

        for sx in snap_x:
            if abs(x - sx) <= self.snap_px:
                x = sx
                break
        for sy in snap_y:
            if abs(y - sy) <= self.snap_px:
                y = sy
                break
        return x, y

    def _snap_size(
        self,
        width: int,
        height: int,
        x: int,
        y: int,
        left: int,
        top: int,
        ww: int,
        hh: int,
        active_index: int,
    ) -> tuple[int, int]:
        right = x + width
        bottom = y + height
        snap_right = [left + ww]
        snap_bottom = [top + hh]
        for i, part in enumerate(self.partitions):
            if i == active_index:
                continue
            px = int(left + float(part.get("rx", 0)) * ww)
            py = int(top + float(part.get("ry", 0)) * hh)
            pw = max(120, int(float(part.get("rw", 0.25)) * ww))
            ph = max(88, int(float(part.get("rh", 0.25)) * hh))
            snap_right.extend([px, px + pw])
            snap_bottom.extend([py, py + ph])

        for sx in snap_right:
            if abs(right - sx) <= self.snap_px:
                width = sx - x
                break
        for sy in snap_bottom:
            if abs(bottom - sy) <= self.snap_px:
                height = sy - y
                break
        return width, height

    def show(self) -> None:
        self.hide()
        left, top, ww, hh = primary_work_area()
        for group_key, group_indices, index in self._visible_groups():
            p = self.partitions[index]
            rx = float(p.get("rx", 0.0))
            ry = float(p.get("ry", 0.0))
            rw = float(p.get("rw", 0.25))
            rh = float(p.get("rh", 0.25))
            name = str(p.get("name", "工作区"))
            workspace_id = str(p.get("id"))
            items = normalize_items(p.get("items"))
            color, group_alpha = self._group_style(group_indices, index)
            locked = bool(p.get("locked", True))
            collapsed = bool(p.get("collapsed", False))
            can_drag = self.edit_mode or not locked
            alpha = self.edit_alpha if self.edit_mode else group_alpha
            x = int(left + rx * ww)
            y = int(top + ry * hh)
            w = max(120, int(rw * ww))
            h = 38 if collapsed else max(88, int(rh * hh))

            geometry = f"{w}x{h}+{x}+{y}"
            backdrop: tk.Toplevel | None = tk.Toplevel(self.root)
            backdrop.overrideredirect(True)
            backdrop.attributes("-topmost", True)
            backdrop.attributes("-alpha", alpha)
            backdrop.geometry(geometry)
            backdrop.configure(bg=color)
            if can_drag:
                backdrop.configure(cursor="fleur")

            tl = tk.Toplevel(self.root)
            tl.overrideredirect(True)
            tl.attributes("-topmost", True)
            tl.geometry(geometry)
            tl.configure(bg=TRANSPARENT_COLOR)
            ui_bg = TRANSPARENT_COLOR
            try:
                tl.attributes("-transparentcolor", TRANSPARENT_COLOR)
            except tk.TclError:
                ui_bg = color
                try:
                    backdrop.destroy()
                except tk.TclError:
                    pass
                backdrop = None
                tl.attributes("-alpha", alpha)
                tl.configure(bg=color)
            setattr(tl, "_panel_backdrop", backdrop)
            if can_drag:
                tl.configure(cursor="fleur")

            border = tk.Frame(tl, bg=ui_bg, padx=0 if collapsed else 2, pady=0 if collapsed else 2)
            border.pack(fill=tk.BOTH, expand=True)
            inner = tk.Frame(border, bg=ui_bg, cursor="fleur" if can_drag else "")
            inner.pack(fill=tk.BOTH, expand=True)
            self._hook_drop(tl, workspace_id)

            header = tk.Frame(inner, bg=ui_bg, height=38, cursor="fleur" if can_drag else "")
            header.pack(fill=tk.X)
            collapse_button = tk.Label(
                header,
                text="⌄" if collapsed else "⌃",
                fg="#ffffff",
                bg=ui_bg,
                font=("Segoe UI", 12, "bold"),
                width=3,
                cursor="hand2",
            )
            collapse_button.pack(side=tk.LEFT, padx=(8, 0), pady=7)
            collapse_button.bind("<Button-1>", lambda _event, wid=workspace_id: self._toggle_collapsed(wid))
            lock_button = tk.Label(
                header,
                text="🔒" if locked else "🔓",
                fg="#ffffff",
                bg=ui_bg,
                font=("Segoe UI", 10, "bold"),
                width=3,
                cursor="hand2",
            )
            lock_button.pack(side=tk.LEFT, padx=(2, 0), pady=7)
            lock_button.bind("<Button-1>", lambda _event, wid=workspace_id: self._toggle_lock(wid))
            title = tk.Label(
                header,
                text=name,
                fg="#f0f0f0",
                bg=ui_bg,
                font=("Segoe UI", 11, "bold"),
                cursor="fleur" if can_drag else "",
            )
            title.pack(side=tk.LEFT, padx=(12, 4), pady=8)
            title.bind(
                "<Double-Button-1>",
                lambda _event, label=title, wid=workspace_id, cur=name: self._start_inline_rename(label, wid, cur),
            )
            count = tk.Label(
                header,
                text=f"{len(items)} 项",
                fg="#ded7ea",
                bg=ui_bg,
                font=("Segoe UI", 9),
                cursor="fleur" if can_drag else "",
            )
            count.pack(side=tk.RIGHT, padx=10)
            more_button = tk.Label(
                header,
                text="...",
                fg="#ffffff",
                bg=ui_bg,
                font=("Segoe UI", 12, "bold"),
                width=4,
                cursor="hand2",
            )
            more_button.pack(side=tk.RIGHT, padx=(0, 4), pady=6)
            more_button.bind("<Button-1>", lambda event, wid=workspace_id: self._show_workspace_menu(event, wid))
            delete_button = tk.Label(
                header,
                text="🗑",
                fg="#ffffff",
                bg=ui_bg,
                font=("Segoe UI", 12),
                width=3,
                cursor="hand2",
            )
            delete_button.pack(side=tk.RIGHT, padx=(0, 2), pady=6)
            delete_button.bind(
                "<Button-1>",
                lambda _event, wid=workspace_id: self.on_workspace_action(wid, "delete") if self.on_workspace_action else "break",
            )
            add_button = tk.Label(
                header,
                text="+",
                fg="#ffffff",
                bg=ui_bg,
                font=("Segoe UI", 16, "bold"),
                width=3,
                cursor="hand2",
            )
            add_button.pack(side=tk.RIGHT, padx=(0, 2), pady=3)
            add_button.bind(
                "<Button-1>",
                lambda _event, wid=workspace_id: self.on_workspace_action(wid, "new") if self.on_workspace_action else "break",
            )

            tabs = tk.Frame(inner, bg=ui_bg, height=28, cursor="fleur" if can_drag else "")
            if not collapsed:
                tabs.pack(fill=tk.X, padx=10, pady=(6, 0))
            tab_widgets: list[tk.Widget] = []
            if not collapsed:
                for tab_index in group_indices:
                    tab_part = self.partitions[tab_index]
                    is_active = tab_index == index
                    tab_label = tk.Label(
                        tabs,
                        text=str(tab_part.get("name", "工作区")),
                        fg="#ffffff" if is_active else "#cbc4d8",
                        bg=ui_bg,
                        font=("Segoe UI", 9, "bold" if is_active else "normal"),
                        cursor="hand2" if len(group_indices) > 1 else ("fleur" if can_drag else ""),
                    )
                    tab_label.pack(side=tk.LEFT, padx=(0, 14))
                    tab_widgets.append(tab_label)
                    if len(group_indices) > 1:
                        self._bind_tab_drag(tab_label, tab_index, index, tl, w, h)

            draggable_tabs = [] if len(group_indices) > 1 else tab_widgets
            drag_widgets = [tl, border, inner, header, title, count, tabs, *draggable_tabs]
            if backdrop is not None:
                drag_widgets.append(backdrop)
            if self.edit_mode and not collapsed:
                hint = tk.Label(
                    inner,
                    text="拖动调整位置，靠近边缘会吸附，松开自动保存",
                    fg="#c8c1d6",
                    bg=ui_bg,
                    font=("Segoe UI", 9),
                    justify=tk.CENTER,
                    cursor="fleur" if can_drag else "",
                )
                hint.pack(expand=True, pady=(4, 8))
                drag_widgets.append(hint)
            elif not collapsed:
                self._render_items(inner, workspace_id, items, ui_bg, w)

            tl.update_idletasks()
            if can_drag:
                for widget in drag_widgets:
                    self._bind_drag(widget, index, tl, w, h)
                if not collapsed:
                    handle_bg = "#403844" if ui_bg == TRANSPARENT_COLOR else color
                    right_handle = tk.Frame(inner, bg=handle_bg, width=7, cursor="sb_h_double_arrow")
                    right_handle.place(relx=1.0, rely=0, relheight=1.0, anchor=tk.NE)
                    self._bind_resize(right_handle, index, tl, w, h, "e")
                    bottom_handle = tk.Frame(inner, bg=handle_bg, height=7, cursor="sb_v_double_arrow")
                    bottom_handle.place(relx=0, rely=1.0, relwidth=1.0, anchor=tk.SW)
                    self._bind_resize(bottom_handle, index, tl, w, h, "s")
                    handle = tk.Label(
                        inner,
                        text="◢",
                        fg="#ffffff",
                        bg=handle_bg,
                        font=("Segoe UI", 12, "bold"),
                        cursor="size_nw_se",
                    )
                    handle.place(relx=1.0, rely=1.0, anchor=tk.SE, x=-6, y=-4)
                    self._bind_resize(handle, index, tl, w, h, "se")
            if backdrop is not None:
                self._windows.append(backdrop)
            self._windows.append(tl)
            if self._pending_rename_id == workspace_id:
                self._pending_rename_id = None
                self.root.after(80, lambda label=title, wid=workspace_id, cur=name: self._start_inline_rename(label, wid, cur))
