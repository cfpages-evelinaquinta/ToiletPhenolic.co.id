import tempfile
import unittest
from pathlib import Path

import normalize_cubicle


class NormalizeCubicleTests(unittest.TestCase):
    def test_flatten_and_redirects_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cubicle-bekasi"
            source.mkdir()
            (source / "index.html").write_bytes(b"hello")
            (root / "_redirects").write_text("/*_1 /:splat 301\n", encoding="utf-8")
            changed, summary = normalize_cubicle.flatten(root)
            self.assertEqual(summary["moved"], 1)
            self.assertIn("cubicle-bekasi.html", changed)
            self.assertFalse(source.exists())
            redirects = (root / "_redirects").read_text().splitlines()
            self.assertEqual(redirects[0], "/cubicle-bekasi/ /cubicle-bekasi.html 301")
            self.assertIn("/cubicle-bekasi/index.html /cubicle-bekasi.html 301", redirects)
            changed, summary = normalize_cubicle.flatten(root)
            self.assertEqual(summary["moved"], 0)
            self.assertEqual(changed, [])

    def test_existing_flat_page_gets_legacy_redirects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cubicle-depok.html").write_bytes(b"page")
            changed, _ = normalize_cubicle.flatten(root)
            self.assertEqual(changed, ["_redirects"])
            self.assertIn("/cubicle-depok/index.html /cubicle-depok.html 301", (root / "_redirects").read_text())

    def test_existing_different_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cubicle-bekasi"
            source.mkdir()
            (source / "index.html").write_bytes(b"source")
            (root / "cubicle-bekasi.html").write_bytes(b"different")
            with self.assertRaises(normalize_cubicle.TransformError):
                normalize_cubicle.flatten(root)

    def test_extra_source_files_are_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cubicle-bekasi"
            source.mkdir()
            (source / "index.html").write_bytes(b"source")
            (source / "asset.css").write_bytes(b"css")
            with self.assertRaises(normalize_cubicle.TransformError):
                normalize_cubicle.flatten(root)
            self.assertFalse((root / "cubicle-bekasi.html").exists())

    def test_css_normalization_checks_the_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / "wp-content/cache/min/1/site.css"
            asset.parent.mkdir(parents=True)
            asset.write_text("body{}", encoding="utf-8")
            page = root / "cubicle-bekasi.html"
            page.write_text(
                '<link rel="icon" href="../wp-content/uploads/icon.png">'
                '<link rel="stylesheet" href="../wp-content/cache/min/1/site.css">',
                encoding="utf-8",
            )
            changed, summary = normalize_cubicle.normalize_css(root)
            self.assertEqual(summary["normalized"], 1)
            self.assertEqual(changed, [page.name])
            self.assertIn('href="wp-content/cache/min/1/site.css"', page.read_text())
            self.assertIn('href="../wp-content/uploads/icon.png"', page.read_text())
            changed, summary = normalize_cubicle.normalize_css(root)
            self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
