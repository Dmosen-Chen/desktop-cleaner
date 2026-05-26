"""Qt settings surface for the desktop panel preview."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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

_SECTIONS = ["基础设置", "桌面分区", "桌面整理", "面板外观"]
_OPACITY_MIN = 0.18
_OPACITY_MAX = 0.95
_DEFAULT_RULE_ROLES = {
    "rule-folders": "folders",
    "rule-documents": "documents",
    "rule-images": "images",
    "rule-archives": "archives",
    "rule-apps": "apps",
    "rule-other": "other",
}


class SettingsWindow(QWidget):
    config_saved = Signal()
    validation_failed = Signal(str)

    def __init__(
        self,
        config: Configuration,
        *,
        group_id: str | None = None,
        screen_options: list[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._group_id = group_id or config.panel_groups[0].id
        self._screen_options = screen_options or available_screen_options()
        self.setWindowTitle("设置")
        self.resize(720, 520)

        self._section_list = QListWidget(self)
        for name in _SECTIONS:
            self._section_list.addItem(QListWidgetItem(name))
        self._section_list.setFixedWidth(140)

        self._pages = QStackedWidget(self)
        self._pages.addWidget(self._build_basic_page())
        self._pages.addWidget(self._build_partition_page())
        self._pages.addWidget(self._build_rules_page())
        self._pages.addWidget(self._build_appearance_page())

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
        self._reload_screen_combo(config)
        self._reload_rules_table()
        group = self._target_group(config)
        self._color_edit.setText(group.appearance.background_color)
        opacity = group.appearance.background_opacity
        self._opacity_value.blockSignals(True)
        self._opacity_value.setValue(opacity)
        self._opacity_value.blockSignals(False)
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(self._opacity_to_slider(opacity))
        self._opacity_slider.blockSignals(False)

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
        for row in range(self._rules_table.rowCount()):
            for column in range(self._rules_table.columnCount()):
                item = self._rules_table.item(row, column)
                if item is not None:
                    parts.append(item.text())
        return "\n".join(part for part in parts if part)

    def panel_background_color(self) -> str:
        return self._color_edit.text().strip()

    def panel_background_opacity(self) -> float:
        return self._opacity_value.value()

    def panel_opacity_minimum(self) -> float:
        return _OPACITY_MIN

    def panel_opacity_maximum(self) -> float:
        return _OPACITY_MAX

    def selected_screen_id(self) -> str:
        return str(self._screen_combo.currentData() or "primary")

    def _build_basic_page(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        self._desktop_path_edit = QLineEdit(self._config.desktop.path, page)
        browse = QPushButton("选择文件夹", page)
        browse.clicked.connect(self._browse_desktop_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self._desktop_path_edit)
        path_row.addWidget(browse)
        self._screen_combo = QComboBox(page)
        self._reload_screen_combo(self._config)
        form.addRow("\u663e\u793a\u5668", self._screen_combo)
        form.addRow("桌面路径", path_row)
        self._takeover_checkbox = QCheckBox("启用桌面接管（仅预览）", page)
        self._takeover_checkbox.setChecked(self._config.desktop.takeover_enabled)
        form.addRow(self._takeover_checkbox)
        self._startup_checkbox = QCheckBox("开机启动", page)
        self._startup_checkbox.setChecked(self._config.desktop.startup_enabled)
        form.addRow(self._startup_checkbox)
        return page

    def _reload_screen_combo(self, config: Configuration) -> None:
        current = self._target_group(config).screen_id or config.desktop.primary_screen_id
        self._screen_combo.blockSignals(True)
        self._screen_combo.clear()
        for screen_id, label in self._screen_options:
            self._screen_combo.addItem(label, screen_id)
        index = self._screen_combo.findData(current)
        if index < 0:
            index = self._screen_combo.findData("primary")
        self._screen_combo.setCurrentIndex(max(0, index))
        self._screen_combo.blockSignals(False)

    def _build_partition_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel("默认面板组包含六个分类标签，可在预览面板中增删标签。", page)
        )
        for group in self._config.panel_groups:
            layout.addWidget(QLabel(f"面板组：{group.id}", page))
            for tab_id in group.tab_ids:
                tab = next(
                    (entry for entry in self._config.panel_tabs if entry.id == tab_id),
                    None,
                )
                if tab is not None:
                    layout.addWidget(QLabel(f"  · {tab.name} ({tab.id})", page))
        layout.addStretch(1)
        return page

    def _build_rules_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("分类规则", page))
        self._rules_table = QTableWidget(0, 4, page)
        self._rules_table.setHorizontalHeaderLabels(
            ["启用", "名称", "扩展名", "目标标签"]
        )
        self._reload_rules_table()
        layout.addWidget(self._rules_table)
        return page

    def _build_appearance_page(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        group = self._target_group()
        self._color_edit = QLineEdit(group.appearance.background_color, page)
        form.addRow("背景颜色", self._color_edit)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, page)
        self._opacity_slider.setMinimum(0)
        self._opacity_slider.setMaximum(1000)
        self._opacity_slider.setValue(self._opacity_to_slider(group.appearance.background_opacity))
        self._opacity_value = QDoubleSpinBox(page)
        self._opacity_value.setRange(_OPACITY_MIN, _OPACITY_MAX)
        self._opacity_value.setSingleStep(0.01)
        self._opacity_value.setDecimals(2)
        self._opacity_value.setValue(group.appearance.background_opacity)
        self._opacity_slider.valueChanged.connect(self._sync_opacity_spin_from_slider)
        self._opacity_value.valueChanged.connect(self._sync_opacity_slider_from_spin)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self._opacity_slider, stretch=1)
        opacity_row.addWidget(self._opacity_value)
        form.addRow("背景透明度", opacity_row)
        return page

    def _reload_rules_table(self) -> None:
        rules = sorted(self._config.rules, key=lambda entry: entry.order)
        self._rules_table.setRowCount(len(rules))
        tab_names = {tab.id: tab.name for tab in self._config.panel_tabs}
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
            extensions = ", ".join(rule.extensions)
            self._rules_table.setItem(row, 2, QTableWidgetItem(extensions))
            target = QComboBox(self._rules_table)
            target.addItem("（无）", "")
            for tab_id, name in sorted(tab_names.items(), key=lambda item: item[1]):
                target.addItem(name, tab_id)
            index = target.findData(self._suggested_target_for_rule(rule, self._config))
            if index >= 0:
                target.setCurrentIndex(index)
            self._rules_table.setCellWidget(row, 3, target)

    def _suggested_target_for_rule(self, rule, config: Configuration) -> str:  # type: ignore[no-untyped-def]
        tab_ids = {tab.id for tab in config.panel_tabs}
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
            if tab.category_role == role:
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
        self._copy_configuration_state(candidate, self._config)
        self.config_saved.emit()
        self.hide()

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
            extensions_item = self._rules_table.item(row, 2)
            if extensions_item is not None:
                raw = extensions_item.text().replace(" ", "")
                extensions = [
                    extension if extension.startswith(".") else f".{extension}"
                    for extension in raw.split(",")
                    if extension
                ]
            else:
                extensions = list(rule.extensions)
            target_widget = self._rules_table.cellWidget(row, 3)
            if isinstance(target_widget, QComboBox):
                target_tab_id = str(target_widget.currentData() or "")
            else:
                target_tab_id = rule.target_tab_id
            if enabled:
                tab_ids = {tab.id for tab in config.panel_tabs}
                if target_tab_id not in tab_ids:
                    target_tab_id = self._suggested_target_for_rule(rule, config)
            target = rules_by_id[rule.id]
            target.enabled = enabled
            target.extensions = extensions
            target.target_tab_id = target_tab_id
        group = self._target_group(config)
        group.screen_id = self.selected_screen_id()
        group.appearance.background_color = self.panel_background_color()
        group.appearance.background_opacity = self._opacity_value.value()

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

    def _opacity_to_slider(self, opacity: float) -> int:
        span = _OPACITY_MAX - _OPACITY_MIN
        normalized = (opacity - _OPACITY_MIN) / span if span else 0.0
        return int(round(max(0.0, min(1.0, normalized)) * 1000))

    def _slider_to_opacity(self, value: int) -> float:
        span = _OPACITY_MAX - _OPACITY_MIN
        return _OPACITY_MIN + (value / 1000.0) * span

    def _sync_opacity_spin_from_slider(self, value: int) -> None:
        self._opacity_value.blockSignals(True)
        self._opacity_value.setValue(self._slider_to_opacity(value))
        self._opacity_value.blockSignals(False)

    def _sync_opacity_slider_from_spin(self, value: float) -> None:
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(self._opacity_to_slider(value))
        self._opacity_slider.blockSignals(False)
