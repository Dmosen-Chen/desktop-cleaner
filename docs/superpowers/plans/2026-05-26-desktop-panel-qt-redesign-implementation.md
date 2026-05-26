# Desktop Panel PySide6 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile Tkinter desktop overlay with a PySide6 Windows desktop-layer entrance manager that classifies entries without modifying source files and restores Explorer icons safely.

**Architecture:** Build a new `desktop_tidy` package alongside the old application, beginning with a pure-Python domain/config/index core and tests. Add Qt views and a narrowly isolated Windows shell adapter through testable controllers, then switch `main.py` and packaging only after the new path passes automated and manual recovery checks.

**Tech Stack:** Python 3.10+, PySide6, standard-library `dataclasses`/`json`/`ctypes`, `unittest`, PyInstaller, Windows Shell APIs.

---

## Scope And Milestone Gates

The approved design spans four risk areas: persisted data and migration, live classification, interactive Qt panels, and Explorer desktop integration. They remain in one product plan because they converge on one shipped application, but execution must stop at each gate before starting the next risk area:

| Milestone | Result users can verify | Gate |
| --- | --- | --- |
| M1 Core | New configuration can migrate safely and classify a chosen desktop without mutating files | All core unit tests pass against temporary directories |
| M2 Qt Preview | Qt window renders panels, tabs, icons, drag/drop references and settings without desktop takeover | Offscreen widget tests pass; interactive preview accepted |
| M3 Desktop Layer | Desktop-layer attachment, icon hide/restore and crash recovery work on Windows | Recovery smoke checklist completed before default takeover is enabled |
| M4 Release | New entrypoint and single-file `exe` use only the Qt product surface | Full tests plus packaged executable smoke test pass |

No implementation step may add real file archive, `.url` creation, wallpaper assets, search, AI, or synchronization features.

## File Structure

Create a focused new package and leave the old Tkinter code untouched until the cutover task:

```text
desktop_tidy/
  __init__.py                  # package/version marker
  application.py               # QApplication wiring and lifecycle
  domain/
    __init__.py
    models.py                  # persisted entities and geometry
    defaults.py                # default tabs, rules, appearance
    classification.py          # rules and manual override resolution
    workspace.py               # application model commands
  persistence/
    __init__.py
    config_store.py            # schema v2 load/save and atomic writes
    migration.py               # old JSON backup and conversion
  services/
    __init__.py
    desktop_index.py           # desktop scans and QFileSystemWatcher bridge
    windows_shell.py           # Win32 desktop parent/icons/startup operations
    takeover.py                # failure-safe desktop integration controller
    item_visuals.py            # native icons and image thumbnails
  resources/
    __init__.py
    default_config.json        # schema v2 first-run template
  ui/
    __init__.py
    panel_group.py             # translucent panel/group shell and drag/resize
    item_grid.py               # grid view, label elision and file drops
    settings_window.py         # supported settings only
    tray.py                    # Qt system tray controls
qt_main.py                     # development launcher until final cutover
main.py                        # final thin Qt entrypoint after M3 acceptance
config.default.json            # legacy Tk resource, retained until final cutover
DesktopTidy.spec               # PyInstaller Qt packaging
scripts/build_exe.bat          # release build command
requirements.txt               # PySide6 runtime dependency
requirements-build.txt         # PyInstaller build dependency
tests/
  test_models.py
  test_config_store.py
  test_migration.py
  test_classification.py
  test_desktop_index.py
  test_workspace.py
  test_takeover.py
  test_qt_panel_group.py
  test_qt_item_grid.py
  test_qt_settings.py
docs/
  superpowers/specs/2026-05-25-desktop-panel-qt-redesign-design.md
  verification/qt-v1-windows-smoke-checklist.md
README.md
```

Files retired at cutover, after the new application no longer imports them:

- Delete: `partition_overlay.py`, `tray_support.py`, `organizer.py`
- Delete: `config.default.json`
- Delete/replace: `tests/test_partition_overlay.py`, `tests/test_collect_rules.py`, `tests/test_organizer.py`

## Persisted Schema Contract

Use schema version `2`. This exact structure is the boundary between core, UI and migration work:

```json
{
  "schema_version": 2,
  "desktop": {
    "path": "E:\\system\\桌面",
    "takeover_enabled": false,
    "restore_required": false,
    "explorer_icons_hidden": false,
    "startup_enabled": false,
    "primary_screen_id": "primary"
  },
  "appearance_defaults": {
    "background_color": "#111111",
    "background_opacity": 0.6
  },
  "panel_groups": [],
  "panel_tabs": [],
  "rules": [],
  "manual_overrides": [],
  "external_refs": []
}
```

Real items found under `desktop.path` are never written into this document. Only `external_refs` and `manual_overrides` represent saved item placement.
The empty arrays above document the JSON shape only. On first run, `build_default_configuration()` populates one group, the six required tabs and their default rules before the configuration is saved.

### Task 1: Create The New Package And Domain Models

**Files:**
- Create: `desktop_tidy/__init__.py`
- Create: `desktop_tidy/domain/__init__.py`
- Create: `desktop_tidy/domain/models.py`
- Create: `desktop_tidy/domain/defaults.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for defaults, serialization and alpha semantics**

```python
# tests/test_models.py
import unittest

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import Configuration, ItemRef


