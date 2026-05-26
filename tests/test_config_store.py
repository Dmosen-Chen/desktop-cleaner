from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import InvalidConfiguration, ItemRef
from desktop_tidy.persistence.config_store import ConfigurationStore


class ConfigurationStoreTests(unittest.TestCase):
    def test_default_path_is_under_local_app_data(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            self.assertEqual(
                ConfigurationStore.default().path,
                Path(tmp) / "DesktopTidy" / "config.json",
            )

    def test_save_replaces_temporary_json_atomically(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings" / "config.json"
            config = build_default_configuration(r"D:\Desktop")
            store = ConfigurationStore(path)

            with patch("desktop_tidy.persistence.config_store.os.replace", wraps=os.replace) as replace:
                store.save(config)

            replace.assert_called_once_with(path.with_suffix(".tmp"), path)
            self.assertFalse(path.with_suffix(".tmp").exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), config.to_dict())

    def test_save_rejects_relative_external_ref_canonical_path(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            invalid = build_default_configuration(r"D:\Desktop")
            invalid.external_refs.append(
                ItemRef("external-relative", "external", "notes.txt", "tab-other")
            )
            store = ConfigurationStore(path)

            with self.assertRaisesRegex(
                InvalidConfiguration,
                "external reference external-relative must use an absolute path",
            ):
                store.save(invalid)

            self.assertFalse(path.exists())

    def test_save_rejects_invalid_configuration_without_modifying_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            valid = build_default_configuration(r"D:\Desktop")
            path.write_text(json.dumps(valid.to_dict(), ensure_ascii=False), encoding="utf-8")
            original = path.read_text(encoding="utf-8")
            invalid = build_default_configuration(r"D:\Desktop")
            invalid.panel_groups[0].active_tab_id = "tab-missing"
            store = ConfigurationStore(path)

            with self.assertRaises(InvalidConfiguration):
                store.save(invalid)

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_load_reads_schema_v2_without_creating_migration_backup(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            expected = build_default_configuration(r"D:\Desktop")
            path.write_text(json.dumps(expected.to_dict(), ensure_ascii=False), encoding="utf-8")

            actual = ConfigurationStore(path).load()

            self.assertEqual(actual, expected)
            self.assertEqual(list(Path(tmp).glob("config.pre-qt-v1-*.json")), [])


if __name__ == "__main__":
    unittest.main()
