from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.classification import canonical_key, classify_path
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import ManualOverride


class ClassificationTests(unittest.TestCase):
    def test_default_rules_classify_folder_known_extensions_and_other(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "album"
            folder.mkdir()
            config = build_default_configuration(root)

            cases = [
                (folder, "tab-folders"),
                (root / "report.PDF", "tab-documents"),
                (root / "cover.JpG", "tab-images"),
                (root / "source.7Z", "tab-archives"),
                (root / "Launch.LNK", "tab-apps"),
                (root / "unknown.custom", "tab-other"),
            ]
            for path, expected in cases:
                with self.subTest(path=path.name):
                    self.assertEqual(classify_path(path, config), expected)

    def test_canonical_key_resolves_paths_and_casefolds(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "child" / ".." / "Report.PDF"
            self.assertEqual(canonical_key(path), str(path.resolve()).casefold())

    def test_manual_override_has_priority_over_matching_rule(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cover.png"
            config = build_default_configuration(tmp)
            config.manual_overrides.append(ManualOverride(canonical_key(path), "tab-documents"))

            self.assertEqual(classify_path(path, config), "tab-documents")


if __name__ == "__main__":
    unittest.main()
