"""Qt settings surface for the desktop panel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.domain.models import Configuration, InvalidConfiguration, validate_configuration
from desktop_tidy.services.screens import available_screen_options

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
_SECTIONS = _SECTIONS + ["面板历史", "功能面板", "诊断与恢复"]


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


class SettingsWindow(QWidget):
    config_saved = Signal()
    validation_failed = Signal(str)
    restore_desktop_requested = Signal()
    add_item_panel_requested = Signal()
    add_item_tab_requested = Signal()
    identify_screens_requested = Signal()
    add_widget_panel_requested = Signal(str)
    add_widget_tab_requested = Signal(str)
    history_restore_requested = Signal(str)
    history_capture_preview_requested = Signal(str)
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
        screen_options: list[tuple[str, str]] | None = None,
        takeover_confirmation: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._group_id = group_id or config.panel_groups[0].id
        self._screen_options = screen_options or available_screen_options()
        self._selected_screen_id = self._target_group(config).screen_id or config.desktop.primary_screen_id
        self._screen_card_buttons: dict[str, QPushButton] = {}
        self._rule_extension_editors: dict[str, ExtensionTagEditor] = {}
        self._color_swatch_buttons: dict[str, QPushButton] = {}
        self._selected_color = self._target_group(config).appearance.background_color
        self._takeover_confirmation = takeover_confirmation
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
        self._reload_screen_cards(config)
        self._reload_panel_list(config)
        self._reload_rules_table()
        group = self._target_group(config)
        self._selected_color = group.appearance.background_color
        self._sync_color_swatch_states()
        opacity = group.appearance.background_opacity
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(self._opacity_to_slider(opacity))
        self._opacity_slider.blockSignals(False)
        self._update_opacity_label()

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

    def _build_basic_page(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        self._desktop_path_edit = QLineEdit(self._config.desktop.path, page)
        browse = QPushButton("选择文件夹", page)
        browse.clicked.connect(self._browse_desktop_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self._desktop_path_edit)
        path_row.addWidget(browse)
        form.addRow("桌面路径", path_row)
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
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("显示器", page))
        self._screen_cards_row = QHBoxLayout()
        layout.addLayout(self._screen_cards_row)
        self._identify_screens_button = QPushButton("识别", page)
        self._identify_screens_button.clicked.connect(self.identify_screens_requested.emit)
        layout.addWidget(self._identify_screens_button, alignment=Qt.AlignmentFlag.AlignRight)

        actions = QHBoxLayout()
        self._new_item_panel_button = QPushButton("新建面板", page)
        self._new_item_tab_button = QPushButton("新建标签", page)
        self._new_item_panel_button.clicked.connect(self.add_item_panel_requested.emit)
        self._new_item_tab_button.clicked.connect(self.add_item_tab_requested.emit)
        actions.addWidget(self._new_item_panel_button)
        actions.addWidget(self._new_item_tab_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(QLabel("当前面板", page))
        self._panel_list = QListWidget(page)
        layout.addWidget(self._panel_list, stretch=1)
        self._reload_screen_cards(self._config)
        self._reload_panel_list(self._config)
        return page

    def _reload_screen_cards(self, config: Configuration) -> None:
        if not hasattr(self, "_screen_cards_row"):
            return
        for button in self._screen_card_buttons.values():
            self._screen_cards_row.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._screen_card_buttons = {}
        current = self._selected_screen_id or self._target_group(config).screen_id or config.desktop.primary_screen_id
        valid_ids = {screen_id for screen_id, _label in self._screen_options}
        if current not in valid_ids:
            current = "primary"
        self._selected_screen_id = current
        for screen_id, label in self._screen_options:
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setMinimumSize(120, 70)
            button.clicked.connect(lambda _checked=False, value=screen_id: self._select_screen(value))
            self._screen_cards_row.addWidget(button)
            self._screen_card_buttons[screen_id] = button
        self._sync_screen_card_states()

    def _select_screen(self, screen_id: str) -> None:
        self._selected_screen_id = screen_id
        self._sync_screen_card_states()

    def _sync_screen_card_states(self) -> None:
        for screen_id, button in self._screen_card_buttons.items():
            checked = screen_id == self._selected_screen_id
            button.setChecked(checked)
            background = "#934A69" if checked else "#2F2F2F"
            button.setStyleSheet(
                f"QPushButton {{ color: #ffffff; background: {background}; "
                "border: 1px solid #4a4a4a; border-radius: 8px; font-size: 18px; }}"
                "QPushButton:hover { border-color: #d7b0c2; }"
            )

    def _reload_panel_list(self, config: Configuration) -> None:
        if not hasattr(self, "_panel_list"):
            return
        self._panel_list.clear()
        for group in config.panel_groups:
            item = QListWidgetItem(f"面板：{group.id} · {len(group.tab_ids)}个标签")
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            self._panel_list.addItem(item)
            for tab_id in group.tab_ids:
                tab = next(
                    (entry for entry in config.panel_tabs if entry.id == tab_id),
                    None,
                )
                if tab is not None:
                    child = QListWidgetItem(f"  · {tab.name}")
                    child.setData(Qt.ItemDataRole.UserRole, tab.id)
                    self._panel_list.addItem(child)

    def _build_rules_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("分类规则", page))
        action_row = QHBoxLayout()
        self._rules_new_item_panel_button = QPushButton("新建面板", page)
        self._rules_new_item_tab_button = QPushButton("新建标签", page)
        self._rules_new_item_panel_button.clicked.connect(self.add_item_panel_requested.emit)
        self._rules_new_item_tab_button.clicked.connect(self.add_item_tab_requested.emit)
        action_row.addWidget(self._rules_new_item_panel_button)
        action_row.addWidget(self._rules_new_item_tab_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        self._rules_table = QTableWidget(0, 4, page)
        self._rules_table.setHorizontalHeaderLabels(
            ["启用", "名称", "包含后缀", "整理到"]
        )
        self._reload_rules_table()
        layout.addWidget(self._rules_table)
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
        self._opacity_percent_label = QLabel(page)
        self._opacity_slider.valueChanged.connect(lambda _value: self._update_opacity_label())
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_percent_label)
        form.addRow("背景透明度", opacity_row)
        self._sync_color_swatch_states()
        self._update_opacity_label()
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("面板历史", page))
        self._history_list = QListWidget(page)
        layout.addWidget(self._history_list, stretch=1)
        self._restore_history_button = QPushButton("恢复选中历史", page)
        self._restore_history_button.clicked.connect(self._emit_selected_history_restore)
        self._capture_history_preview_button = QPushButton("保存主屏截图预览", page)
        self._capture_history_preview_button.clicked.connect(
            self._emit_selected_history_preview_capture
        )
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._capture_history_preview_button)
        actions.addWidget(self._restore_history_button)
        layout.addLayout(actions)
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
        card_layout.addWidget(QLabel("时间面板预览", card))
        preview = QLabel("12:34\n2026-05-28", card)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumHeight(90)
        preview.setStyleSheet("font-size: 24px; font-weight: 600;")
        card_layout.addWidget(preview)
        self._add_clock_panel_button = QPushButton("添加为独立面板", card)
        self._add_clock_tab_button = QPushButton("添加到当前面板组", card)
        self._add_clock_panel_button.clicked.connect(
            lambda: self.add_widget_panel_requested.emit("clock")
        )
        self._add_clock_tab_button.clicked.connect(
            lambda: self.add_widget_tab_requested.emit("clock")
        )
        button_row = QHBoxLayout()
        button_row.addWidget(self._add_clock_panel_button)
        button_row.addWidget(self._add_clock_tab_button)
        card_layout.addLayout(button_row)
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

    def set_history_snapshots(self, snapshots: list[object]) -> None:
        self._history_list.clear()
        for snapshot in snapshots:
            item = QListWidgetItem(
                f"{snapshot.created_at}  {snapshot.reason}  "
                f"{snapshot.group_count}组/{snapshot.tab_count}标签"
            )
            preview_path = str(getattr(snapshot, "preview_path", "") or "")
            if preview_path and Path(preview_path).is_file():
                item.setIcon(QIcon(preview_path))
            else:
                item.setIcon(self._layout_preview_icon(snapshot))
            item.setData(Qt.ItemDataRole.UserRole, snapshot.id)
            self._history_list.addItem(item)

    def _emit_selected_history_restore(self) -> None:
        item = self._history_list.currentItem()
        if item is None:
            return
        snapshot_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if snapshot_id:
            self.history_restore_requested.emit(snapshot_id)

    def _emit_selected_history_preview_capture(self) -> None:
        item = self._history_list.currentItem()
        if item is None:
            return
        snapshot_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if snapshot_id:
            self.history_capture_preview_requested.emit(snapshot_id)

    def _layout_preview_icon(self, snapshot: object) -> QIcon:
        pixmap = QPixmap(128, 72)
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
                8 + geometry.rx * 112,
                8 + geometry.ry * 56,
                max(10, geometry.rw * 112),
                max(8, geometry.rh * 56),
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

    def _reload_rules_table(self) -> None:
        rules = sorted(self._config.rules, key=lambda entry: entry.order)
        self._rules_table.setRowCount(len(rules))
        self._rule_extension_editors = {}
        tab_names = {
            tab.id: tab.name
            for tab in self._config.panel_tabs
            if tab.content_kind == "items"
        }
        for row, rule in enumerate(rules):
            enabled = QTableWidgetItem()
            enabled.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            enabled.setCheckState(
                Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked
            )
            self._rules_table.setItem(row, 0, enabled)
            self._rules_table.setItem(row, 1, QTableWidgetItem(rule.name))
            editor = ExtensionTagEditor(list(rule.extensions), self._rules_table)
            self._rule_extension_editors[rule.id] = editor
            self._rules_table.setCellWidget(row, 2, editor)
            target = QComboBox(self._rules_table)
            target.addItem("（无）", "")
            for tab_id, name in sorted(tab_names.items(), key=lambda item: item[1]):
                target.addItem(name, tab_id)
            index = target.findData(self._suggested_target_for_rule(rule, self._config))
            if index >= 0:
                target.setCurrentIndex(index)
            self._rules_table.setCellWidget(row, 3, target)

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
        for row, rule in enumerate(sorted(config.rules, key=lambda entry: entry.order)):
            enabled_item = self._rules_table.item(row, 0)
            enabled = (
                enabled_item.checkState() == Qt.CheckState.Checked
                if enabled_item is not None
                else rule.enabled
            )
            extensions_widget = self._rules_table.cellWidget(row, 2)
            if isinstance(extensions_widget, ExtensionTagEditor):
                extensions = extensions_widget.extensions()
            else:
                extensions = list(rule.extensions)
            target_widget = self._rules_table.cellWidget(row, 3)
            if isinstance(target_widget, QComboBox):
                target_tab_id = str(target_widget.currentData() or "")
            else:
                target_tab_id = rule.target_tab_id
            if enabled:
                tab_ids = {
                    tab.id for tab in config.panel_tabs if tab.content_kind == "items"
                }
                if target_tab_id not in tab_ids:
                    target_tab_id = self._suggested_target_for_rule(rule, config)
            target = rules_by_id[rule.id]
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

    def _update_opacity_label(self) -> None:
        if hasattr(self, "_opacity_percent_label"):
            self._opacity_percent_label.setText(f"{self._opacity_slider.value()}%")
