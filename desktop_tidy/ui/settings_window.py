"""Qt settings surface for the desktop panel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.domain.models import Configuration, InvalidConfiguration, validate_configuration
from desktop_tidy.persistence.ui_preferences import UiPreferences
from desktop_tidy.services.screens import ScreenInfo, available_screens

_SECTIONS = ["基础设置", "面板管理", "桌面整理", "面板外观"]
_OPACITY_MIN = 0.10
_OPACITY_MAX = 1.00
_COLOR_SWATCHES = [
    "#000000",
    "#111827",
    "#2D2A32",
    "#4B5563",
    "#6D4C7D",
    "#8B3A5D",
    "#25636B",
    "#7C6A46",
]
_EXTENSION_PRESETS = {
    "图片": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"],
    "文档": [
        ".pdf",
        ".doc",
        ".docx",
        ".rtf",
        ".odt",
        ".wps",
        ".xls",
        ".xlsx",
        ".csv",
        ".ppt",
        ".pptx",
        ".txt",
        ".md",
    ],
    "压缩包": [".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".iso"],
    "应用": [".lnk", ".url", ".exe", ".msi"],
    "代码": [".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".sql"],
    "音频": [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg"],
    "视频": [".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm"],
}
_DEFAULT_RULE_ROLES = {
    "rule-folders": "folders",
    "rule-documents": "documents",
    "rule-images": "images",
    "rule-archives": "archives",
    "rule-apps": "apps",
    "rule-other": "other",
}
_SECTIONS = _SECTIONS + ["面板历史", "功能面板", "诊断与恢复", "其他"]


class ScreenLayoutWidget(QWidget):
    screen_selected = Signal(str)
    identify_requested = Signal()

    def __init__(
        self,
        screens: list[ScreenInfo],
        selected_screen_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._screens = screens
        self._selected_screen_id = selected_screen_id
        self._buttons: dict[str, QPushButton] = {}
        self.setMinimumSize(420, 220)
        self.resize(420, 220)
        self._identify_button = QPushButton("识别", self)
        self._identify_button.clicked.connect(self.identify_requested.emit)
        self._rebuild_buttons()

    @property
    def buttons(self) -> dict[str, QPushButton]:
        return self._buttons

    def set_selected_screen(self, screen_id: str) -> None:
        self._selected_screen_id = screen_id
        self._sync_button_styles()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._layout_buttons()

    def _rebuild_buttons(self) -> None:
        for button in self._buttons.values():
            button.setParent(None)
            button.deleteLater()
        self._buttons = {}
        for index, screen in enumerate(self._screens, start=1):
            button = QPushButton(str(index), self)
            button.setCheckable(True)
            button.setToolTip(screen.label)
            button.clicked.connect(
                lambda _checked=False, value=screen.screen_id: self._select_screen(value)
            )
            self._buttons[screen.screen_id] = button
        self._layout_buttons()
        self._sync_button_styles()

    def _select_screen(self, screen_id: str) -> None:
        self._selected_screen_id = screen_id
        self._sync_button_styles()
        self.screen_selected.emit(screen_id)

    def _layout_buttons(self) -> None:
        if not self._screens:
            return
        geometries = [screen.geometry for screen in self._screens]
        min_x = min(rect.x() for rect in geometries)
        min_y = min(rect.y() for rect in geometries)
        max_x = max(rect.x() + rect.width() for rect in geometries)
        max_y = max(rect.y() + rect.height() for rect in geometries)
        total_width = max(1, max_x - min_x)
        total_height = max(1, max_y - min_y)
        margin = 16
        action_height = 42
        available_width = max(1, self.width() - margin * 2)
        available_height = max(1, self.height() - margin * 2 - action_height)
        scale = min(available_width / total_width, available_height / total_height)
        used_width = total_width * scale
        used_height = total_height * scale
        offset_x = margin + int((available_width - used_width) / 2)
        offset_y = margin + int((available_height - used_height) / 2)
        for screen in self._screens:
            rect = screen.geometry
            button = self._buttons[screen.screen_id]
            button.setGeometry(
                offset_x + int((rect.x() - min_x) * scale),
                offset_y + int((rect.y() - min_y) * scale),
                max(58, int(rect.width() * scale)),
                max(44, int(rect.height() * scale)),
            )
        self._identify_button.setGeometry(
            max(margin, self.width() - 116),
            max(margin, self.height() - 40),
            92,
            30,
        )

    def _sync_button_styles(self) -> None:
        for screen_id, button in self._buttons.items():
            checked = screen_id == self._selected_screen_id
            button.setChecked(checked)
            background = "#934A69" if checked else "#2F2F2F"
            button.setStyleSheet(
                f"QPushButton {{ color: #ffffff; background: {background}; "
                "border: 1px solid #555; border-radius: 8px; font-size: 28px; }}"
                "QPushButton:hover { border-color: #d7b0c2; }"
            )


class ExtensionTagEditor(QWidget):
    """Small preset-and-chip editor for classification rule extensions."""

    def __init__(self, extensions: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._extensions: list[str] = []
        self._chip_widgets: list[QPushButton] = []
        self._preset_combo = QComboBox(self)
        self._preset_combo.addItem("选择类型", "")
        for name in _EXTENSION_PRESETS:
            self._preset_combo.addItem(name, name)
        self._preset_button = QPushButton("添加预设", self)
        self._custom_input = QLineEdit(self)
        self._custom_input.setPlaceholderText(".ext")
        self._custom_button = QPushButton("添加", self)
        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(self._preset_combo)
        top.addWidget(self._preset_button)
        top.addWidget(self._custom_input)
        top.addWidget(self._custom_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addLayout(self._chips_row)

        self._preset_button.clicked.connect(self._apply_selected_preset)
        self._custom_button.clicked.connect(self._add_custom_extension)
        self._custom_input.returnPressed.connect(self._add_custom_extension)
        self.set_extensions(extensions)

    def extensions(self) -> list[str]:
        return list(self._extensions)

    def set_extensions(self, extensions: list[str]) -> None:
        self._extensions = []
        for extension in extensions:
            self.add_extension(extension)
        self._rebuild_chips()

    def apply_preset(self, name: str) -> None:
        for extension in _EXTENSION_PRESETS.get(name, []):
            self.add_extension(extension)

    def add_extension(self, extension: str) -> None:
        normalized = extension.strip().lower()
        if not normalized:
            return
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        if normalized not in self._extensions:
            self._extensions.append(normalized)
            self._rebuild_chips()

    def remove_extension(self, extension: str) -> None:
        normalized = extension.strip().lower()
        self._extensions = [entry for entry in self._extensions if entry != normalized]
        self._rebuild_chips()

    def _apply_selected_preset(self) -> None:
        name = str(self._preset_combo.currentData() or "")
        if name:
            self.apply_preset(name)

    def _add_custom_extension(self) -> None:
        self.add_extension(self._custom_input.text())
        self._custom_input.clear()

    def _rebuild_chips(self) -> None:
        for chip in self._chip_widgets:
            self._chips_row.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chip_widgets = []
        for extension in self._extensions:
            chip = QPushButton(extension, self)
            chip.setToolTip("点击移除此后缀")
            chip.setStyleSheet(
                "QPushButton { color: #ffffff; background: #3b3b3b; "
                "border: 1px solid #555; border-radius: 8px; padding: 2px 8px; }"
                "QPushButton:hover { background: #555; }"
            )
            chip.clicked.connect(lambda _checked=False, value=extension: self.remove_extension(value))
            self._chips_row.addWidget(chip)
            self._chip_widgets.append(chip)


class HistoryCardWidget(QFrame):
    def __init__(self, snapshot: object, icon: QIcon, preview_size: QSize, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.snapshot_id = str(getattr(snapshot, "id", "") or "")
        self.restore_button = QPushButton("恢复", self)
        self.capture_button = QPushButton("保存截图", self)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #242424; border: 1px solid #444; border-radius: 8px; }"
            "QLabel { color: #ffffff; background: transparent; }"
        )
        preview = QLabel(self)
        pixmap = icon.pixmap(preview_size)
        preview.setPixmap(pixmap)
        preview.setFixedSize(preview_size)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(
            f"{getattr(snapshot, 'created_at', '')}\n"
            f"{getattr(snapshot, 'reason', '')}\n"
            f"{getattr(snapshot, 'group_count', 0)}组 / {getattr(snapshot, 'tab_count', 0)}标签",
            self,
        )
        actions = QHBoxLayout()
        actions.addWidget(self.capture_button)
        actions.addWidget(self.restore_button)
        layout = QVBoxLayout(self)
        layout.addWidget(preview)
        layout.addWidget(text)
        layout.addLayout(actions)


class SettingsWindow(QWidget):
    config_saved = Signal()
    validation_failed = Signal(str)
    restore_desktop_requested = Signal()
    add_item_panel_requested = Signal()
    add_item_tab_requested = Signal()
    delete_item_panel_requested = Signal(str)
    delete_item_tab_requested = Signal(str)
    identify_screens_requested = Signal()
    add_widget_panel_requested = Signal(str)
    history_restore_requested = Signal(str)
    history_capture_preview_requested = Signal(str)
    ui_preferences_changed = Signal()
    management_metadata_changed = Signal()
    diagnostics_refresh_requested = Signal()
    diagnostics_restore_icons_requested = Signal()
    diagnostics_refresh_takeover_requested = Signal()
    diagnostics_open_logs_requested = Signal()
    diagnostics_export_requested = Signal()

    def __init__(
        self,
        config: Configuration,
        *,
        group_id: str | None = None,
        screen_infos: list[ScreenInfo] | None = None,
        screen_options: list[tuple[str, str]] | None = None,
        ui_preferences: UiPreferences | None = None,
        takeover_confirmation: Callable[[], bool] | None = None,
        delete_confirmation: Callable[[str, str], tuple[bool, bool]] | None = None,
        rename_prompt: Callable[[str, str], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._group_id = group_id or config.panel_groups[0].id
        if screen_infos is None and screen_options is not None:
            screen_infos = [
                ScreenInfo(screen_id, label, QRect(index * 1280, 0, 1280, 720))
                for index, (screen_id, label) in enumerate(screen_options)
            ]
        self._screen_infos = screen_infos or available_screens()
        self._selected_screen_id = self._target_group(config).screen_id or config.desktop.primary_screen_id
        self._screen_layout_buttons: dict[str, QPushButton] = {}
        self._rule_extension_editors: dict[str, ExtensionTagEditor] = {}
        self._color_swatch_buttons: dict[str, QPushButton] = {}
        self._selected_color = self._target_group(config).appearance.background_color
        self._ui_preferences = ui_preferences or UiPreferences()
        self._takeover_confirmation = takeover_confirmation
        self._delete_confirmation = delete_confirmation
        self._rename_prompt = rename_prompt
        self._management_selection_kind = "panel"
        self._selected_tab_id = ""
        self.setWindowTitle("设置")
        self.resize(820, 600)

        self._section_list = QListWidget(self)
        for name in _SECTIONS:
            self._section_list.addItem(QListWidgetItem(name))
        self._section_list.setFixedWidth(140)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._build_basic_page())
        self._pages.addWidget(self._build_panel_management_page())
        self._pages.addWidget(self._build_rules_page())
        self._pages.addWidget(self._build_appearance_page())
        self._pages.addWidget(self._build_history_page())
        self._pages.addWidget(self._build_widgets_page())
        self._pages.addWidget(self._build_diagnostics_page())
        self._pages.addWidget(self._build_other_page())

        self._section_list.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._section_list.setCurrentRow(0)

        save_button = QPushButton("保存", self)
        save_button.clicked.connect(self._save)

        body = QHBoxLayout()
        body.addWidget(self._section_list)
        body.addWidget(self._pages, stretch=1)

        layout = QVBoxLayout(self)
        layout.addLayout(body)
        layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignRight)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.hide()
        event.ignore()

    def _target_group(self, config: Configuration | None = None):
        config = config or self._config
        for group in config.panel_groups:
            if group.id == self._group_id:
                return group
        return config.panel_groups[0]

    def set_configuration(
        self,
        config: Configuration,
        *,
        group_id: str | None = None,
    ) -> None:
        self._config = config
        if group_id is not None:
            self._group_id = group_id
        self._desktop_path_edit.setText(config.desktop.path)
        self._takeover_checkbox.setChecked(config.desktop.takeover_enabled)
        self._startup_checkbox.setChecked(config.desktop.startup_enabled)
        self._update_takeover_status_label()
        self._selected_screen_id = self._target_group(config).screen_id or config.desktop.primary_screen_id
        self._reload_screen_layout(config)
        self._reload_panel_management(config)
        self._reload_rules_editor()
        group = self._target_group(config)
        self._selected_color = group.appearance.background_color
        self._sync_color_swatch_states()
        opacity = group.appearance.background_opacity
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(self._opacity_to_slider(opacity))
        self._opacity_slider.blockSignals(False)
        if hasattr(self, "_opacity_spinbox"):
            self._opacity_spinbox.blockSignals(True)
            self._opacity_spinbox.setValue(self._opacity_slider.value())
            self._opacity_spinbox.blockSignals(False)

    def visible_section_names(self) -> list[str]:
        return list(_SECTIONS)

    def all_text(self) -> str:
        parts: list[str] = []
        for index in range(self._section_list.count()):
            parts.append(self._section_list.item(index).text())
        for widget in self.findChildren(QWidget):
            if isinstance(widget, QLineEdit):
                parts.append(widget.text())
                parts.append(widget.placeholderText())
            elif isinstance(widget, (QLabel, QPushButton, QCheckBox)):
                parts.append(widget.text())
            elif isinstance(widget, QComboBox):
                parts.append(widget.currentText())
            elif isinstance(widget, QPlainTextEdit):
                parts.append(widget.toPlainText())
        if hasattr(self, "_rules_table"):
            for row in range(self._rules_table.rowCount()):
                for column in range(self._rules_table.columnCount()):
                    item = self._rules_table.item(row, column)
                    if item is not None:
                        parts.append(item.text())
        return "\n".join(part for part in parts if part)

    def panel_background_color(self) -> str:
        return self._selected_color

    def panel_background_opacity(self) -> float:
        return self._slider_to_opacity(self._opacity_slider.value())

    def panel_opacity_minimum(self) -> float:
        return _OPACITY_MIN

    def panel_opacity_maximum(self) -> float:
        return _OPACITY_MAX

    def selected_screen_id(self) -> str:
        return self._selected_screen_id or "primary"

    def selected_group_id(self) -> str:
        return self._group_id

    def _build_basic_page(self) -> QWidget:
        page = QWidget(self)
        self._basic_page = page
        form = QFormLayout(page)
        self._desktop_path_edit = QLineEdit(self._config.desktop.path, page)
        browse = QPushButton("选择文件夹", page)
        browse.clicked.connect(self._browse_desktop_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self._desktop_path_edit)
        path_row.addWidget(browse)
        form.addRow("桌面路径", path_row)
        self._screen_layout_widget = ScreenLayoutWidget(
            self._screen_infos,
            self.selected_screen_id(),
            page,
        )
        self._screen_layout_widget.screen_selected.connect(self._select_screen)
        self._screen_layout_widget.identify_requested.connect(
            self.identify_screens_requested.emit
        )
        self._screen_layout_buttons = self._screen_layout_widget.buttons
        form.addRow("显示器布局", self._screen_layout_widget)
        self._takeover_checkbox = QCheckBox("启用桌面接管", page)
        self._takeover_checkbox.setChecked(self._config.desktop.takeover_enabled)
        form.addRow(self._takeover_checkbox)
        self._startup_checkbox = QCheckBox("开机启动", page)
        self._startup_checkbox.setChecked(self._config.desktop.startup_enabled)
        form.addRow(self._startup_checkbox)
        self._takeover_status_label = QLabel("", page)
        form.addRow("接管状态", self._takeover_status_label)
        self._restore_desktop_button = QPushButton("恢复桌面图标", page)
        self._restore_desktop_button.clicked.connect(self.restore_desktop_requested.emit)
        form.addRow(self._restore_desktop_button)
        self._update_takeover_status_label()
        return page

    def _build_panel_management_page(self) -> QWidget:
        page = QWidget(self)
        self._panel_management_page = page
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        left.addWidget(QLabel("面板", page))
        self._panel_group_list = QListWidget(page)
        self._panel_group_list.currentRowChanged.connect(self._select_panel_group_row)
        self._panel_group_list.itemDoubleClicked.connect(self._rename_panel_from_item)
        left.addWidget(self._panel_group_list, stretch=1)
        layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        self._management_add_button = QPushButton("+", page)
        self._management_add_button.setToolTip("新建面板或标签")
        self._management_delete_button = QPushButton("删除", page)
        self._management_delete_button.setToolTip("删除当前选中的面板或标签")
        self._management_add_button.clicked.connect(self._request_management_add)
        self._management_delete_button.clicked.connect(self._request_management_delete)
        actions = QHBoxLayout()
        actions.addWidget(self._management_add_button)
        actions.addWidget(self._management_delete_button)
        actions.addStretch(1)
        right.addLayout(actions)
        self._panel_summary_label = QLabel("", page)
        right.addWidget(self._panel_summary_label)
        right.addWidget(QLabel("预览", page))
        self._panel_preview_container = QWidget(page)
        self._panel_preview_layout = QGridLayout(self._panel_preview_container)
        self._panel_preview_group_buttons: dict[str, QPushButton] = {}
        self._panel_preview_tab_buttons: dict[str, QPushButton] = {}
        right.addWidget(self._panel_preview_container)
        right.addWidget(QLabel("标签", page))
        self._panel_tab_list = QListWidget(page)
        self._panel_tab_list.currentRowChanged.connect(self._select_panel_tab_row)
        self._panel_tab_list.itemClicked.connect(self._select_panel_tab_item)
        self._panel_tab_list.itemDoubleClicked.connect(self._rename_tab_from_item)
        right.addWidget(self._panel_tab_list, stretch=1)
        layout.addLayout(right, stretch=2)
        self._reload_panel_management(self._config)
        return page

    def _reload_screen_layout(self, config: Configuration) -> None:
        if not hasattr(self, "_screen_layout_widget"):
            return
        current = self._selected_screen_id or self._target_group(config).screen_id or config.desktop.primary_screen_id
        valid_ids = {screen.screen_id for screen in self._screen_infos}
        if current not in valid_ids:
            current = "primary"
        self._selected_screen_id = current
        self._screen_layout_widget.set_selected_screen(current)
        self._screen_layout_buttons = self._screen_layout_widget.buttons

    def _select_screen(self, screen_id: str) -> None:
        self._selected_screen_id = screen_id
        if hasattr(self, "_screen_layout_widget"):
            self._screen_layout_widget.set_selected_screen(screen_id)

    def _reload_panel_management(self, config: Configuration) -> None:
        if not hasattr(self, "_panel_group_list"):
            return
        self._panel_group_list.blockSignals(True)
        self._panel_group_list.clear()
        self._panel_group_count_labels = {}
        selected_row = 0
        for index, group in enumerate(config.panel_groups):
            item = QListWidgetItem(group.name or f"面板 {index + 1}")
            item.setSizeHint(QSize(220, 34))
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            self._panel_group_list.addItem(item)
            row_widget = QWidget(self._panel_group_list)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 2, 8, 2)
            row_layout.addWidget(QLabel(item.text(), row_widget))
            row_layout.addStretch(1)
            count_label = QLabel(str(len(group.tab_ids)), row_widget)
            count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(count_label)
            self._panel_group_list.setItemWidget(item, row_widget)
            self._panel_group_count_labels[group.id] = count_label
            if group.id == self._group_id:
                selected_row = index
        self._panel_group_list.setCurrentRow(selected_row)
        self._panel_group_list.blockSignals(False)
        self._rebuild_panel_preview()
        self._sync_panel_detail()

    def _select_panel_group_row(self, row: int) -> None:
        item = self._panel_group_list.item(row)
        if item is None:
            return
        group_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if group_id:
            self._group_id = group_id
            self._management_selection_kind = "panel"
            self._selected_tab_id = ""
            self._selected_screen_id = self._target_group().screen_id or self.selected_screen_id()
            self._sync_panel_detail()

    def _select_panel_tab_row(self, row: int) -> None:
        item = self._panel_tab_list.item(row)
        if item is None:
            return
        self._select_panel_tab_item(item)

    def _select_panel_tab_item(self, item: QListWidgetItem) -> None:
        tab_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if tab_id:
            self._selected_tab_id = tab_id
            self._management_selection_kind = "tab"

    def _sync_panel_detail(self) -> None:
        if not hasattr(self, "_panel_tab_list"):
            return
        group = self._target_group()
        tabs_by_id = {tab.id: tab for tab in self._config.panel_tabs}
        self._panel_summary_label.setText(f"位置：{self._screen_label(group.screen_id)}")
        self._panel_tab_list.blockSignals(True)
        self._panel_tab_list.clear()
        for tab_id in group.tab_ids:
            tab = tabs_by_id.get(tab_id)
            if tab is None:
                continue
            marker = "当前 · " if tab.id == group.active_tab_id else ""
            item = QListWidgetItem(f"{marker}{tab.name}")
            item.setData(Qt.ItemDataRole.UserRole, tab.id)
            self._panel_tab_list.addItem(item)
        if self._panel_tab_list.count():
            active_row = max(0, group.tab_ids.index(group.active_tab_id))
            self._panel_tab_list.setCurrentRow(active_row)
            self._selected_tab_id = group.active_tab_id
        self._panel_tab_list.blockSignals(False)
        self._rebuild_panel_preview()

    def _screen_label(self, screen_id: str) -> str:
        for screen in self._screen_infos:
            if screen.screen_id == screen_id:
                return "主屏" if screen_id == "primary" else screen.label
        return "主屏" if screen_id == "primary" else screen_id

    def _rebuild_panel_preview(self) -> None:
        if not hasattr(self, "_panel_preview_layout"):
            return
        while self._panel_preview_layout.count():
            item = self._panel_preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._panel_preview_group_buttons = {}
        self._panel_preview_tab_buttons = {}
        tabs_by_id = {tab.id: tab for tab in self._config.panel_tabs}
        for row, group in enumerate(self._config.panel_groups):
            group_button = QPushButton(group.name, self._panel_preview_container)
            group_button.setCheckable(True)
            group_button.setChecked(group.id == self._group_id)
            group_button.clicked.connect(
                lambda _checked=False, value=group.id: self._select_panel_from_preview(value)
            )
            self._panel_preview_layout.addWidget(group_button, row, 0)
            self._panel_preview_group_buttons[group.id] = group_button
            for column, tab_id in enumerate(group.tab_ids[:5], start=1):
                tab = tabs_by_id.get(tab_id)
                if tab is None:
                    continue
                tab_button = QPushButton(tab.name, self._panel_preview_container)
                tab_button.setCheckable(True)
                tab_button.setChecked(group.id == self._group_id and tab.id == group.active_tab_id)
                tab_button.clicked.connect(
                    lambda _checked=False, value=tab.id: self._select_tab_from_preview(value)
                )
                self._panel_preview_layout.addWidget(tab_button, row, column)
                self._panel_preview_tab_buttons[tab.id] = tab_button

    def _select_panel_from_preview(self, group_id: str) -> None:
        for row in range(self._panel_group_list.count()):
            item = self._panel_group_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == group_id:
                self._panel_group_list.setCurrentRow(row)
                break

    def _select_tab_from_preview(self, tab_id: str) -> None:
        tab = next((entry for entry in self._config.panel_tabs if entry.id == tab_id), None)
        if tab is None:
            return
        self._select_panel_from_preview(tab.group_id)
        group = self._target_group()
        group.active_tab_id = tab.id
        self._sync_panel_detail()
        for row in range(self._panel_tab_list.count()):
            item = self._panel_tab_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == tab_id:
                self._panel_tab_list.setCurrentRow(row)
                break

    def _build_rules_page(self) -> QWidget:
        page = QWidget(self)
        self._rules_page = page
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("桌面整理只编辑：什么类型整理到哪个标签。", page))
        body = QHBoxLayout()
        self._rule_list = QListWidget(page)
        self._rule_list.currentRowChanged.connect(self._select_rule_row)
        body.addWidget(self._rule_list, stretch=1)
        detail = QVBoxLayout()
        self._rule_enabled_checkbox = QCheckBox("启用", page)
        self._rule_name_label = QLabel("", page)
        self._rule_target_combo = QComboBox(page)
        self._rule_extension_editor = ExtensionTagEditor([], page)
        self._rule_type_label = QLabel("", page)
        self._rule_current_preset_label = QLabel("", page)
        self._rule_preset_buttons: dict[str, QPushButton] = {}
        preset_row = QHBoxLayout()
        for preset in ("图片", "文档", "压缩包", "应用", "代码"):
            button = QPushButton(preset, page)
            button.clicked.connect(lambda _checked=False, value=preset: self._apply_rule_preset(value))
            preset_row.addWidget(button)
            self._rule_preset_buttons[preset] = button
        preset_row.addStretch(1)
        detail.addWidget(self._rule_enabled_checkbox)
        detail.addWidget(self._rule_name_label)
        detail.addWidget(QLabel("规则类型", page))
        detail.addWidget(self._rule_type_label)
        detail.addWidget(QLabel("整理到", page))
        detail.addWidget(self._rule_target_combo)
        detail.addWidget(QLabel("当前预设", page))
        detail.addWidget(self._rule_current_preset_label)
        detail.addLayout(preset_row)
        detail.addWidget(QLabel("后缀列表", page))
        detail.addWidget(self._rule_extension_editor, stretch=1)
        body.addLayout(detail, stretch=2)
        layout.addLayout(body, stretch=1)
        self._reload_rules_editor()
        return page

    def _build_appearance_page(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        group = self._target_group()
        self._selected_color = group.appearance.background_color
        color_row = QHBoxLayout()
        for color in _COLOR_SWATCHES:
            button = QPushButton("", page)
            button.setCheckable(True)
            button.setFixedSize(28, 28)
            button.setToolTip(color)
            button.clicked.connect(lambda _checked=False, value=color: self._select_color(value))
            color_row.addWidget(button)
            self._color_swatch_buttons[color] = button
        self._more_color_button = QPushButton("更多颜色", page)
        self._more_color_button.clicked.connect(self._choose_custom_color)
        color_row.addWidget(self._more_color_button)
        color_row.addStretch(1)
        form.addRow("背景颜色", color_row)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, page)
        self._opacity_slider.setMinimum(self._opacity_to_slider(_OPACITY_MIN))
        self._opacity_slider.setMaximum(self._opacity_to_slider(_OPACITY_MAX))
        self._opacity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._opacity_slider.setTickInterval(10)
        self._opacity_slider.setSingleStep(10)
        self._opacity_slider.setPageStep(10)
        self._opacity_slider.setValue(self._opacity_to_slider(group.appearance.background_opacity))
        self._opacity_spinbox = QSpinBox(page)
        self._opacity_spinbox.setRange(0, 100)
        self._opacity_spinbox.setSuffix("%")
        self._opacity_spinbox.setSingleStep(10)
        self._opacity_spinbox.setValue(self._opacity_slider.value())
        self._opacity_slider.valueChanged.connect(self._sync_opacity_from_slider)
        self._opacity_spinbox.valueChanged.connect(self._sync_opacity_from_spinbox)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_spinbox)
        form.addRow("背景透明度", opacity_row)
        self._sync_color_swatch_states()
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("面板历史", page))
        self._history_card_preview_size = QSize(280, 158)
        self._history_grid_columns = 3
        self._history_cards: list[HistoryCardWidget] = []
        self._history_scroll = QScrollArea(page)
        self._history_scroll.setWidgetResizable(True)
        self._history_grid_host = QWidget(self._history_scroll)
        self._history_grid_layout = QGridLayout(self._history_grid_host)
        self._history_grid_layout.setSpacing(10)
        self._history_scroll.setWidget(self._history_grid_host)
        layout.addWidget(self._history_scroll, stretch=1)
        return page

    def _build_widgets_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("功能面板", page))
        card = QFrame(page)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { background: #242424; border: 1px solid #444; border-radius: 8px; }"
            "QLabel { color: #ffffff; background: transparent; }"
        )
        card_layout = QVBoxLayout(card)
        header = QHBoxLayout()
        header.addWidget(QLabel("时间面板预览", card))
        header.addStretch(1)
        self._add_clock_panel_button = QPushButton("+", card)
        self._add_clock_panel_button.setFixedSize(34, 30)
        self._add_clock_panel_button.setToolTip("创建独立时间面板")
        self._add_clock_panel_button.clicked.connect(
            lambda: self.add_widget_panel_requested.emit("clock")
        )
        header.addWidget(self._add_clock_panel_button)
        card_layout.addLayout(header)
        preview = QLabel("12:34\n2026-05-28", card)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumHeight(90)
        preview.setStyleSheet("font-size: 24px; font-weight: 600;")
        card_layout.addWidget(preview)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_diagnostics_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("诊断与恢复", page))
        self._diagnostics_summary = QPlainTextEdit(page)
        self._diagnostics_summary.setReadOnly(True)
        self._diagnostics_summary.setPlaceholderText("点击刷新诊断状态。")
        self._diagnostics_details = QPlainTextEdit(page)
        self._diagnostics_details.setReadOnly(True)
        self._diagnostics_log_view = QPlainTextEdit(page)
        self._diagnostics_log_view.setReadOnly(True)
        self._diagnostics_log_view.setPlaceholderText("最近日志会显示在这里。")
        self._diagnostics_refresh_button = QPushButton("刷新诊断", page)
        self._diagnostics_restore_icons_button = QPushButton("恢复桌面图标", page)
        self._diagnostics_refresh_takeover_button = QPushButton("刷新桌面接管", page)
        self._diagnostics_open_logs_button = QPushButton("打开日志文件夹", page)
        self._diagnostics_export_button = QPushButton("导出诊断包", page)
        self._diagnostics_refresh_button.clicked.connect(
            self.diagnostics_refresh_requested.emit
        )
        self._diagnostics_restore_icons_button.clicked.connect(
            self.diagnostics_restore_icons_requested.emit
        )
        self._diagnostics_refresh_takeover_button.clicked.connect(
            self.diagnostics_refresh_takeover_requested.emit
        )
        self._diagnostics_open_logs_button.clicked.connect(
            self.diagnostics_open_logs_requested.emit
        )
        self._diagnostics_export_button.clicked.connect(
            self.diagnostics_export_requested.emit
        )
        button_row = QHBoxLayout()
        button_row.addWidget(self._diagnostics_refresh_button)
        button_row.addWidget(self._diagnostics_restore_icons_button)
        button_row.addWidget(self._diagnostics_refresh_takeover_button)
        button_row.addWidget(self._diagnostics_open_logs_button)
        button_row.addWidget(self._diagnostics_export_button)
        layout.addLayout(button_row)
        layout.addWidget(QLabel("当前状态", page))
        layout.addWidget(self._diagnostics_summary, stretch=2)
        self._diagnostics_advanced_group = QGroupBox("高级详情", page)
        self._diagnostics_advanced_group.setCheckable(True)
        self._diagnostics_advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout(self._diagnostics_advanced_group)
        self._diagnostics_advanced_content = QWidget(self._diagnostics_advanced_group)
        advanced_content_layout = QVBoxLayout(self._diagnostics_advanced_content)
        advanced_content_layout.addWidget(QLabel("路径与进程", self._diagnostics_advanced_content))
        advanced_content_layout.addWidget(self._diagnostics_details, stretch=2)
        advanced_content_layout.addWidget(QLabel("最近日志", self._diagnostics_advanced_content))
        advanced_content_layout.addWidget(self._diagnostics_log_view, stretch=3)
        advanced_layout.addWidget(self._diagnostics_advanced_content)
        self._diagnostics_advanced_content.setVisible(False)
        self._diagnostics_advanced_group.toggled.connect(
            self._diagnostics_advanced_content.setVisible
        )
        layout.addWidget(self._diagnostics_advanced_group, stretch=3)
        return page

    def _build_other_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("其他", page))
        layout.addWidget(QLabel("把不常用的提示和偏好恢复到默认状态。", page))
        self._reset_delete_confirmations_button = QPushButton(
            "恢复删除确认提示",
            page,
        )
        self._reset_delete_confirmations_button.clicked.connect(
            self._reset_delete_confirmations
        )
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._reset_delete_confirmations_button)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def set_history_snapshots(self, snapshots: list[object]) -> None:
        while self._history_grid_layout.count():
            item = self._history_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._history_cards = []
        self._history_grid_columns = 3 if self.width() >= 900 else 2
        for index, snapshot in enumerate(snapshots):
            preview_path = str(getattr(snapshot, "preview_path", "") or "")
            if preview_path and Path(preview_path).is_file():
                icon = QIcon(preview_path)
            else:
                icon = self._layout_preview_icon(snapshot)
            card = HistoryCardWidget(snapshot, icon, self._history_card_preview_size, self._history_grid_host)
            card.restore_button.clicked.connect(
                lambda _checked=False, value=card.snapshot_id: self.history_restore_requested.emit(value)
            )
            card.capture_button.clicked.connect(
                lambda _checked=False, value=card.snapshot_id: self.history_capture_preview_requested.emit(value)
            )
            row = index // self._history_grid_columns
            column = index % self._history_grid_columns
            self._history_grid_layout.addWidget(card, row, column)
            self._history_cards.append(card)

    def _layout_preview_icon(self, snapshot: object) -> QIcon:
        size = getattr(self, "_history_card_preview_size", QSize(280, 158))
        pixmap = QPixmap(size)
        pixmap.fill(QColor("#191919"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        config = getattr(snapshot, "configuration", None)
        groups = list(getattr(config, "panel_groups", []) or [])
        if not groups:
            painter.setPen(QColor("#777777"))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "无布局")
            painter.end()
            return QIcon(pixmap)
        colors = ["#934A69", "#4B5563", "#25636B", "#7C6A46"]
        for index, group in enumerate(groups):
            geometry = group.geometry
            rect = QRectF(
                12 + geometry.rx * (size.width() - 24),
                12 + geometry.ry * (size.height() - 24),
                max(16, geometry.rw * (size.width() - 24)),
                max(12, geometry.rh * (size.height() - 24)),
            )
            painter.setBrush(QColor(colors[index % len(colors)]))
            painter.setPen(QPen(QColor("#d7d7d7"), 1))
            painter.drawRoundedRect(rect, 4, 4)
        painter.end()
        return QIcon(pixmap)

    def set_diagnostics(self, snapshot: object, recent_logs: list[str]) -> None:
        self._diagnostics_summary.setPlainText(self._format_diagnostics(snapshot))
        self._diagnostics_details.setPlainText(self._format_diagnostics_details(snapshot))
        self._diagnostics_log_view.setPlainText("\n".join(recent_logs))

    def show_diagnostics_message(self, message: str) -> None:
        current = self._diagnostics_summary.toPlainText().strip()
        separator = "\n\n" if current else ""
        self._diagnostics_summary.setPlainText(f"{current}{separator}{message}")

    def _format_diagnostics(self, snapshot: object) -> str:
        visible = getattr(snapshot, "explorer_icons_visible", None)
        if visible is True:
            visible_text = "是"
        elif visible is False:
            visible_text = "否"
        else:
            visible_text = "未知"
        enabled = "是" if getattr(snapshot, "takeover_enabled", False) else "否"
        restore_required = "是" if getattr(snapshot, "restore_required", False) else "否"
        icons_hidden = "是" if getattr(snapshot, "explorer_icons_hidden", False) else "否"
        recent_errors = list(getattr(snapshot, "recent_errors", []) or [])
        error_text = "\n".join(f"- {entry}" for entry in recent_errors) or "无"
        if getattr(snapshot, "restore_required", False) or getattr(
            snapshot, "explorer_icons_hidden", False
        ):
            status = "桌面接管需要恢复"
        elif recent_errors:
            status = "发现最近错误"
        else:
            status = "运行状态正常"
        return "\n".join(
            [
                f"状态：{status}",
                f"接管启用：{enabled}",
                f"恢复标记：{restore_required}",
                f"Explorer 图标隐藏标记：{icons_hidden}",
                f"Explorer 图标可见：{visible_text}",
                f"面板组/标签：{getattr(snapshot, 'group_count', 0)}组 / {getattr(snapshot, 'tab_count', 0)}标签",
                "最近错误：",
                error_text,
            ]
        )

    def _format_diagnostics_details(self, snapshot: object) -> str:
        return "\n".join(
            [
                f"桌面路径：{getattr(snapshot, 'desktop_path', '')}",
                f"配置路径：{getattr(snapshot, 'config_path', '')}",
                f"日志路径：{getattr(snapshot, 'log_path', '')}",
                f"程序路径：{getattr(snapshot, 'executable_path', '')}",
                f"面板窗口数：{getattr(snapshot, 'panel_window_count', 0)}",
                f"当前屏幕：{getattr(snapshot, 'primary_screen_id', '')}",
                f"进程 ID：{getattr(snapshot, 'process_id', '')}",
            ]
        )

    def _update_takeover_status_label(self) -> None:
        if not hasattr(self, "_takeover_status_label"):
            return
        if self._config.desktop.explorer_icons_hidden:
            text = "Explorer 图标已隐藏"
        elif self._config.desktop.takeover_enabled:
            text = "桌面接管已启用"
        else:
            text = "桌面接管未启用"
        self._takeover_status_label.setText(text)

    def _reload_rules_editor(self) -> None:
        if not hasattr(self, "_rule_list"):
            return
        rules = sorted(self._config.rules, key=lambda entry: entry.order)
        current_id = self._current_rule_id()
        self._rule_list.blockSignals(True)
        self._rule_list.clear()
        selected_row = 0
        for row, rule in enumerate(rules):
            item = QListWidgetItem(rule.name)
            item.setData(Qt.ItemDataRole.UserRole, rule.id)
            self._rule_list.addItem(item)
            if rule.id == current_id:
                selected_row = row
        self._rule_list.setCurrentRow(selected_row if rules else -1)
        self._rule_list.blockSignals(False)
        self._load_rule_detail(self._current_rule_id())

    def _select_rule_row(self, _row: int) -> None:
        self._load_rule_detail(self._current_rule_id())

    def _current_rule_id(self) -> str:
        if not hasattr(self, "_rule_list"):
            return self._config.rules[0].id if self._config.rules else ""
        item = self._rule_list.currentItem()
        if item is None:
            return self._config.rules[0].id if self._config.rules else ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _load_rule_detail(self, rule_id: str) -> None:
        if not rule_id or not hasattr(self, "_rule_enabled_checkbox"):
            return
        rule = next((entry for entry in self._config.rules if entry.id == rule_id), None)
        if rule is None:
            return
        self._rule_enabled_checkbox.setChecked(rule.enabled)
        self._rule_name_label.setText(rule.name)
        self._rule_type_label.setText("文件夹" if rule.matcher_kind == "folder" else "后缀匹配" if rule.matcher_kind == "extension" else "其它")
        self._rule_extension_editor.set_extensions(list(rule.extensions))
        preset_name = self._preset_name_for_extensions(rule.extensions)
        self._rule_current_preset_label.setText(preset_name or "自定义")
        self._rule_target_combo.clear()
        self._rule_target_combo.addItem("（无）", "")
        tab_names = {
            tab.id: tab.name
            for tab in self._config.panel_tabs
            if tab.content_kind == "items"
        }
        for tab_id, name in sorted(tab_names.items(), key=lambda item: item[1]):
            self._rule_target_combo.addItem(name, tab_id)
        index = self._rule_target_combo.findData(
            self._suggested_target_for_rule(rule, self._config)
        )
        if index >= 0:
            self._rule_target_combo.setCurrentIndex(index)

    def _preset_name_for_extensions(self, extensions: list[str]) -> str:
        normalized = {extension.lower() for extension in extensions}
        for name, preset_extensions in _EXTENSION_PRESETS.items():
            if normalized == {extension.lower() for extension in preset_extensions}:
                return name
        return ""

    def _apply_rule_preset(self, name: str) -> None:
        if not hasattr(self, "_rule_extension_editor"):
            return
        self._rule_extension_editor.apply_preset(name)
        self._rule_current_preset_label.setText(name)

    def _suggested_target_for_rule(self, rule, config: Configuration) -> str:  # type: ignore[no-untyped-def]
        tab_ids = {tab.id for tab in config.panel_tabs if tab.content_kind == "items"}
        if rule.target_tab_id in tab_ids:
            return rule.target_tab_id
        role = _DEFAULT_RULE_ROLES.get(rule.id)
        if role is None and rule.matcher_kind == "folder":
            role = "folders"
        elif role is None and rule.matcher_kind == "fallback":
            role = "other"
        if role is None:
            return ""
        for tab in config.panel_tabs:
            if tab.content_kind == "items" and tab.category_role == role:
                return tab.id
        return ""

    def _browse_desktop_path(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择桌面文件夹",
            self._desktop_path_edit.text(),
        )
        if selected:
            self._desktop_path_edit.setText(selected)

    def _save(self) -> None:
        candidate = Configuration.from_dict(self._config.to_dict())
        self._apply_editor_values_to_configuration(candidate)
        try:
            validate_configuration(candidate)
        except InvalidConfiguration as exc:
            self.validation_failed.emit(str(exc))
            return
        if self._requires_takeover_confirmation(candidate) and not self._confirm_takeover_enable():
            candidate.desktop.takeover_enabled = False
            self._takeover_checkbox.setChecked(False)
        self._copy_configuration_state(candidate, self._config)
        self.config_saved.emit()
        self.hide()

    def _requires_takeover_confirmation(self, candidate: Configuration) -> bool:
        return (
            not self._config.desktop.takeover_enabled
            and candidate.desktop.takeover_enabled
        )

    def _confirm_takeover_enable(self) -> bool:
        if self._takeover_confirmation is not None:
            return self._takeover_confirmation()
        result = QMessageBox.question(
            self,
            "启用桌面接管",
            "启用后会隐藏 Explorer 原生桌面图标，并由 Desktop Cleaner 面板显示桌面入口。退出程序、关闭接管或异常恢复时会尝试恢复原桌面图标。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _apply_editor_values_to_configuration(self, config: Configuration) -> None:
        config.desktop.path = self._desktop_path_edit.text().strip()
        config.desktop.takeover_enabled = self._takeover_checkbox.isChecked()
        config.desktop.startup_enabled = self._startup_checkbox.isChecked()
        config.desktop.primary_screen_id = self.selected_screen_id()
        rules_by_id = {rule.id: rule for rule in config.rules}
        valid_item_tab_ids = {tab.id for tab in config.panel_tabs if tab.content_kind == "items"}
        for rule in config.rules:
            if rule.enabled and rule.target_tab_id not in valid_item_tab_ids:
                rule.target_tab_id = self._suggested_target_for_rule(rule, config)
        rule_id = self._current_rule_id()
        if rule_id in rules_by_id:
            target = rules_by_id[rule_id]
            enabled = self._rule_enabled_checkbox.isChecked()
            extensions = self._rule_extension_editor.extensions()
            target_tab_id = str(self._rule_target_combo.currentData() or "")
            if enabled:
                tab_ids = {
                    tab.id for tab in config.panel_tabs if tab.content_kind == "items"
                }
                if target_tab_id not in tab_ids:
                    target_tab_id = self._suggested_target_for_rule(target, config)
            target.enabled = enabled
            target.extensions = extensions
            target.target_tab_id = target_tab_id
        group = self._target_group(config)
        group.screen_id = self.selected_screen_id()
        group.appearance.background_color = self.panel_background_color()
        group.appearance.background_opacity = self.panel_background_opacity()

    def _copy_configuration_state(
        self, source: Configuration, target: Configuration
    ) -> None:
        target.desktop.path = source.desktop.path
        target.desktop.takeover_enabled = source.desktop.takeover_enabled
        target.desktop.startup_enabled = source.desktop.startup_enabled
        target.desktop.primary_screen_id = source.desktop.primary_screen_id
        source_rules = {rule.id: rule for rule in source.rules}
        for rule in target.rules:
            updated = source_rules[rule.id]
            rule.enabled = updated.enabled
            rule.extensions = list(updated.extensions)
            rule.target_tab_id = updated.target_tab_id
        target_group = self._target_group(target)
        source_group = self._target_group(source)
        target_group.screen_id = source_group.screen_id
        target_group.appearance.background_color = (
            source_group.appearance.background_color
        )
        target_group.appearance.background_opacity = (
            source_group.appearance.background_opacity
        )
        target_group.appearance.item_icon_size = source_group.appearance.item_icon_size

    def _select_color(self, color: str) -> None:
        self._selected_color = color
        self._sync_color_swatch_states()

    def _sync_color_swatch_states(self) -> None:
        for color, button in self._color_swatch_buttons.items():
            checked = color.lower() == self._selected_color.lower()
            button.setChecked(checked)
            border = "#ffffff" if checked else "#666666"
            button.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 2px solid {border}; "
                "border-radius: 6px; }}"
            )

    def _choose_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._selected_color), self, "选择背景颜色")
        if color.isValid():
            self._selected_color = color.name().upper()
            self._sync_color_swatch_states()

    def _opacity_to_slider(self, opacity: float) -> int:
        return int(round(max(0.0, min(1.0, opacity)) * 100))

    def _slider_to_opacity(self, value: int) -> float:
        return round(value / 100.0, 2)

    def _sync_opacity_from_slider(self, value: int) -> None:
        if not hasattr(self, "_opacity_spinbox"):
            return
        if self._opacity_spinbox.value() != value:
            self._opacity_spinbox.blockSignals(True)
            self._opacity_spinbox.setValue(value)
            self._opacity_spinbox.blockSignals(False)

    def _sync_opacity_from_spinbox(self, value: int) -> None:
        if self._opacity_slider.value() != value:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(value)
            self._opacity_slider.blockSignals(False)

    def _request_management_add(self) -> None:
        if self._management_selection_kind == "tab":
            self.add_item_tab_requested.emit()
        else:
            self.add_item_panel_requested.emit()

    def _request_management_delete(self) -> None:
        if self._management_selection_kind == "tab":
            self._request_delete_selected_tab()
        else:
            self._request_delete_selected_panel()

    def _rename_panel_from_item(self, item: QListWidgetItem) -> None:
        group_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None:
            return
        new_name = self._ask_for_name("panel", group.name)
        if new_name is None:
            return
        group.name = new_name.strip() or "未命名面板"
        self._reload_panel_management(self._config)
        self.management_metadata_changed.emit()

    def _rename_tab_from_item(self, item: QListWidgetItem) -> None:
        tab_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        tab = next((entry for entry in self._config.panel_tabs if entry.id == tab_id), None)
        if tab is None:
            return
        new_name = self._ask_for_name("tab", tab.name)
        if new_name is None:
            return
        tab.name = new_name.strip() or "未命名面板"
        self._reload_panel_management(self._config)
        self.management_metadata_changed.emit()

    def _ask_for_name(self, kind: str, current: str) -> str | None:
        if self._rename_prompt is not None:
            return self._rename_prompt(kind, current)
        title = "重命名面板" if kind == "panel" else "重命名标签"
        label = "名称"
        text, accepted = QInputDialog.getText(self, title, label, text=current)
        return text if accepted else None

    def _request_delete_selected_panel(self) -> None:
        if len(self._config.panel_groups) <= 1:
            return
        group = self._target_group()
        label = self._panel_label(group.id)
        if self._confirm_delete("panel", label):
            self.delete_item_panel_requested.emit(group.id)

    def _request_delete_selected_tab(self) -> None:
        group = self._target_group()
        if len(self._config.panel_tabs) <= 1 or not group.tab_ids:
            return
        current = self._panel_tab_list.currentItem() if hasattr(self, "_panel_tab_list") else None
        tab_id = (
            self._selected_tab_id
            or (str(current.data(Qt.ItemDataRole.UserRole) or "") if current is not None else "")
            or group.active_tab_id
        )
        tab = next((entry for entry in self._config.panel_tabs if entry.id == tab_id), None)
        if tab is None:
            return
        if self._confirm_delete("tab", tab.name):
            self.delete_item_tab_requested.emit(tab.id)

    def _confirm_delete(self, kind: str, label: str) -> bool:
        if kind == "panel" and not self._ui_preferences.confirm_delete_panel:
            return True
        if kind == "tab" and not self._ui_preferences.confirm_delete_tab:
            return True
        if self._delete_confirmation is not None:
            confirmed, dont_ask_again = self._delete_confirmation(kind, label)
        else:
            box = QMessageBox(self)
            box.setWindowTitle("确认删除")
            box.setText(f"确定删除“{label}”吗？")
            box.setInformativeText("只删除应用里的面板/标签，不会删除任何真实文件。")
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            dont_ask = QCheckBox("以后不再询问", box)
            box.setCheckBox(dont_ask)
            confirmed = box.exec() == QMessageBox.StandardButton.Yes
            dont_ask_again = dont_ask.isChecked()
        if confirmed and dont_ask_again:
            if kind == "panel":
                self._ui_preferences.confirm_delete_panel = False
            else:
                self._ui_preferences.confirm_delete_tab = False
            self.ui_preferences_changed.emit()
        return confirmed

    def _reset_delete_confirmations(self) -> None:
        self._ui_preferences.confirm_delete_panel = True
        self._ui_preferences.confirm_delete_tab = True
        self.ui_preferences_changed.emit()

    def _panel_label(self, group_id: str) -> str:
        for index, group in enumerate(self._config.panel_groups, start=1):
            if group.id == group_id:
                return f"面板 {index}"
        return "面板"

    def _widget_text(self, widget: QWidget) -> str:
        parts: list[str] = []
        for child in widget.findChildren(QWidget):
            if isinstance(child, QLineEdit):
                parts.append(child.text())
                parts.append(child.placeholderText())
            elif isinstance(child, (QLabel, QPushButton, QCheckBox)):
                parts.append(child.text())
            elif isinstance(child, QComboBox):
                parts.append(child.currentText())
            elif isinstance(child, QPlainTextEdit):
                parts.append(child.toPlainText())
            elif isinstance(child, QListWidget):
                for row in range(child.count()):
                    parts.append(child.item(row).text())
        return "\n".join(part for part in parts if part)

    def _basic_page_text(self) -> str:
        return self._widget_text(self._basic_page)

    def _panel_management_page_text(self) -> str:
        return self._widget_text(self._panel_management_page)

    def _rules_page_text(self) -> str:
        return self._widget_text(self._rules_page)