class ModelTests(unittest.TestCase):
    def test_default_configuration_has_one_unlocked_six_tab_group(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        self.assertEqual(config.schema_version, 2)
        self.assertEqual(len(config.panel_groups), 1)
        group = config.panel_groups[0]
        self.assertFalse(group.locked)
        self.assertEqual(config.appearance_defaults.background_color, "#111111")
        self.assertEqual(config.appearance_defaults.background_opacity, 0.60)
        self.assertEqual(
            [tab.name for tab in config.panel_tabs],
            ["文件夹", "文档", "图片", "压缩包", "应用", "其它"],
        )
        self.assertEqual(group.tab_ids, [tab.id for tab in config.panel_tabs])

    def test_real_desktop_items_are_not_serialized_as_references(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        config.external_refs.append(
            ItemRef(id="external-1", source_kind="external", canonical_path=r"D:\draft\readme.md", target_tab_id="tab-other")
        )
        payload = config.to_dict()
        self.assertEqual(payload["external_refs"][0]["source_kind"], "external")
        self.assertNotIn("desktop_items", payload)
        self.assertEqual(Configuration.from_dict(payload).external_refs[0].canonical_path, r"D:\draft\readme.md")
```

- [ ] **Step 2: Run the tests to establish the red state**

Run: `python -m unittest tests.test_models -v`  
Expected: `ModuleNotFoundError: No module named 'desktop_tidy'`.

- [ ] **Step 3: Implement dataclasses and default construction**

Use dataclasses with explicit `to_dict()` and `from_dict()` conversions. The important public surface is:

```python
# desktop_tidy/domain/models.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class AppearanceSettings:
    background_color: str = "#111111"
    background_opacity: float = 0.60


@dataclass
class PanelGeometry:
    rx: float = 0.04
    ry: float = 0.04
    rw: float = 0.72
    rh: float = 0.62


@dataclass
class PanelGroup:
    id: str
    screen_id: str
    geometry: PanelGeometry
    tab_ids: list[str]
    active_tab_id: str
    appearance: AppearanceSettings
    locked: bool = False
    collapsed: bool = False


@dataclass
class PanelTab:
    id: str
    group_id: str
    name: str
    order: int
    category_role: str = "custom"


@dataclass
class ItemRef:
    id: str
    source_kind: str
    canonical_path: str
    target_tab_id: str


@dataclass
class ClassificationRule:
    id: str
    name: str
    matcher_kind: str
    target_tab_id: str
    extensions: list[str] = field(default_factory=list)
    enabled: bool = True
    order: int = 0


@dataclass
class ManualOverride:
    canonical_path: str
    target_tab_id: str


@dataclass
class DesktopIntegrationState:
    path: str
    takeover_enabled: bool = False
    restore_required: bool = False
    explorer_icons_hidden: bool = False
    startup_enabled: bool = False
    primary_screen_id: str = "primary"


@dataclass
class Configuration:
    schema_version: int
    desktop: DesktopIntegrationState
    appearance_defaults: AppearanceSettings
    panel_groups: list[PanelGroup]
    panel_tabs: list[PanelTab]
    rules: list[ClassificationRule]
    manual_overrides: list[ManualOverride] = field(default_factory=list)
    external_refs: list[ItemRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Configuration":
        desktop = DesktopIntegrationState(**dict(payload["desktop"]))
        defaults = AppearanceSettings(**dict(payload["appearance_defaults"]))
        groups = []
        for raw in payload.get("panel_groups", []):
            item = dict(raw)
            item["geometry"] = PanelGeometry(**dict(item["geometry"]))
            item["appearance"] = AppearanceSettings(**dict(item["appearance"]))
            groups.append(PanelGroup(**item))
        return cls(
            schema_version=int(payload["schema_version"]),
            desktop=desktop,
            appearance_defaults=defaults,
            panel_groups=groups,
            panel_tabs=[PanelTab(**dict(item)) for item in payload.get("panel_tabs", [])],
            rules=[ClassificationRule(**dict(item)) for item in payload.get("rules", [])],
            manual_overrides=[ManualOverride(**dict(item)) for item in payload.get("manual_overrides", [])],
            external_refs=[ItemRef(**dict(item)) for item in payload.get("external_refs", [])],
        )
```

`desktop_tidy/domain/defaults.py` must create stable tab IDs (`tab-folders`, `tab-documents`, `tab-images`, `tab-archives`, `tab-apps`, `tab-other`), one `group-default`, group-level black/`0.60` appearance, and enabled default classification rules targeting those IDs.

- [ ] **Step 4: Run the domain model tests**

Run: `python -m unittest tests.test_models -v`  
Expected: both tests pass.

- [ ] **Step 5: Commit the core types**

```powershell
git add desktop_tidy tests/test_models.py
git commit -m "feat: add qt desktop domain models and defaults"
```

### Task 2: Add Atomic Configuration Storage And Legacy Migration

**Files:**
- Create: `desktop_tidy/persistence/__init__.py`
- Create: `desktop_tidy/persistence/config_store.py`
- Create: `desktop_tidy/persistence/migration.py`
- Create: `desktop_tidy/resources/__init__.py`
- Create: `desktop_tidy/resources/default_config.json`
- Create: `tests/test_config_store.py`
- Create: `tests/test_migration.py`

- [ ] **Step 1: Write tests for atomic v2 persistence, legacy backup and clean reconstruction**

```python
# tests/test_migration.py
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.persistence.migration import load_or_migrate


class MigrationTests(unittest.TestCase):
    def test_legacy_config_is_backed_up_and_rebuilt_with_external_refs_only(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            desktop = base / "desktop"
            desktop.mkdir()
            external = base / "outside" / "notes.pdf"
            external.parent.mkdir()
            external.write_text("pdf", encoding="utf-8")
            legacy_link = desktop / "old-external.url"
            legacy_link.write_text("[InternetShortcut]\nURL=" + external.resolve().as_uri() + "\n", encoding="utf-8")
            legacy = {
                "desktop": str(desktop),
                "ui": {
                    "startup_enabled": True,
                    "partitions": [
                        {
                            "name": "乱标签",
                            "items": [
                                {"path": str(desktop / "inside.txt")},
                                {"path": str(external)},
                                {"path": str(legacy_link)},
                            ],
                        }
                    ],
                },
            }
            config_path = base / "config.json"
            config_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

            config = load_or_migrate(config_path)

            self.assertEqual(config.desktop.path, str(desktop))
            self.assertTrue(config.desktop.startup_enabled)
            self.assertEqual([tab.name for tab in config.panel_tabs], ["文件夹", "文档", "图片", "压缩包", "应用", "其它"])
            self.assertEqual([ref.canonical_path for ref in config.external_refs], [str(external.resolve())])
            self.assertEqual(list(base.glob("config.pre-qt-v1-*.json")).__len__(), 1)
```

Also add `tests/test_config_store.py` asserting `ConfigurationStore.save()` writes valid JSON through a temporary file replacement and a corrupt JSON is copied to `config.corrupt-*.json` before defaults are returned.

- [ ] **Step 2: Verify the new tests fail before persistence exists**

Run: `python -m unittest tests.test_config_store tests.test_migration -v`  
Expected: imports fail because `desktop_tidy.persistence` has not been created.

- [ ] **Step 3: Implement storage and migration**

`ConfigurationStore` must have this interface and use `os.replace()` for atomic writes:

```python
class ConfigurationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def default(cls) -> "ConfigurationStore":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DesktopTidy"
        return cls(base / "config.json")

    def load(self) -> Configuration:
        return load_or_migrate(self.path)

    def save(self, config: Configuration) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
```

`load_or_migrate()` must:

1. Return defaults if the file does not exist.
2. Parse schema version `2` through `Configuration.from_dict()`.
3. For legacy JSON, copy the original to `config.pre-qt-v1-<timestamp>.json`.
4. Preserve only desktop path, startup preference, valid uniform color/alpha, and item paths outside the configured desktop.
5. If a legacy saved item is a `.url` file under the desktop and its `URL=file:///...` target resolves outside the desktop, import the target once as an external virtual reference.
6. Convert outside paths to `ItemRef(source_kind="external")` targeting `tab-other`; deduplicate by canonical target path and never write `.url` or touch source paths.
7. Quarantine malformed JSON as `config.corrupt-<timestamp>.json` and return defaults.

Create `desktop_tidy/resources/default_config.json` from the serialized output of `build_default_configuration()` for the configured default desktop path. It must contain one group, all six default tabs and enabled default rules; it must not ship an empty first-run layout. Leave the root `config.default.json` unchanged until final cutover so the legacy Tk launcher can still run during Qt preview development.

- [ ] **Step 4: Run migration and model tests**

Run: `python -m unittest tests.test_models tests.test_config_store tests.test_migration -v`  
Expected: all tests pass and temporary-directory assertions confirm no source files change.

- [ ] **Step 5: Commit configuration migration**

```powershell
git add desktop_tidy/persistence desktop_tidy/resources tests/test_config_store.py tests/test_migration.py
git commit -m "feat: migrate desktop configuration to qt schema"
```

### Task 3: Implement Rule Classification, Overrides And Virtual References

**Files:**
- Create: `desktop_tidy/domain/classification.py`
- Create: `desktop_tidy/domain/workspace.py`
- Create: `tests/test_classification.py`
- Create: `tests/test_workspace.py`

- [ ] **Step 1: Write failing tests for classification precedence and metadata-only item commands**

```python
# tests/test_classification.py
import unittest
from pathlib import Path

from desktop_tidy.domain.classification import classify_path
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import ManualOverride


class ClassificationTests(unittest.TestCase):
    def test_manual_override_wins_over_matching_extension(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        path = Path(r"E:\system\桌面\cover.png")
        config.manual_overrides.append(ManualOverride(str(path).casefold(), "tab-documents"))
        self.assertEqual(classify_path(path, config), "tab-documents")

    def test_unknown_extension_targets_other(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        self.assertEqual(classify_path(Path(r"E:\system\桌面\blob.abc"), config), "tab-other")
```

```python
# tests/test_workspace.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.workspace import WorkspaceModel


class WorkspaceTests(unittest.TestCase):
    def test_external_drop_saves_reference_without_changing_source_or_desktop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "anything.custom"
            source.write_text("content", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(str(desktop)))

            model.add_paths_to_tab([source], "tab-images")

            self.assertTrue(source.is_file())
            self.assertEqual(list(desktop.iterdir()), [])
            self.assertEqual(model.config.external_refs[0].target_tab_id, "tab-images")

    def test_desktop_drop_creates_override_not_external_reference(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            source = desktop / "photo.png"
            source.write_text("img", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(str(desktop)))
            model.add_paths_to_tab([source], "tab-documents")
            self.assertEqual(model.config.external_refs, [])
            self.assertEqual(model.config.manual_overrides[0].target_tab_id, "tab-documents")
```

- [ ] **Step 2: Run tests and observe the missing classification/workspace modules**

Run: `python -m unittest tests.test_classification tests.test_workspace -v`  
Expected: module import failures.

- [ ] **Step 3: Implement classification and workspace commands**

Implement normalized Windows keys with `str(path.resolve()).casefold()`, hide `desktop.ini`, `~$*`, and hidden/system entries in the index layer, and keep command methods free of file writes:

```python
def canonical_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def classify_path(path: Path, config: Configuration) -> str:
    key = canonical_key(path)
    override = next((entry for entry in config.manual_overrides if entry.canonical_path == key), None)
    if override:
        return override.target_tab_id
    for rule in sorted((rule for rule in config.rules if rule.enabled), key=lambda rule: rule.order):
        if rule.matcher_kind == "folder" and path.is_dir():
            return rule.target_tab_id
        if rule.matcher_kind == "extension" and path.suffix.casefold() in rule.extensions:
            return rule.target_tab_id
    return "tab-other"


class WorkspaceModel:
    def set_manual_override(self, path: Path, tab_id: str) -> None:
        key = canonical_key(path)
        self.config.manual_overrides = [
            entry for entry in self.config.manual_overrides if entry.canonical_path != key
        ]
        self.config.manual_overrides.append(ManualOverride(key, tab_id))

    def add_external_reference(self, path: Path, tab_id: str) -> None:
        key = canonical_key(path)
        self.config.external_refs = [
            entry for entry in self.config.external_refs if canonical_key(Path(entry.canonical_path)) != key
        ]
        self.config.external_refs.append(
            ItemRef(id=f"external-{uuid.uuid4().hex}", source_kind="external", canonical_path=str(path), target_tab_id=tab_id)
        )

    def add_paths_to_tab(self, paths: list[Path], tab_id: str) -> None:
        for path in paths:
            resolved = path.resolve()
            if is_inside(resolved, Path(self.config.desktop.path)):
                self.set_manual_override(resolved, tab_id)
            else:
                self.add_external_reference(resolved, tab_id)

    def restore_auto_classification(self, path: Path) -> None:
        key = canonical_key(path)
        self.config.manual_overrides = [entry for entry in self.config.manual_overrides if entry.canonical_path != key]
```

- [ ] **Step 4: Run core logic tests**

Run: `python -m unittest tests.test_models tests.test_config_store tests.test_migration tests.test_classification tests.test_workspace -v`  
Expected: all tests pass.

- [ ] **Step 5: Commit metadata-only classification**

```powershell
git add desktop_tidy/domain tests/test_classification.py tests/test_workspace.py
git commit -m "feat: classify desktop entries without file mutation"
```

### Task 4: Build Real-Time Desktop Indexing

**Files:**
- Create: `desktop_tidy/services/__init__.py`
- Create: `desktop_tidy/services/desktop_index.py`
- Create: `tests/test_desktop_index.py`

- [ ] **Step 1: Write failing scan/diff tests**

```python
# tests/test_desktop_index.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.services.desktop_index import DesktopIndex


class DesktopIndexTests(unittest.TestCase):
    def test_scan_accepts_any_format_and_suppresses_system_noise(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            (desktop / "note.unusual").write_text("x", encoding="utf-8")
            (desktop / "desktop.ini").write_text("x", encoding="utf-8")
            (desktop / "~$draft.docx").write_text("x", encoding="utf-8")
            entries = DesktopIndex(desktop).scan()
            self.assertEqual([entry.path.name for entry in entries], ["note.unusual"])

    def test_rescan_reports_add_remove_and_rename_as_model_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            index = DesktopIndex(desktop)
            index.rescan()
            source = desktop / "before.txt"
            source.write_text("x", encoding="utf-8")
            added = index.rescan()
            source.rename(desktop / "after.txt")
            changed = index.rescan()
            self.assertEqual([item.path.name for item in added.added], ["before.txt"])
            self.assertEqual([item.path.name for item in changed.added], ["after.txt"])
            self.assertEqual([item.path.name for item in changed.removed], ["before.txt"])
```

- [ ] **Step 2: Run the test to prove the service is missing**

Run: `python -m unittest tests.test_desktop_index -v`  
Expected: module import failure.

- [ ] **Step 3: Implement the pure scan/diff service and Qt watcher adapter**

`DesktopIndex.scan()` must only read directory entries. Add a `DesktopWatcher(QObject)` wrapper using `QFileSystemWatcher.directoryChanged` to call `rescan()` and emit a `changed` signal carrying the new model change set:

```python
@dataclass(frozen=True)
class IndexedItem:
    path: Path


@dataclass(frozen=True)
class IndexChanges:
    current: list[IndexedItem]
    added: list[IndexedItem]
    removed: list[IndexedItem]


class DesktopIndex:
    def __init__(self, desktop: Path) -> None:
        self.desktop = desktop
        self._last: dict[str, IndexedItem] = {}

    def scan(self) -> list[IndexedItem]:
        return [
            IndexedItem(entry.resolve())
            for entry in sorted(self.desktop.iterdir(), key=lambda item: item.name.casefold())
            if should_display(entry)
        ]

    def rescan(self) -> IndexChanges:
        current = {canonical_key(item.path): item for item in self.scan()}
        changes = IndexChanges(
            current=list(current.values()),
            added=[current[key] for key in current.keys() - self._last.keys()],
            removed=[self._last[key] for key in self._last.keys() - current.keys()],
        )
        self._last = current
        return changes


def should_display(entry: Path) -> bool:
    lowered = entry.name.casefold()
    if lowered == "desktop.ini" or lowered.startswith("~$"):
        return False
    return not bool(entry.stat().st_file_attributes & 0x6) if hasattr(entry.stat(), "st_file_attributes") else True
```

Import `canonical_key` from `desktop_tidy.domain.classification`; the index service must not create its own differing path normalization rule.

- [ ] **Step 4: Run all non-UI tests**

Run: `python -m unittest tests.test_models tests.test_config_store tests.test_migration tests.test_classification tests.test_workspace tests.test_desktop_index -v`  
Expected: all tests pass.

- [ ] **Step 5: Commit desktop indexing**

```powershell
git add desktop_tidy/services tests/test_desktop_index.py
git commit -m "feat: index and watch desktop entries in real time"
```

### Task 5: Scaffold The Qt Application And Render Panel Contents

**Files:**
- Create: `desktop_tidy/application.py`
- Create: `desktop_tidy/ui/__init__.py`
- Create: `desktop_tidy/ui/panel_group.py`
- Create: `desktop_tidy/ui/item_grid.py`
- Create: `desktop_tidy/services/item_visuals.py`
- Create: `qt_main.py`
- Create: `tests/test_qt_item_grid.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Replace runtime dependencies for the new UI and write offscreen widget tests**

Add Qt while retaining legacy optional packages until the final cutover milestone:

```text
PySide6>=6.8,<7
pystray>=0.19,<1
Pillow>=10,<12
windnd>=1.0,<2
```

Write an offscreen test that initializes one `QApplication`, renders a group with items, and checks that labels elide and that the panel opacity is painted on its background rather than applied as whole-window opacity:

```python
# tests/test_qt_item_grid.py
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.ui.panel_group import PanelGroupWidget


class ItemGridWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_group_uses_background_alpha_without_fading_children(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        widget = PanelGroupWidget(config.panel_groups[0], config.panel_tabs)
        self.assertEqual(widget.windowOpacity(), 1.0)
        self.assertEqual(widget.background_opacity, 0.60)

    def test_item_caption_is_limited_to_two_elided_lines(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        widget = PanelGroupWidget(config.panel_groups[0], config.panel_tabs)
        caption = widget.item_grid.caption_text("一个特别特别特别长的桌面文档文件名称.pdf", width=80)
        self.assertLessEqual(len(caption.splitlines()), 2)
        self.assertTrue(caption.endswith("..."))
```

- [ ] **Step 2: Install dependencies and verify the tests fail for missing UI types**

Run: `python -m pip install -r requirements.txt`  
Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_qt_item_grid -v`  
Expected: PySide6 installs successfully, then tests fail because `PanelGroupWidget` does not yet exist.

- [ ] **Step 3: Implement Qt preview window, translucent panel painting and item visuals**

Implement `PanelGroupWidget(QWidget)` with `Qt.FramelessWindowHint | Qt.Tool`, `WA_TranslucentBackground`, and a `paintEvent()` that fills only the rounded panel background with `QColor(color)` plus `setAlphaF(background_opacity)`. Do not call `setWindowOpacity()` for the panel. Implement:

```python
class ItemVisualProvider:
    def __init__(self) -> None:
        self.icons = QFileIconProvider()

    def icon_for(self, path: Path) -> QIcon:
        if path.suffix.casefold() in IMAGE_EXTENSIONS:
            pixmap = QPixmap(str(path)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if not pixmap.isNull():
                return QIcon(pixmap)
        return self.icons.icon(QFileInfo(str(path)))
```

`ItemGridWidget` uses a `QGridLayout`, `QToolButton`/label cells sized consistently, a two-line text elision helper backed by `QFontMetrics.elidedText(text, Qt.ElideRight, width)`, and double-click/open signals only; no file mutation APIs.

`qt_main.py` loads a default model and shows one preview group without desktop takeover, providing the M2 preview path before shell integration exists.

- [ ] **Step 4: Run widget tests and manually open the Qt preview**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_qt_item_grid -v`  
Expected: widget tests pass.

Run on Windows interactively: `python qt_main.py`  
Expected: one unlocked black translucent panel appears with opaque header/content; closing it exits normally and does not alter Explorer desktop icons.

- [ ] **Step 5: Commit the first Qt-rendered panel**

```powershell
git add requirements.txt desktop_tidy/application.py desktop_tidy/ui desktop_tidy/services/item_visuals.py qt_main.py tests/test_qt_item_grid.py
git commit -m "feat: render pyqt desktop panel preview"
```

### Task 6: Add Tabs, Rename, Add/Delete And Group Commands

**Files:**
- Modify: `desktop_tidy/domain/workspace.py`
- Modify: `desktop_tidy/ui/panel_group.py`
- Create: `tests/test_qt_panel_group.py`
- Modify: `tests/test_workspace.py`

- [ ] **Step 1: Write failing model and widget tests for group/tab actions**

```python
def test_delete_last_group_recreates_default_group(self) -> None:
    model = WorkspaceModel(build_default_configuration(r"E:\system\桌面"))
    only_tab = model.config.panel_tabs[0].id
    model.delete_tab(only_tab)
    self.assertEqual(len(model.config.panel_groups), 1)
    self.assertGreaterEqual(len(model.config.panel_tabs), 1)

def test_add_tab_joins_current_group_and_requests_inline_rename(self) -> None:
    model = WorkspaceModel(build_default_configuration(r"E:\system\桌面"))
    new_tab = model.add_tab("group-default")
    self.assertEqual(new_tab.group_id, "group-default")
    self.assertEqual(model.config.panel_groups[0].active_tab_id, new_tab.id)
```

```python
# tests/test_qt_panel_group.py
def make_group_widget() -> PanelGroupWidget:
    config = build_default_configuration(r"E:\system\桌面")
    return PanelGroupWidget(config.panel_groups[0], config.panel_tabs)


def test_clicking_tab_switches_active_content(self) -> None:
    widget = make_group_widget()
    widget.activate_tab("tab-images")
    self.assertEqual(widget.active_tab_id, "tab-images")

def test_toolbar_contains_add_delete_and_more_actions(self) -> None:
    widget = make_group_widget()
    self.assertIsNotNone(widget.add_button)
    self.assertIsNotNone(widget.delete_button)
    self.assertIsNotNone(widget.more_button)
```

- [ ] **Step 2: Run only the new interaction tests and confirm failures**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_workspace tests.test_qt_panel_group -v`  
Expected: failures for missing `add_tab`, `delete_tab`, and toolbar behavior.

- [ ] **Step 3: Implement command-first tab management and bind header widgets**

`WorkspaceModel` owns all mutations:

```python
def add_tab(self, group_id: str, name: str = "新建面板") -> PanelTab:
    group = self.group(group_id)
    tab = PanelTab(id=f"tab-{uuid.uuid4().hex}", group_id=group_id, name=name, order=len(group.tab_ids))
    self.config.panel_tabs.append(tab)
    group.tab_ids.append(tab.id)
    group.active_tab_id = tab.id
    return tab

def rename_tab(self, tab_id: str, name: str) -> None:
    value = name.strip() or "未命名面板"
    self.tab(tab_id).name = value

def delete_tab(self, tab_id: str) -> None:
    tab = self.tab(tab_id)
    group = self.group(tab.group_id)
    self.config.manual_overrides = [
        override for override in self.config.manual_overrides if override.target_tab_id != tab_id
    ]
    self.config.external_refs = [
        item for item in self.config.external_refs if item.target_tab_id != tab_id
    ]
    group.tab_ids = [candidate for candidate in group.tab_ids if candidate != tab_id]
    self.config.panel_tabs = [candidate for candidate in self.config.panel_tabs if candidate.id != tab_id]
    fallback_id = "tab-other" if any(candidate.id == "tab-other" for candidate in self.config.panel_tabs) else ""
    for rule in self.config.rules:
        if rule.target_tab_id == tab_id:
            rule.target_tab_id = fallback_id
            rule.enabled = bool(fallback_id)
    if group.tab_ids:
        group.active_tab_id = group.tab_ids[0]
        return
    self.config.panel_groups = [candidate for candidate in self.config.panel_groups if candidate.id != group.id]
    if not self.config.panel_groups:
        clean = build_default_configuration(self.config.desktop.path)
        self.config.panel_groups = clean.panel_groups
        self.config.panel_tabs = clean.panel_tabs
        self.config.rules = clean.rules
```

Bind Qt header controls as required: inline `QLineEdit` editing for title, `+` creates and edits a tab, trash requests confirmation only when deleting a whole group, and `...` holds appearance/settings actions.

- [ ] **Step 4: Run domain and Qt action tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_workspace tests.test_qt_panel_group -v`  
Expected: tests pass and deletion never invokes filesystem writes.

- [ ] **Step 5: Commit tab actions**

```powershell
git add desktop_tidy/domain/workspace.py desktop_tidy/ui/panel_group.py tests/test_workspace.py tests/test_qt_panel_group.py
git commit -m "feat: manage panel tabs through qt header actions"
```

### Task 7: Implement Drop-In Items, Manual Overrides And Settings Center

**Files:**
- Modify: `desktop_tidy/ui/item_grid.py`
- Create: `desktop_tidy/ui/settings_window.py`
- Modify: `desktop_tidy/application.py`
- Create: `tests/test_qt_settings.py`
- Modify: `tests/test_qt_item_grid.py`

- [ ] **Step 1: Write failing tests for Qt drops and settings surface**

```python
def make_item_grid() -> ItemGridWidget:
    config = build_default_configuration(r"E:\system\桌面")
    return ItemGridWidget(active_tab_id="tab-images")


def test_local_file_urls_are_emitted_for_any_suffix(self) -> None:
    widget = make_item_grid()
    paths = widget.local_paths_from_urls([QUrl.fromLocalFile(r"D:\draft\asset.weird")])
    self.assertEqual(paths, [Path(r"D:\draft\asset.weird")])

def test_settings_has_supported_sections_only(self) -> None:
    window = SettingsWindow(build_default_configuration(r"E:\system\桌面"))
    text = window.visible_section_names()
    self.assertEqual(text, ["基础设置", "桌面分区", "桌面整理", "面板外观"])
    self.assertNotIn("壁纸", window.all_text())
    self.assertNotIn("归档", window.all_text())
```

- [ ] **Step 2: Run UI tests to verify missing drop/settings behavior**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_qt_item_grid tests.test_qt_settings -v`  
Expected: tests fail until drag/drop helpers and `SettingsWindow` exist.

- [ ] **Step 3: Implement Qt-native drag/drop and supported settings**

Set `ItemGridWidget.setAcceptDrops(True)`. `dragEnterEvent()` accepts `mimeData().hasUrls()`, and `dropEvent()` emits local paths to `WorkspaceModel.add_paths_to_tab()`. It must accept folders and all suffixes, with no `windnd` hooks:

```python
def local_paths_from_urls(self, urls: list[QUrl]) -> list[Path]:
    return [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]

def dropEvent(self, event: QDropEvent) -> None:
    paths = self.local_paths_from_urls(event.mimeData().urls())
    if paths:
        self.paths_dropped.emit(paths, self.active_tab_id)
        event.acceptProposedAction()
```

`SettingsWindow` exposes:

- Desktop path `QLineEdit` and folder picker.
- Desktop takeover and startup checkboxes.
- Rules table with enable toggles, editable extension list and target tab selector.
- Color chooser and opacity slider mapped to `0.18` through `0.95`, initialized at `0.60`.

Saving settings updates `WorkspaceModel` and `ConfigurationStore`; it must not expose archive, wallpaper, search, AI or synchronization controls.

- [ ] **Step 4: Run widget tests and interactive add-item preview**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_qt_item_grid tests.test_qt_settings tests.test_workspace -v`  
Expected: tests pass.

Manual preview: start `python qt_main.py`, drag an unusual-format file and a folder from a non-desktop path into a tab, close/restart the preview, and confirm entries persist while the source paths and configured desktop directory contain no new files.

- [ ] **Step 5: Commit reference drops and settings**

```powershell
git add desktop_tidy/ui desktop_tidy/application.py tests/test_qt_item_grid.py tests/test_qt_settings.py
git commit -m "feat: add virtual reference drops and qt settings"
```

### Task 8: Add Panel Movement, Resize, Collapse, Lock, Detach And Merge

**Files:**
- Modify: `desktop_tidy/domain/workspace.py`
- Modify: `desktop_tidy/ui/panel_group.py`
- Modify: `tests/test_workspace.py`
- Modify: `tests/test_qt_panel_group.py`

- [ ] **Step 1: Write failing pure command tests for layout behavior**

```python
def test_drop_group_over_target_merges_using_pointer_position(self) -> None:
    model = WorkspaceModel(build_default_configuration(r"E:\system\桌面"))
    second = model.detach_tab("tab-images", PanelGeometry(0.6, 0.2, 0.3, 0.4))
    model.merge_group_at_point(second.id, QPoint(180, 160), bounds={"group-default": QRect(100, 100, 400, 300)})
    self.assertEqual(model.tab("tab-images").group_id, "group-default")

def test_drag_tab_outside_group_detaches_without_moving_content_files(self) -> None:
    model = WorkspaceModel(build_default_configuration(r"E:\system\桌面"))
    detached = model.detach_tab("tab-images", PanelGeometry(0.5, 0.2, 0.3, 0.4))
    self.assertEqual(model.tab("tab-images").group_id, detached.id)
    self.assertEqual(detached.appearance.background_opacity, 0.60)
```

Add widget tests for `locked` blocking resize/move, `collapsed` hiding the tab/content section without adding a trailing bar, and hit testing horizontal edges, vertical edges and corners.

- [ ] **Step 2: Run tests and see missing gesture commands**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_workspace tests.test_qt_panel_group -v`  
Expected: failures for missing layout commands and resize hit testing.

- [ ] **Step 3: Implement persisted layout commands and Qt pointer gestures**

Keep business decisions in `WorkspaceModel` and pointer feedback in the widget:

```python
class ResizeRegion(Enum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


def merge_group_at_point(self, dragged_group_id: str, point: QPoint, bounds: dict[str, QRect]) -> bool:
    target_id = next((group_id for group_id, rect in bounds.items() if group_id != dragged_group_id and rect.contains(point)), None)
    if not target_id:
        return False
    dragged = self.group(dragged_group_id)
    target = self.group(target_id)
    for tab_id in dragged.tab_ids:
        self.tab(tab_id).group_id = target_id
        target.tab_ids.append(tab_id)
    target.active_tab_id = dragged.active_tab_id
    self.config.panel_groups = [group for group in self.config.panel_groups if group.id != dragged_group_id]
    return True

def detach_tab(self, tab_id: str, geometry: PanelGeometry) -> PanelGroup:
    tab = self.tab(tab_id)
    original = self.group(tab.group_id)
    original.tab_ids = [candidate for candidate in original.tab_ids if candidate != tab_id]
    if original.active_tab_id == tab_id and original.tab_ids:
        original.active_tab_id = original.tab_ids[0]
    group = PanelGroup(
        id=f"group-{uuid.uuid4().hex}",
        screen_id=self.config.desktop.primary_screen_id,
        geometry=geometry,
        tab_ids=[tab_id],
        active_tab_id=tab_id,
        appearance=copy.deepcopy(self.config.appearance_defaults),
    )
    tab.group_id = group.id
    self.config.panel_groups.append(group)
    if not original.tab_ids:
        self.config.panel_groups = [candidate for candidate in self.config.panel_groups if candidate.id != original.id]
    return group
```

Implement:

- Header drag moves only when unlocked, snaps to desktop/group edges and saves geometry on release.
- Each panel edge changes its corresponding dimension; corners change both.
- Collapse preserves the header geometry and z-order and removes all extra content height.
- Tab drag displays a preview; release outside creates a new group and removes the tab from its old group.
- Group drop merges only if release pointer is within the target group's visible rectangle.
- Merged tabs inherit the destination group's single appearance; newly detached groups use the configured default group appearance.

- [ ] **Step 4: Run all M2 UI and core tests and conduct interaction preview**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: all new Qt/core tests pass; old tests may still run only until the cutover task replaces them.

Manual preview: verify moving, edge resizing, locking, collapsing, tab switching, inline naming, tab detach preview and pointer-based merge in `qt_main.py`.

- [ ] **Step 5: Commit interactive panel grouping**

```powershell
git add desktop_tidy/domain/workspace.py desktop_tidy/ui/panel_group.py tests/test_workspace.py tests/test_qt_panel_group.py
git commit -m "feat: implement qt panel layout and grouping interactions"
```

### Task 9: Implement Failure-Safe Windows Desktop Takeover

**Files:**
- Create: `desktop_tidy/services/windows_shell.py`
- Create: `desktop_tidy/services/takeover.py`
- Create: `tests/test_takeover.py`
- Modify: `desktop_tidy/application.py`

- [ ] **Step 1: Write controller tests with a fake shell adapter**

```python
# tests/test_takeover.py
import unittest

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.services.takeover import DesktopTakeoverController


class FakeShell:
    def __init__(self, attach_ok=True, hide_ok=True):
        self.attach_ok = attach_ok
        self.hide_ok = hide_ok
        self.calls = []

    def attach_panel(self, hwnd: int) -> bool:
        self.calls.append("attach")
        return self.attach_ok

    def hide_explorer_icons(self) -> bool:
        self.calls.append("hide")
        return self.hide_ok

    def show_explorer_icons(self) -> bool:
        self.calls.append("show")
        return True


class TakeoverTests(unittest.TestCase):
    def test_attach_failure_never_hides_explorer_icons(self) -> None:
        state = build_default_configuration(r"E:\system\桌面")
        shell = FakeShell(attach_ok=False)
        controller = DesktopTakeoverController(state, shell, lambda: None)
        self.assertFalse(controller.enable(123))
        self.assertEqual(shell.calls, ["attach"])

    def test_restore_marker_is_saved_before_icons_are_hidden(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        events = []
        shell = FakeShell()
        controller = DesktopTakeoverController(config, shell, lambda: events.append(config.desktop.restore_required))
        self.assertTrue(controller.enable(123))
        self.assertTrue(events[0])
        self.assertEqual(shell.calls, ["attach", "hide"])

    def test_startup_recovers_stale_hidden_state_first(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        config.desktop.restore_required = True
        shell = FakeShell()
        DesktopTakeoverController(config, shell, lambda: None).recover_if_required()
        self.assertEqual(shell.calls, ["show"])
        self.assertFalse(config.desktop.restore_required)
```

- [ ] **Step 2: Run controller tests and establish failure**

Run: `python -m unittest tests.test_takeover -v`  
Expected: missing takeover module failures.

- [ ] **Step 3: Implement controller and isolated Win32 adapter**

`DesktopTakeoverController` must first recover stale state at application startup. On enable it must attach a Qt panel window to the desktop layer, set and save `restore_required = True`, then call `hide_explorer_icons()`. On any hide failure it restores icons and clears the flag. Attachment failure returns without ever setting the flag or hiding icons:

```python
class DesktopTakeoverController:
    def __init__(self, config: Configuration, shell: WindowsShellAdapter, save: Callable[[], None]) -> None:
        self.config = config
        self.shell = shell
        self.save = save

    def recover_if_required(self) -> None:
        if self.config.desktop.restore_required or self.config.desktop.explorer_icons_hidden:
            if self.shell.show_explorer_icons():
                self.config.desktop.restore_required = False
                self.config.desktop.explorer_icons_hidden = False
                self.save()

    def enable(self, hwnd: int) -> bool:
        if not self.shell.attach_panel(hwnd):
            return False
        self.config.desktop.restore_required = True
        self.save()
        if not self.shell.hide_explorer_icons():
            self.shell.show_explorer_icons()
            self.config.desktop.restore_required = False
            self.config.desktop.explorer_icons_hidden = False
            self.save()
            return False
        self.config.desktop.explorer_icons_hidden = True
        self.save()
        return True

    def disable(self) -> bool:
        restored = self.shell.show_explorer_icons()
        if restored:
            self.config.desktop.restore_required = False
            self.config.desktop.explorer_icons_hidden = False
            self.save()
        return restored
```

Implement `WindowsShellAdapter` in one file only, using `ctypes` to:

- Trigger creation/discovery of the WorkerW/Progman desktop host.
- Set the panel HWND parent to the discovered desktop host.
- Locate the Explorer desktop icon `SysListView32` view beneath `SHELLDLL_DefView`.
- Show/hide only that icon view through `ShowWindow`.
- Return booleans and never swallow failure into a false success.

The adapter must expose `attach_panel(hwnd: int) -> bool`, `hide_explorer_icons() -> bool`, and `show_explorer_icons() -> bool`, matching the fake adapter in `tests/test_takeover.py`.

Do not copy reference software implementation or assets; implement against documented Windows window discovery behavior and validate on the development machine.

- [ ] **Step 4: Run controller tests and execute the mandatory recovery smoke check**

Run: `python -m unittest tests.test_takeover -v`  
Expected: all tests pass.

Manual Windows check with a disposable Qt preview setting:

1. Enable takeover and confirm the panel appears behind normal application windows.
2. Confirm Explorer icons hide only after the panel is visible.
3. Disable takeover and confirm icons return.
4. Force-close the process after icons hide, relaunch it, and confirm startup restores icons before trying takeover again.
5. Force attachment failure using a fake/dev flag and confirm icons never hide.

Do not proceed to make takeover default-enabled until all five checks pass.

- [ ] **Step 5: Commit shell integration**

```powershell
git add desktop_tidy/services/windows_shell.py desktop_tidy/services/takeover.py desktop_tidy/application.py tests/test_takeover.py
git commit -m "feat: add recoverable windows desktop takeover"
```

### Task 10: Wire Live Application Lifecycle, Tray And Startup

**Files:**
- Create: `desktop_tidy/ui/tray.py`
- Modify: `desktop_tidy/application.py`
- Modify: `desktop_tidy/services/windows_shell.py`
- Create: `tests/test_qt_settings.py`

- [ ] **Step 1: Add lifecycle tests for settings saves and quit restoration**

```python
class FakeTakeoverController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def disable(self) -> bool:
        self.calls.append("disable")
        return True


class FakeStore:
    def save(self, _config) -> None:
        return None


class FakeWatcher:
    def __init__(self) -> None:
        self.path = None

    def set_path(self, path: Path) -> None:
        self.path = path


def make_lifecycle() -> ApplicationLifecycle:
    return ApplicationLifecycle(
        model=WorkspaceModel(build_default_configuration(r"C:\Users\me\Desktop")),
        controller=FakeTakeoverController(),
        store=FakeStore(),
        watcher=FakeWatcher(),
    )


def test_quit_requests_icon_restore_before_application_exit(self) -> None:
    controller = FakeTakeoverController()
    lifecycle = ApplicationLifecycle(controller=controller, store=FakeStore())
    lifecycle.quit()
    self.assertEqual(controller.calls, ["disable"])

def test_desktop_path_change_rebuilds_watcher_without_creating_entries(self) -> None:
    lifecycle = make_lifecycle()
    lifecycle.set_desktop_path(r"E:\system\桌面")
    self.assertEqual(lifecycle.watcher.path, Path(r"E:\system\桌面"))
    self.assertEqual(lifecycle.model.config.external_refs, [])
```

- [ ] **Step 2: Verify lifecycle tests fail**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest tests.test_qt_settings -v`  
Expected: lifecycle API assertions fail until wired.

- [ ] **Step 3: Implement application wiring and Qt tray controls**

`ApplicationLifecycle` accepts `model`, `controller`, `store` and `watcher` dependencies as shown by the tests, and constructs the production instances from `ConfigurationStore.default()` inside `run()`. It owns settings and group widgets, saves after model mutations, calls `watcher.set_path(Path(value))` when the desktop path changes, and calls `takeover.disable()` on every controlled quit path.

`TrayController(QSystemTrayIcon)` menu contains only:

- 显示设置中心
- 启用/停用桌面面板
- 开机启动
- 退出

Use a startup shortcut implementation moved into `WindowsShellAdapter` or a focused companion in the same services package. It must start `qt_main.py` during development and the frozen executable after packaging.

- [ ] **Step 4: Run UI/controller tests and a normal quit smoke test**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: new tests pass.

Manual check: enable takeover, quit through the tray item, and confirm Explorer icons restore before the process exits.

- [ ] **Step 5: Commit application lifecycle**

```powershell
git add desktop_tidy/application.py desktop_tidy/ui/tray.py desktop_tidy/services/windows_shell.py tests/test_qt_settings.py
git commit -m "feat: wire qt lifecycle tray and startup controls"
```

### Task 11: Cut Over From Tkinter And Remove Obsolete File-Moving Surface

**Files:**
- Modify: `main.py`
- Modify: `requirements.txt`
- Delete: `config.default.json`
- Delete: `organizer.py`
- Delete: `partition_overlay.py`
- Delete: `tray_support.py`
- Delete: `tests/test_organizer.py`
- Delete: `tests/test_partition_overlay.py`
- Delete: `tests/test_collect_rules.py`
- Modify: `README.md`
- Modify: `docs/需求说明.md`

- [ ] **Step 1: Add an import/entrypoint regression test**

Create `tests/test_entrypoint.py`:

```python
import inspect
import unittest

import main


class EntrypointTests(unittest.TestCase):
    def test_shipping_entrypoint_uses_qt_application_only(self) -> None:
        source = inspect.getsource(main)
        self.assertIn("desktop_tidy.application", source)
        self.assertNotIn("tkinter", source)
        self.assertNotIn("organizer", source)
```

- [ ] **Step 2: Verify the current Tk entrypoint fails the cutover assertion**

Run: `python -m unittest tests.test_entrypoint -v`  
Expected: failure because current `main.py` imports `tkinter` and `organizer`.

- [ ] **Step 3: Switch the executable entrypoint and remove non-product runtime modules**

Make `main.py` a thin entrypoint:

```python
from desktop_tidy.application import run


if __name__ == "__main__":
    raise SystemExit(run())
```

Delete old Tk overlay, tray, and archive modules and their old tests once no code imports them. Update README and `docs/需求说明.md` to refer to the approved design document and describe only the Qt v1 scope:

- Entry classification only; no source file movement/undo/archive root.
- External files are virtual references only.
- Desktop takeover restoration warning and recovery behavior.
- Settings center and final packaging command.

At this cutover, reduce `requirements.txt` to the Qt runtime dependency:

```text
PySide6>=6.8,<7
```

- [ ] **Step 4: Run the complete replacement test suite**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: all remaining tests pass with no imports from deleted Tk/file-moving modules.

- [ ] **Step 5: Commit cutover**

```powershell
git add main.py requirements.txt README.md docs desktop_tidy tests
git rm config.default.json organizer.py partition_overlay.py tray_support.py tests/test_organizer.py tests/test_partition_overlay.py tests/test_collect_rules.py
git commit -m "refactor: replace tkinter app with qt desktop manager"
```

### Task 12: Package The Qt Application And Record Windows Acceptance

**Files:**
- Modify: `requirements-build.txt`
- Modify: `DesktopTidy.spec`
- Modify: `scripts/build_exe.bat`
- Create: `docs/verification/qt-v1-windows-smoke-checklist.md`
- Modify: `README.md`

- [ ] **Step 1: Write the manual acceptance checklist before packaging**

`docs/verification/qt-v1-windows-smoke-checklist.md` must record checkboxes and a results table for:

```markdown
# Qt v1 Windows Smoke Checklist

- [ ] First start builds one six-tab group and classifies the configured desktop.
- [ ] Any-format external drop creates only a persistent virtual reference.
- [ ] Manual reclassification survives restart and can return to automatic classification.
- [ ] Tab rename/add/delete/detach/merge works; one default group remains.
- [ ] Header move, edge resize, lock and collapse persist after restart.
- [ ] Black `alpha = 0.60` background keeps icons and captions opaque; long captions elide to two lines.
- [ ] Enabling takeover hides Explorer icons only after panel attachment.
- [ ] Disable, tray quit and abnormal-restart recovery restore Explorer icons.
- [ ] The packaged one-file executable starts without a console window.
```

- [ ] **Step 2: Update PyInstaller dependencies and specification**

`requirements-build.txt` becomes:

```text
-r requirements.txt
pyinstaller>=6.0,<8
```

`DesktopTidy.spec` must analyze `main.py`, include `desktop_tidy/resources/default_config.json`, and collect PySide6 Qt plugins. Remove hidden imports and asset collection for `windnd`, `pystray` and `PIL`, because the shipping runtime no longer uses those packages. Use an `EXE`-only spec: omitting a `COLLECT` stage makes this the one-file build equivalent of `--onefile`, while `console=False` supplies the no-console behavior equivalent of `--windowed`.

```python
# DesktopTidy.spec
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all("PySide6")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=pyside_binaries,
    datas=[("desktop_tidy/resources/default_config.json", "desktop_tidy/resources")] + pyside_datas,
    hiddenimports=pyside_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "windnd", "pystray", "PIL"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DesktopTidy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
```

Update `scripts/build_exe.bat` to run the spec:

```bat
@echo off
setlocal
cd /d "%~dp0.."
python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean DesktopTidy.spec
if errorlevel 1 exit /b 1
echo Completed: dist\DesktopTidy.exe
endlocal
```

- [ ] **Step 3: Run automated verification before packaging**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m unittest discover -s tests -p 'test_*.py' -v`  
Expected: all tests pass.

- [ ] **Step 4: Build and manually verify the executable**

Run: `scripts\build_exe.bat`  
Expected: command exits `0` and produces `dist\DesktopTidy.exe`.

Run: `dist\DesktopTidy.exe`  
Expected: no console window is shown. Complete every checkbox in `docs/verification/qt-v1-windows-smoke-checklist.md`, recording Windows version, executable build date and observations. If icon restoration fails once, do not distribute the executable.

- [ ] **Step 5: Commit release preparation**

```powershell
git add requirements-build.txt DesktopTidy.spec scripts/build_exe.bat docs/verification/qt-v1-windows-smoke-checklist.md README.md
git commit -m "build: package qt desktop manager as windows exe"
```

## Final Verification Before Distribution

Run these commands from the repository root after all tasks:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s tests -p 'test_*.py' -v
scripts\build_exe.bat
git status --short
```

Expected results:

- The complete remaining test suite reports `OK`.
- PyInstaller produces `dist\DesktopTidy.exe` without build errors.
- `git status --short` contains no uncommitted source or documentation changes intended for release.
- The Windows smoke checklist contains completed results for desktop attachment, icon hide/restore, crash recovery and no-console executable launch.
