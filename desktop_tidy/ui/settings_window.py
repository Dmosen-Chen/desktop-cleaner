"""Qt settings surface for the desktop panel."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QFontMetrics,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.domain.models import (
    Configuration,
    InvalidConfiguration,
    validate_configuration,
)
from desktop_tidy.domain.workspace import WorkspaceModel
from desktop_tidy.persistence.ui_preferences import UiPreferences
from desktop_tidy.services.screens import ScreenInfo, available_screens
from desktop_tidy.version import APP_VERSION
from desktop_tidy.ui.panel_preview import (
    PanelPreviewWidget,
    layout_preview_tab_names as shared_layout_preview_tab_names,
    render_layout_preview_pixmap as shared_render_layout_preview_pixmap,
)
from desktop_tidy.widgets.models import WidgetDefinition
from desktop_tidy.widgets.registry import BuiltinWidgetRegistry

_SECTIONS = ["面板", "分类规则"]
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
_PANEL_COUNT_ROLE = Qt.ItemDataRole.UserRole.value + 64
_SETTINGS_WINDOW_STYLE = """
QWidget#DesktopCleanerSettings {
    background: rgba(9, 11, 15, 214);
    color: #F8FAFC;
}
QWidget#SettingsTitleBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(35, 39, 47, 232),
        stop:0.55 rgba(22, 25, 31, 226),
        stop:1 rgba(49, 36, 49, 230));
    border: 1px solid rgba(255, 255, 255, 54);
    border-radius: 15px;
}
QLabel#SettingsTitleIcon {
    background: rgba(217, 154, 189, 66);
    border: 1px solid rgba(217, 154, 189, 126);
    border-radius: 10px;
    padding: 5px;
}
QLabel#SettingsTitleText {
    color: #F8FAFC;
    font-weight: 700;
    font-size: 15px;
    letter-spacing: 0px;
}
QPushButton#SettingsTitleButton {
    background: rgba(255, 255, 255, 28);
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 10px;
    font-size: 15px;
    padding: 0;
}
QPushButton#SettingsCloseButton {
    background: rgba(255, 255, 255, 28);
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 10px;
    font-size: 15px;
    padding: 0;
}
QPushButton#SettingsTitleButton:hover {
    background: rgba(255, 255, 255, 44);
    border-color: rgba(255, 255, 255, 70);
}
QPushButton#SettingsTitleButton:pressed {
    background: rgba(217, 154, 189, 150);
    color: #FFFFFF;
}
QPushButton#SettingsCloseButton:pressed {
    background: rgba(232, 93, 117, 220);
    color: #FFFFFF;
}
QPushButton#SettingsCloseButton:hover {
    background: rgba(232, 93, 117, 190);
    color: #FFFFFF;
}
QWidget#DesktopCleanerSettings QListWidget,
QWidget#DesktopCleanerSettings QStackedWidget,
QWidget#DesktopCleanerSettings QPlainTextEdit {
    background: rgba(28, 31, 37, 236);
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 34);
    border-radius: 11px;
    selection-color: #F8FAFC;
    selection-background-color: rgba(217, 154, 189, 78);
}
QWidget#DesktopCleanerSettings QListWidget::item {
    color: #F8FAFC;
    min-height: 30px;
    padding: 4px 8px;
    border-radius: 6px;
}
QWidget#DesktopCleanerSettings QListWidget::item:hover {
    background: rgba(255, 255, 255, 20);
    color: #F8FAFC;
}
QWidget#DesktopCleanerSettings QListWidget::item:selected {
    background: rgba(217, 154, 189, 36);
    border-left: 3px solid #d99abd;
    color: #F8FAFC;
}
QWidget#DesktopCleanerSettings QListWidget::item:selected:!active,
QWidget#DesktopCleanerSettings QListWidget::item:selected:active {
    color: #F8FAFC;
}
QWidget#DesktopCleanerSettings QGroupBox,
QWidget#DesktopCleanerSettings QFrame {
    background: rgba(31, 34, 40, 238);
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 36);
    border-radius: 12px;
}
QWidget#DesktopCleanerSettings QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QWidget#DesktopCleanerSettings QLabel,
QWidget#DesktopCleanerSettings QCheckBox {
    color: #F8FAFC;
    background: transparent;
}
QWidget#DesktopCleanerSettings QPushButton,
QWidget#DesktopCleanerSettings QComboBox,
QWidget#DesktopCleanerSettings QLineEdit,
QWidget#DesktopCleanerSettings QSpinBox {
    background: rgba(43, 47, 55, 236);
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 42);
    border-radius: 8px;
    padding: 4px 8px;
}
QWidget#DesktopCleanerSettings QPushButton:hover {
    background: rgba(61, 66, 76, 242);
    border-color: rgba(255, 255, 255, 74);
}
QWidget#DesktopCleanerSettings QPushButton:pressed {
    background: rgba(217, 154, 189, 220);
    color: #111318;
}
QWidget#DesktopCleanerSettings QPushButton:checked {
    background: rgba(217, 154, 189, 120);
    color: #F8FAFC;
    border-color: rgba(217, 154, 189, 220);
}
QWidget#DesktopCleanerSettings QLineEdit:focus,
QWidget#DesktopCleanerSettings QComboBox:focus,
QWidget#DesktopCleanerSettings QSpinBox:focus {
    border-color: rgba(248, 250, 252, 170);
    color: #F8FAFC;
}
"""


class SettingsTitleBar(QWidget):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._drag_start = QPoint()
        self._window_start = QPoint()
        self.setObjectName("SettingsTitleBar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(10)

        icon_label = QLabel(self)
        icon_label.setObjectName("SettingsTitleIcon")
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon).pixmap(18, 18))
        self.title_label = QLabel("设置", self)
        self.title_label.setObjectName("SettingsTitleText")
        layout.addWidget(icon_label)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.minimize_button = self._make_button("−", "最小化")
        self.maximize_button = self._make_button("□", "最大化")
        self.close_button = self._make_button("×", "关闭设置")
        self.close_button.setObjectName("SettingsCloseButton")
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(self._toggle_maximized)
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

    def _make_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName("SettingsTitleButton")
        button.setToolTip(tooltip)
        button.setFixedSize(38, 32)
        return button

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
            self.maximize_button.setText("□")
        else:
            self._window.showMaximized()
            self.maximize_button.setText("❐")

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._window_start = self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and not self._window.isMaximized():
            self._window.move(self._window_start + event.globalPosition().toPoint() - self._drag_start)
            event.accept()
            return
        super().mouseMoveEvent(event)


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


class FlowLayout(QLayout):
    """Simple wrapping layout for compact chip rows."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margin: int = 0,
        spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[object] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # type: ignore[no-untyped-def]
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # type: ignore[no-untyped-def]
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # type: ignore[no-untyped-def]
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def row_count_for_width(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, max(1, width), 0), test_only=True, count_rows=True)

    def _do_layout(
        self,
        rect: QRect,
        *,
        test_only: bool,
        count_rows: bool = False,
    ) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        rows = 1 if self._items else 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if x > effective.x() and next_x - spacing > effective.right() + 1:
                x = effective.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
                rows += 1
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        if count_rows:
            return rows
        return y + line_height - rect.y() + margins.bottom()


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
        self._chips_host = QWidget(self)
        self._chips_flow = FlowLayout(self._chips_host, spacing=6)

        top = QHBoxLayout()
        top.addWidget(self._preset_combo)
        top.addWidget(self._preset_button)
        top.addWidget(self._custom_input)
        top.addWidget(self._custom_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(112)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._chips_host)
        self._chips_scroll = scroll
        layout.addWidget(scroll)

        self._preset_button.clicked.connect(self._apply_selected_preset)
        self._custom_button.clicked.connect(self._add_custom_extension)
        self._custom_input.returnPressed.connect(self._add_custom_extension)
        self.set_extensions(extensions)

    def extensions(self) -> list[str]:
        return list(self._extensions)

    def set_extensions(self, extensions: list[str]) -> None:
        normalized: list[str] = []
        for extension in extensions:
            value = self._normalize_extension(extension)
            if value and value not in normalized:
                normalized.append(value)
        self._extensions = normalized
        self._rebuild_chips()

    def apply_preset(self, name: str) -> None:
        changed = False
        for extension in _EXTENSION_PRESETS.get(name, []):
            normalized = self._normalize_extension(extension)
            if normalized and normalized not in self._extensions:
                self._extensions.append(normalized)
                changed = True
        if changed:
            self._rebuild_chips()

    def add_extension(self, extension: str) -> None:
        normalized = self._normalize_extension(extension)
        if not normalized:
            return
        if normalized not in self._extensions:
            self._extensions.append(normalized)
            self._rebuild_chips()

    def remove_extension(self, extension: str) -> None:
        normalized = extension.strip().lower()
        self._extensions = [entry for entry in self._extensions if entry != normalized]
        self._rebuild_chips()

    def is_flow_layout_enabled(self) -> bool:
        return True

    def chip_row_count_for_width(self, width: int) -> int:
        return self._chips_flow.row_count_for_width(width)

    def scroll_height_range(self) -> tuple[int, int]:
        return (self._chips_scroll.minimumHeight(), self._chips_scroll.maximumHeight())

    def _apply_selected_preset(self) -> None:
        name = str(self._preset_combo.currentData() or "")
        if name:
            self.apply_preset(name)

    def _add_custom_extension(self) -> None:
        self.add_extension(self._custom_input.text())
        self._custom_input.clear()

    def _rebuild_chips(self) -> None:
        while self._chips_flow.count():
            item = self._chips_flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._chip_widgets = []
        for extension in self._extensions:
            chip = QPushButton(extension, self._chips_host)
            chip.setToolTip("点击移除此后缀")
            chip.setStyleSheet(
                "QPushButton { color: #ffffff; background: #3b3b3b; "
                "border: 1px solid #555; border-radius: 8px; padding: 2px 8px; }"
                "QPushButton:hover { background: #555; }"
            )
            chip.clicked.connect(lambda _checked=False, value=extension: self.remove_extension(value))
            self._chips_flow.addWidget(chip)
            self._chip_widgets.append(chip)
        self._chips_host.adjustSize()

    def _normalize_extension(self, extension: str) -> str:
        normalized = extension.strip().lower()
        if not normalized:
            return ""
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        return normalized


class EditableRowWidget(QWidget):
    rename_committed = Signal(str)

    def __init__(self, text: str, count: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.label = QLabel(text, self)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.label.setMinimumWidth(0)
        self.count_label = QLabel(count, self)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.editor = QLineEdit(text, self)
        self.editor.hide()
        self.editor.editingFinished.connect(self._finish_edit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.addWidget(self.label, stretch=1)
        if count:
            self.count_label.setFixedWidth(32)
            layout.addWidget(self.count_label)
        else:
            self.count_label.hide()
        layout.addWidget(self.editor, stretch=1)

    def set_text(self, text: str) -> None:
        self._text = text
        self.label.setText(text)
        self.editor.setText(text)

    def begin_edit(self) -> None:
        self.editor.setText(self._text)
        self.label.hide()
        self.count_label.hide()
        self.editor.show()
        self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self.editor.selectAll()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.begin_edit()
        event.accept()

    def _finish_edit(self) -> None:
        if not self.editor.isVisible():
            return
        text = self.editor.text().strip()
        self.editor.hide()
        self.label.show()
        if self.count_label.text():
            self.count_label.show()
        if text and text != self._text:
            self._text = text
            self.label.setText(text)
            self.rename_committed.emit(text)
        else:
            self.editor.setText(self._text)


class PanelListDelegate(QStyledItemDelegate):
    """Paints stable panel rows without embedding per-row widgets."""

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[no-untyped-def]
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = option.rect.adjusted(4, 3, -4, -3)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3a3a3a" if selected else "#2b2b2b"))
        painter.drawRoundedRect(rect, 6, 6)
        if selected:
            painter.setBrush(QColor("#f0a8cf"))
            painter.drawRoundedRect(rect.adjusted(0, 6, -rect.width() + 4, -6), 2, 2)
        count = str(index.data(_PANEL_COUNT_ROLE) or "")
        count_width = 34 if count else 0
        text_rect = rect.adjusted(12, 0, -count_width - 8, 0)
        metrics = QFontMetrics(option.font)
        name = metrics.elidedText(str(index.data(Qt.ItemDataRole.DisplayRole) or ""), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.setPen(QColor("#ffffff"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        if count:
            painter.drawText(
                rect.adjusted(rect.width() - count_width - 8, 0, -8, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                count,
            )
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # type: ignore[no-untyped-def]
        return QSize(220, 42)


class HistoryCardWidget(QFrame):
    def __init__(
        self,
        snapshot: object,
        icon: QIcon,
        preview_size: QSize,
        preview_tab_names: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.snapshot_id = str(getattr(snapshot, "id", "") or "")
        self.preview_tab_names = list(preview_tab_names or [])
        self.restore_button = QPushButton("恢复", self)
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
            f"{_history_reason_label(str(getattr(snapshot, 'reason', '') or ''))}\n"
            f"{getattr(snapshot, 'group_count', 0)}组 / {getattr(snapshot, 'tab_count', 0)}标签",
            self,
        )
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.restore_button)
        layout = QVBoxLayout(self)
        layout.addWidget(preview)
        layout.addWidget(text)
        layout.addLayout(actions)


def _history_reason_label(reason: str) -> str:
    labels = {
        "add-item-panel": "新增面板",
        "add-item-tab": "新增标签",
        "add-widget-panel:clock": "新增时间面板",
        "appearance-change": "外观调整",
        "delete-item-panel": "删除面板",
        "delete-item-tab": "删除标签",
        "detach-tab": "拆出标签",
        "geometry-change": "移动或缩放",
        "layout-adjustment": "调整面板",
        "merge-group": "合并面板",
        "move": "移动或缩放",
        "panel-change": "面板调整",
        "settings-preview-move": "预览拖动面板",
        "settings-rename": "重命名",
        "settings-save": "保存设置",
        "tab-reorder": "调整标签顺序",
    }
    return labels.get(reason, "布局变化")


class SettingsWindow(QWidget):
    PANEL_COUNT_ROLE = _PANEL_COUNT_ROLE

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
    ui_preferences_changed = Signal()
    management_metadata_changed = Signal()
    management_group_geometry_changed = Signal(str, object, bool)
    appearance_live_changed = Signal(str, str, float)
    appearance_live_save_requested = Signal(str)
    management_tab_reordered = Signal(str, str, int, bool)
    diagnostics_refresh_requested = Signal()
    diagnostics_restore_icons_requested = Signal()
    diagnostics_refresh_takeover_requested = Signal()
    diagnostics_open_logs_requested = Signal()
    diagnostics_export_requested = Signal()
    update_check_requested = Signal()
    update_download_requested = Signal()
    update_open_folder_requested = Signal()
    update_replace_requested = Signal()

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
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
        self._management_selection_kind = "panel"
        self._selected_tab_id = ""
        self._history_snapshots: list[object] = []
        self._inline_edit_kind = ""
        self._inline_edit_id = ""
        self._appearance_save_timer = QTimer(self)
        self._appearance_save_timer.setSingleShot(True)
        self._appearance_save_timer.setInterval(250)
        self._appearance_save_timer.timeout.connect(self._emit_appearance_save_requested)
        self.setObjectName("DesktopCleanerSettings")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(_SETTINGS_WINDOW_STYLE)
        self.setWindowTitle("设置")
        self.resize(820, 600)

        self._section_list = QListWidget(self)
        for name in _SECTIONS:
            self._section_list.addItem(QListWidgetItem(name))
        self._section_list.setFixedWidth(140)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._build_panel_management_page())
        self._pages.addWidget(self._build_rules_page())
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

        self._title_bar = SettingsTitleBar(self)
        self._title_label = self._title_bar.title_label
        self._title_minimize_button = self._title_bar.minimize_button
        self._title_maximize_button = self._title_bar.maximize_button
        self._title_close_button = self._title_bar.close_button

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self._title_bar)
        layout.addLayout(body)
        layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignRight)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.hide()
        event.ignore()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        # 顶级 QWidget 不会自动绘制 QSS 的 background,
        # 叠加 WA_TranslucentBackground 后整窗透明,这里手动画磨砂底 + 圆角边框。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        painter.fillPath(path, QColor(9, 11, 15, 214))
        pen = QPen(QColor(255, 255, 255, 40))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        super().paintEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._reflow_history_grid_if_needed()

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
        self._sync_appearance_controls_from_group(group)

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
        self._update_takeover_status_label()
        return page

    def _build_panel_management_page(self) -> QWidget:
        page = QWidget(self)
        self._panel_management_page = page
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        left.addWidget(QLabel("面板", page))
        self._panel_group_list = QListWidget(page)
        self._panel_group_list.setItemDelegate(PanelListDelegate(self._panel_group_list))
        self._panel_group_list.currentRowChanged.connect(self._select_panel_group_row)
        self._panel_group_list.itemDoubleClicked.connect(self._rename_panel_from_item)
        left.addWidget(self._panel_group_list, stretch=1)
        layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        self._management_add_button = QPushButton("+", page)
        self._management_add_button.setToolTip("新建面板或标签")
        self._management_delete_button = QPushButton("", page)
        self._management_delete_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self._management_delete_button.setToolTip("删除当前选中的面板或标签")
        self._management_add_button.setFixedSize(42, 30)
        self._management_delete_button.setFixedSize(42, 30)
        self._management_add_button.clicked.connect(self._request_management_add)
        self._management_delete_button.clicked.connect(self._request_management_delete)
        self._panel_inline_editor = QLineEdit(page)
        self._panel_inline_editor.hide()
        self._panel_inline_editor.editingFinished.connect(self._finish_inline_edit)
        actions = QHBoxLayout()
        actions.addWidget(self._management_add_button)
        actions.addWidget(self._management_delete_button)
        actions.addStretch(1)
        right.addLayout(actions)
        self._panel_summary_label = QLabel("", page)
        right.addWidget(self._panel_summary_label)
        self._panel_layout_preview = PanelPreviewWidget(
            self._config,
            self._screen_infos,
            show_detail=False,
            parent=page,
        )
        self._panel_layout_preview.group_selected.connect(self._select_panel_from_preview)
        self._panel_layout_preview.tab_selected.connect(self._select_tab_from_preview)
        self._panel_layout_preview.tab_reordered.connect(self._reorder_tab_from_preview)
        self._panel_layout_preview.screen_selected.connect(self._select_screen)
        self._panel_layout_preview.group_rename_requested.connect(self._begin_panel_inline_rename_by_id)
        self._panel_layout_preview.tab_rename_requested.connect(self._begin_tab_inline_rename_by_id)
        self._panel_layout_preview.group_geometry_changed.connect(
            self.management_group_geometry_changed.emit
        )
        right.addWidget(self._panel_layout_preview, stretch=1)
        right.addWidget(QLabel("标签", page))
        self._panel_tab_list = QListWidget(page)
        self._panel_tab_list.currentRowChanged.connect(self._select_panel_tab_row)
        self._panel_tab_list.itemClicked.connect(self._select_panel_tab_item)
        self._panel_tab_list.itemDoubleClicked.connect(self._rename_tab_from_item)
        right.addWidget(self._panel_tab_list, stretch=1)
        appearance = self._build_appearance_page()
        right.addWidget(appearance)
        layout.addLayout(right, stretch=2)
        self._reload_panel_management(self._config)
        return page

    def _reload_screen_layout(self, config: Configuration) -> None:
        current = self._selected_screen_id or self._target_group(config).screen_id or config.desktop.primary_screen_id
        valid_ids = {screen.screen_id for screen in self._screen_infos}
        if current not in valid_ids:
            current = "primary"
        self._selected_screen_id = current
        if hasattr(self, "_screen_layout_widget"):
            self._screen_layout_widget.set_selected_screen(current)
            self._screen_layout_buttons = self._screen_layout_widget.buttons
        if hasattr(self, "_panel_layout_preview"):
            self._panel_layout_preview.set_selected_screen(current)

    def _select_screen(self, screen_id: str) -> None:
        self._selected_screen_id = screen_id
        if hasattr(self, "_screen_layout_widget"):
            self._screen_layout_widget.set_selected_screen(screen_id)
        if hasattr(self, "_panel_layout_preview"):
            self._panel_layout_preview.set_selected_screen(screen_id)
        if hasattr(self, "_screen_hint_label"):
            self._screen_hint_label.setText(f"显示器：{self._screen_label(screen_id)}")

    def _reload_panel_management(self, config: Configuration) -> None:
        if not hasattr(self, "_panel_group_list"):
            return
        self._panel_group_list.blockSignals(True)
        self._panel_group_list.clear()
        selected_row = 0
        for index, group in enumerate(config.panel_groups):
            item = QListWidgetItem(group.name or f"面板 {index + 1}")
            item.setSizeHint(QSize(220, 40))
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            item.setData(_PANEL_COUNT_ROLE, len(group.tab_ids))
            self._panel_group_list.addItem(item)
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
            self._sync_appearance_controls_from_group()
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
            group = self._target_group()
            if tab_id in group.tab_ids:
                group.active_tab_id = tab_id
            self._rebuild_panel_preview()

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
            item.setSizeHint(QSize(320, 36))
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
        if not hasattr(self, "_panel_layout_preview"):
            return
        self._panel_layout_preview.set_state(
            self._config,
            self._screen_infos,
            self._group_id,
            self._selected_tab_id or self._target_group().active_tab_id,
        )

    def _sync_appearance_controls_from_group(self, group=None) -> None:  # type: ignore[no-untyped-def]
        if not hasattr(self, "_opacity_slider"):
            return
        group = group or self._target_group()
        self._selected_color = group.appearance.background_color
        self._sync_color_swatch_states()
        value = self._opacity_to_slider(group.appearance.background_opacity)
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(value)
        self._opacity_slider.blockSignals(False)
        if hasattr(self, "_opacity_spinbox"):
            self._opacity_spinbox.blockSignals(True)
            self._opacity_spinbox.setValue(value)
            self._opacity_spinbox.blockSignals(False)

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

    def _reorder_tab_from_preview(
        self,
        group_id: str,
        tab_id: str,
        target_index: int,
        final: bool,
    ) -> None:
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None or tab_id not in group.tab_ids:
            return
        current_index = group.tab_ids.index(tab_id)
        clamped = max(0, min(target_index, len(group.tab_ids) - 1))
        if clamped != current_index:
            group.tab_ids.pop(current_index)
            group.tab_ids.insert(clamped, tab_id)
            for order, current_tab_id in enumerate(group.tab_ids):
                tab = next((entry for entry in self._config.panel_tabs if entry.id == current_tab_id), None)
                if tab is not None:
                    tab.order = order
            group.active_tab_id = tab_id
            self._selected_tab_id = tab_id
            self._sync_panel_detail()
        self.management_tab_reordered.emit(group_id, tab_id, clamped, final)

    def _build_rules_page(self) -> QWidget:
        page = QWidget(self)
        self._rules_page = page
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("分类规则：按文件类型显示到哪个标签。", page))
        custom_row = QHBoxLayout()
        self._custom_type_name_edit = QLineEdit(page)
        self._custom_type_name_edit.setPlaceholderText("自定义类型名称")
        self._create_custom_type_button = QPushButton("新增类型", page)
        self._delete_custom_rule_button = QPushButton("删除类型", page)
        self._create_custom_type_button.clicked.connect(self._create_custom_classification_type)
        self._delete_custom_rule_button.clicked.connect(self._delete_current_custom_rule)
        custom_row.addWidget(self._custom_type_name_edit, stretch=1)
        custom_row.addWidget(self._create_custom_type_button)
        custom_row.addWidget(self._delete_custom_rule_button)
        layout.addLayout(custom_row)
        body = QHBoxLayout()
        self._rule_list = QListWidget(page)
        self._rule_list.currentRowChanged.connect(self._select_rule_row)
        body.addWidget(self._rule_list, stretch=1)
        detail = QVBoxLayout()
        self._rule_enabled_checkbox = QCheckBox("启用", page)
        self._rule_name_label = QLabel("", page)
        self._rule_target_combo = QComboBox(page)
        self._rule_extension_editor = ExtensionTagEditor([], page)
        self._rule_extension_panel = QFrame(page)
        self._rule_extension_panel.setFixedHeight(156)
        extension_panel_layout = QVBoxLayout(self._rule_extension_panel)
        extension_panel_layout.setContentsMargins(0, 0, 0, 0)
        extension_panel_layout.addWidget(self._rule_extension_editor)
        self._rule_folder_note = QLabel("按文件夹类型整理", page)
        self._rule_type_label = QLabel("", page)
        self._rule_current_preset_label = QLabel("", page)
        self._rule_preset_buttons: dict[str, QPushButton] = {}
        self._rule_preset_host = QWidget(page)
        self._rule_preset_flow = FlowLayout(self._rule_preset_host, spacing=8)
        for preset in ("图片", "文档", "压缩包", "应用", "代码"):
            button = QPushButton(preset, page)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=preset: self._apply_rule_preset(value))
            self._rule_preset_flow.addWidget(button)
            self._rule_preset_buttons[preset] = button
        self._rule_preset_host.setFixedHeight(72)
        self._rule_detail_card = QFrame(page)
        self._rule_detail_card.setFrameShape(QFrame.Shape.StyledPanel)
        self._rule_detail_card.setMaximumHeight(520)
        self._rule_detail_layout = QVBoxLayout(self._rule_detail_card)
        self._rule_detail_layout.setContentsMargins(12, 12, 12, 12)
        self._rule_detail_layout.setSpacing(6)
        self._rule_detail_layout.addWidget(self._rule_enabled_checkbox)
        self._rule_detail_layout.addWidget(self._rule_name_label)
        self._rule_detail_layout.addWidget(QLabel("规则类型", page))
        self._rule_detail_layout.addWidget(self._rule_type_label)
        self._rule_detail_layout.addWidget(QLabel("整理到", page))
        self._rule_detail_layout.addWidget(self._rule_target_combo)
        self._rule_detail_layout.addWidget(QLabel("当前预设", page))
        self._rule_detail_layout.addWidget(self._rule_current_preset_label)
        self._rule_detail_layout.addWidget(self._rule_preset_host)
        self._rule_detail_layout.addWidget(QLabel("后缀列表", page))
        self._rule_detail_layout.addWidget(self._rule_folder_note)
        self._rule_detail_layout.addWidget(self._rule_extension_panel)
        detail.addWidget(self._rule_detail_card, alignment=Qt.AlignmentFlag.AlignTop)
        detail.addStretch(1)
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
        self._history_card_preview_size = QSize(420, 240)
        self._history_grid_columns = 2
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
        registry = BuiltinWidgetRegistry()
        for definition in registry.available():
            card = self._build_widget_definition_card(definition, page)
            if definition.id == "clock":
                self._clock_widget_card = card
            layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        return page

    def _build_widget_definition_card(
        self,
        definition: WidgetDefinition,
        parent: QWidget,
    ) -> QFrame:
        visual = definition.visual
        card = QFrame(parent)
        card.setFixedSize(definition.default_width, definition.default_height)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { "
            f"background: {visual.card_background}; border: 1px solid {visual.accent_color}; "
            "border-radius: 12px; }"
            "QLabel { color: #ffffff; background: transparent; }"
            f"QPushButton {{ background: {visual.accent_color}; color: #111111; border-radius: 8px; font-weight: 700; }}"
        )
        card_layout = QVBoxLayout(card)
        header = QHBoxLayout()
        header.addWidget(QLabel(definition.display_name, card))
        header.addStretch(1)
        button = QPushButton("+", card)
        button.setFixedSize(34, 30)
        button.setToolTip(f"创建独立{definition.display_name}")
        button.clicked.connect(
            lambda _checked=False, widget_id=definition.id: self.add_widget_panel_requested.emit(widget_id)
        )
        if definition.id == "clock":
            self._add_clock_panel_button = button
        header.addWidget(button)
        card_layout.addLayout(header)
        preview = QLabel(f"{definition.preview_title}\n{definition.preview_body}", card)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedHeight(108)
        preview.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {visual.foreground}; "
            f"background: {visual.background}; "
            "border-radius: 12px; padding: 12px;"
        )
        if definition.id == "clock":
            self._clock_widget_preview = preview
        card_layout.addWidget(preview)
        return card

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
        self._other_page = page
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("其他", page))

        system_group = QGroupBox("系统位置", page)
        system_form = QFormLayout(system_group)
        self._desktop_path_edit = QLineEdit(self._config.desktop.path, system_group)
        browse = QPushButton("选择文件夹", system_group)
        browse.clicked.connect(self._browse_desktop_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self._desktop_path_edit)
        path_row.addWidget(browse)
        system_form.addRow("桌面路径", path_row)
        screen_row = QHBoxLayout()
        self._screen_hint_label = QLabel(
            f"显示器：{self._screen_label(self.selected_screen_id())}",
            system_group,
        )
        identify = QPushButton("识别", system_group)
        identify.clicked.connect(self.identify_screens_requested.emit)
        screen_row.addWidget(self._screen_hint_label)
        screen_row.addStretch(1)
        screen_row.addWidget(identify)
        system_form.addRow("显示器", screen_row)
        layout.addWidget(system_group)

        takeover_group = QGroupBox("启动与接管", page)
        takeover_layout = QVBoxLayout(takeover_group)
        self._takeover_checkbox = QCheckBox("启用桌面接管", takeover_group)
        self._takeover_checkbox.setChecked(self._config.desktop.takeover_enabled)
        self._startup_checkbox = QCheckBox("开机启动", takeover_group)
        self._startup_checkbox.setChecked(self._config.desktop.startup_enabled)
        self._takeover_status_label = QLabel("", takeover_group)
        takeover_layout.addWidget(self._takeover_checkbox)
        takeover_layout.addWidget(self._startup_checkbox)
        takeover_layout.addWidget(self._takeover_status_label)
        layout.addWidget(takeover_group)

        update_group = QGroupBox("软件更新", page)
        self._update_group = update_group
        update_layout = QVBoxLayout(update_group)
        self._update_current_version_label = QLabel(
            f"当前版本：{APP_VERSION}",
            update_group,
        )
        self._update_latest_version_label = QLabel("最新版本：未检查", update_group)
        self._update_status_label = QLabel("点击检查更新。", update_group)
        self._update_check_button = QPushButton("检查更新", update_group)
        self._update_download_button = QPushButton("下载更新", update_group)
        self._update_open_folder_button = QPushButton("打开更新文件夹", update_group)
        self._update_replace_button = QPushButton("替换并重启", update_group)
        self._update_download_button.setEnabled(False)
        self._update_replace_button.setEnabled(False)
        self._update_check_button.clicked.connect(self.update_check_requested.emit)
        self._update_download_button.clicked.connect(self.update_download_requested.emit)
        self._update_open_folder_button.clicked.connect(
            self.update_open_folder_requested.emit
        )
        self._update_replace_button.clicked.connect(self.update_replace_requested.emit)
        update_button_row = QHBoxLayout()
        update_button_row.addWidget(self._update_check_button)
        update_button_row.addWidget(self._update_download_button)
        update_button_row.addWidget(self._update_open_folder_button)
        update_button_row.addWidget(self._update_replace_button)
        update_button_row.addStretch(1)
        update_layout.addWidget(self._update_current_version_label)
        update_layout.addWidget(self._update_latest_version_label)
        update_layout.addWidget(self._update_status_label)
        update_layout.addLayout(update_button_row)
        layout.addWidget(update_group)

        recovery_group = QGroupBox("恢复工具", page)
        recovery_layout = QHBoxLayout(recovery_group)
        recovery_layout.addStretch(1)
        self._reset_delete_confirmations_button = QPushButton(
            "恢复删除确认提示",
            recovery_group,
        )
        self._reset_delete_confirmations_button.clicked.connect(
            self._reset_delete_confirmations
        )
        self._other_restore_desktop_button = QPushButton("恢复桌面图标", recovery_group)
        self._other_restore_desktop_button.clicked.connect(
            self.restore_desktop_requested.emit
        )
        recovery_layout.addWidget(self._other_restore_desktop_button)
        recovery_layout.addWidget(self._reset_delete_confirmations_button)
        layout.addWidget(recovery_group)
        layout.addStretch(1)
        self._update_takeover_status_label()
        return page

    def set_update_state(
        self,
        *,
        current_version: str = APP_VERSION,
        latest_version: str = "",
        message: str = "",
        update_available: bool = False,
        download_ready: bool = False,
        can_replace: bool = False,
        checking: bool = False,
        downloading: bool = False,
    ) -> None:
        if not hasattr(self, "_update_current_version_label"):
            return
        busy = checking or downloading
        self._update_current_version_label.setText(f"当前版本：{current_version}")
        self._update_latest_version_label.setText(
            f"最新版本：{latest_version or '未检查'}"
        )
        self._update_status_label.setText(message or "点击检查更新。")
        self._update_check_button.setEnabled(not busy)
        self._update_download_button.setEnabled(update_available and not busy)
        self._update_open_folder_button.setEnabled(not busy)
        self._update_replace_button.setEnabled(download_ready and can_replace and not busy)

    def set_history_snapshots(self, snapshots: list[object]) -> None:
        self._history_snapshots = list(snapshots)
        self._rebuild_history_grid(self._history_snapshots)

    def _rebuild_history_grid(self, snapshots: list[object]) -> None:
        while self._history_grid_layout.count():
            item = self._history_grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._history_cards = []
        self._history_grid_columns = self._history_columns_for_width(self.width())
        for index, snapshot in enumerate(snapshots):
            config = getattr(snapshot, "configuration", None)
            preview_tab_names = (
                shared_layout_preview_tab_names(config)
                if isinstance(config, Configuration)
                else []
            )
            icon = self._layout_preview_icon(snapshot)
            card = HistoryCardWidget(
                snapshot,
                icon,
                self._history_card_preview_size,
                preview_tab_names,
                self._history_grid_host,
            )
            card.restore_button.clicked.connect(
                lambda _checked=False, value=card.snapshot_id: self.history_restore_requested.emit(value)
            )
            row = index // self._history_grid_columns
            column = index % self._history_grid_columns
            self._history_grid_layout.addWidget(card, row, column)
            self._history_cards.append(card)

    def _reflow_history_grid_if_needed(self) -> None:
        if not hasattr(self, "_history_grid_layout") or not self._history_snapshots:
            return
        columns = self._history_columns_for_width(self.width())
        if columns == self._history_grid_columns:
            return
        self._rebuild_history_grid(self._history_snapshots)

    def _history_columns_for_width(self, width: int) -> int:
        if width >= 1560:
            return 3
        if width >= 980:
            return 2
        return 1

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
        painter.end()
        screens = self._screen_infos or [ScreenInfo("primary", "主屏", QRect(0, 0, 1920, 1080))]
        return QIcon(shared_render_layout_preview_pixmap(config, screens, size))

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
        if hasattr(self, "_delete_custom_rule_button"):
            self._delete_custom_rule_button.setEnabled(self._is_custom_rule(rule))
        self._rule_enabled_checkbox.blockSignals(True)
        self._rule_enabled_checkbox.setChecked(rule.enabled)
        self._rule_enabled_checkbox.blockSignals(False)
        self._rule_name_label.setText(rule.name)
        self._rule_type_label.setText("文件夹" if rule.matcher_kind == "folder" else "后缀匹配" if rule.matcher_kind == "extension" else "其它")
        self._rule_extension_editor.set_extensions(list(rule.extensions))
        preset_name = self._preset_name_for_extensions(rule.extensions)
        self._rule_current_preset_label.setText(f"当前预设：{preset_name or '自定义'}")
        self._sync_rule_preset_buttons(preset_name)
        is_folder_rule = rule.matcher_kind == "folder"
        self._rule_folder_note.setVisible(is_folder_rule)
        self._rule_extension_panel.setVisible(not is_folder_rule)
        self._rule_target_combo.clear()
        self._rule_target_combo.addItem("（无）", "")
        tab_names = self._classification_target_tabs()
        for tab_id, name in sorted(tab_names.items(), key=lambda item: item[1]):
            self._rule_target_combo.addItem(name, tab_id)
        index = self._rule_target_combo.findData(
            self._suggested_target_for_rule(rule, self._config)
        )
        if index >= 0:
            self._rule_target_combo.setCurrentIndex(index)

    def _is_custom_rule(self, rule) -> bool:  # type: ignore[no-untyped-def]
        return rule.id not in _DEFAULT_RULE_ROLES and rule.matcher_kind == "extension"

    def _classification_target_tabs(self) -> dict[str, str]:
        referenced_tab_ids = {
            rule.target_tab_id
            for rule in self._config.rules
            if rule.target_tab_id
        }
        return {
            tab.id: tab.name
            for tab in self._config.panel_tabs
            if tab.content_kind == "items"
            and (tab.category_role != "custom" or tab.id in referenced_tab_ids)
        }

    def _create_custom_classification_type(self) -> None:
        name = self._custom_type_name_edit.text().strip()
        if not name:
            return
        model = WorkspaceModel(self._config)
        _tab, rule = model.create_custom_classification_type(self._group_id, name)
        self._custom_type_name_edit.clear()
        self._reload_panel_management(self._config)
        self._reload_rules_editor()
        self._select_rule_by_id(rule.id)
        self.management_metadata_changed.emit()

    def _delete_current_custom_rule(self) -> None:
        rule_id = self._current_rule_id()
        rule = next((entry for entry in self._config.rules if entry.id == rule_id), None)
        if rule is None or not self._is_custom_rule(rule):
            return
        model = WorkspaceModel(self._config)
        model.delete_classification_rule(rule_id)
        self._reload_rules_editor()
        self.management_metadata_changed.emit()

    def _select_rule_by_id(self, rule_id: str) -> None:
        for row in range(self._rule_list.count()):
            item = self._rule_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == rule_id:
                self._rule_list.setCurrentRow(row)
                return

    def _preset_name_for_extensions(self, extensions: list[str]) -> str:
        normalized = {extension.lower() for extension in extensions}
        for name, preset_extensions in _EXTENSION_PRESETS.items():
            if normalized == {extension.lower() for extension in preset_extensions}:
                return name
        return ""

    def _apply_rule_preset(self, name: str) -> None:
        if not hasattr(self, "_rule_extension_editor"):
            return
        self._rule_extension_editor.set_extensions([])
        self._rule_extension_editor.apply_preset(name)
        self._rule_current_preset_label.setText(f"当前预设：{name}")
        self._sync_rule_preset_buttons(name)

    def _sync_rule_preset_buttons(self, selected_name: str) -> None:
        for name, button in self._rule_preset_buttons.items():
            checked = name == selected_name
            button.setChecked(checked)
            button.setStyleSheet(
                "QPushButton { padding: 4px 18px; }"
                + (
                    "QPushButton { background: #d99abd; color: #111111; border: 1px solid #f2c4db; }"
                    if checked
                    else ""
                )
            )

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
        config.appearance_defaults.background_color = self.panel_background_color()
        config.appearance_defaults.background_opacity = self.panel_background_opacity()
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
        target.appearance_defaults.background_color = source.appearance_defaults.background_color
        target.appearance_defaults.background_opacity = source.appearance_defaults.background_opacity
        for source_panel_group in source.panel_groups:
            matching = next(
                (entry for entry in target.panel_groups if entry.id == source_panel_group.id),
                None,
            )
            if matching is None:
                continue
            matching.appearance.background_color = source_panel_group.appearance.background_color
            matching.appearance.background_opacity = source_panel_group.appearance.background_opacity
            matching.appearance.item_icon_size = source_panel_group.appearance.item_icon_size

    def _select_color(self, color: str) -> None:
        self._selected_color = color
        self._sync_color_swatch_states()
        self._emit_appearance_live_changed()

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
            self._select_color(color.name().upper())

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
        self._emit_appearance_live_changed()

    def _sync_opacity_from_spinbox(self, value: int) -> None:
        if self._opacity_slider.value() != value:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(value)
            self._opacity_slider.blockSignals(False)
        self._emit_appearance_live_changed()

    def _emit_appearance_live_changed(self) -> None:
        if not hasattr(self, "_opacity_slider"):
            return
        group = self._target_group()
        group.appearance.background_color = self.panel_background_color()
        group.appearance.background_opacity = self.panel_background_opacity()
        self.appearance_live_changed.emit(
            self._group_id,
            self.panel_background_color(),
            self.panel_background_opacity(),
        )
        self._appearance_save_timer.start()

    def _emit_appearance_save_requested(self) -> None:
        self.appearance_live_save_requested.emit(self._group_id)

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
        self._begin_panel_inline_rename_by_id(group_id)

    def _rename_tab_from_item(self, item: QListWidgetItem) -> None:
        tab_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._begin_tab_inline_rename_by_id(tab_id)

    def _begin_panel_inline_rename_by_id(self, group_id: str) -> None:
        for row in range(self._panel_group_list.count()):
            item = self._panel_group_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == group_id:
                self._panel_group_list.setCurrentRow(row)
                self._begin_inline_edit("panel", group_id, self._panel_group_list, item)
                break

    def _begin_tab_inline_rename_by_id(self, tab_id: str) -> None:
        tab = next((entry for entry in self._config.panel_tabs if entry.id == tab_id), None)
        if tab is None:
            return
        self._select_panel_from_preview(tab.group_id)
        for row in range(self._panel_tab_list.count()):
            item = self._panel_tab_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == tab_id:
                self._panel_tab_list.setCurrentRow(row)
                self._begin_inline_edit("tab", tab_id, self._panel_tab_list, item)
                break

    def _begin_inline_edit(
        self,
        kind: str,
        target_id: str,
        list_widget: QListWidget,
        item: QListWidgetItem,
    ) -> None:
        self._inline_edit_kind = kind
        self._inline_edit_id = target_id
        editor = self._panel_inline_editor
        editor.setParent(list_widget.viewport())
        rect = list_widget.visualItemRect(item).adjusted(8, 4, -40, -4)
        editor.setGeometry(rect)
        label = item.text()
        if label.startswith("当前 · "):
            label = label.replace("当前 · ", "", 1)
        editor.setText(label)
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        editor.selectAll()

    def _finish_inline_edit(self) -> None:
        editor = self._panel_inline_editor
        if not editor.isVisible():
            return
        kind = self._inline_edit_kind
        target_id = self._inline_edit_id
        value = editor.text()
        editor.hide()
        self._inline_edit_kind = ""
        self._inline_edit_id = ""
        if kind == "panel":
            self._commit_panel_rename(target_id, value)
        elif kind == "tab":
            self._commit_tab_rename(target_id, value)

    def _commit_panel_rename(self, group_id: str, value: str) -> None:
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None:
            return
        group.name = value.strip() or "未命名面板"
        self._reload_panel_management(self._config)
        self.management_metadata_changed.emit()

    def _commit_tab_rename(self, tab_id: str, value: str) -> None:
        tab = next((entry for entry in self._config.panel_tabs if entry.id == tab_id), None)
        if tab is None:
            return
        tab.name = value.strip() or "未命名标签"
        self._reload_panel_management(self._config)
        self.management_metadata_changed.emit()

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
        if not hasattr(self, "_basic_page"):
            return ""
        return self._widget_text(self._basic_page)

    def _panel_management_page_text(self) -> str:
        return self._widget_text(self._panel_management_page)

    def _rules_page_text(self) -> str:
        return self._widget_text(self._rules_page)

    def _other_page_text(self) -> str:
        return self._widget_text(self._other_page)
