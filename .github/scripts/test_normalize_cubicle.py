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
            (root / "_redirects").write_bytes(b"/*_1 /:splat 301\r\n")
            changed, summary = normalize_cubicle.flatten(root)
            self.assertEqual(summary["moved"], 1)
            self.assertIn("cubicle-bekasi.html", changed)
            self.assertFalse(source.exists())
            redirects = (root / "_redirects").read_text().splitlines()
            self.assertEqual(redirects[0], "/cubicle-bekasi/ /cubicle-bekasi.html 301")
            self.assertIn("/cubicle-bekasi/index.html /cubicle-bekasi.html 301", redirects)
            self.assertNotIn(b"\n", (root / "_redirects").read_bytes().replace(b"\r\n", b""))
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

    def test_flatten_rewrites_only_known_cubicle_href_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cubicle-bogor.html").write_text("destination", encoding="utf-8")
            page = root / "blog" / "page" / "5" / "index.html"
            page.parent.mkdir(parents=True)
            original = (
                "\ufeff<p>keep <a href=\"/other\">x</a></p>"
                "<a href=\"../../../cubicle-bogor/index.html?x=1#top\">relative</a>"
                "<a href=\"../../../cubicle-bogor/?x=2#top\">trailing</a>"
                "<a href=\"/cubicle-bogor/index.html\">root</a>"
                "<a href=\"https://toiletphenolic.co.id/cubicle-bogor/index.html#abs\">absolute</a>"
                "<a href=\"https://bobrick.com/cubicle-bogor/index.html\">external</a>"
                "<a href=\"//bobrick.com/cubicle-bogor/index.html\">external-protocol-relative</a>"
                "<a href=\"/cubicle-missing/index.html\">missing</a>"
                "<a href=\"/cubicle-bogor.html\">already-flat</a>"
            )
            page.write_text(original, encoding="utf-8-sig")

            changed, summary = normalize_cubicle.flatten(root)

            self.assertEqual(summary["rewritten"], 4)
            self.assertIn("blog/page/5/index.html", changed)
            result = page.read_text(encoding="utf-8-sig")
            self.assertIn('href="../../../cubicle-bogor.html?x=1#top"', result)
            self.assertIn('href="../../../cubicle-bogor.html?x=2#top"', result)
            self.assertIn('href="/cubicle-bogor.html"', result)
            self.assertIn('href="https://toiletphenolic.co.id/cubicle-bogor.html#abs"', result)
            self.assertIn('href="https://bobrick.com/cubicle-bogor/index.html"', result)
            self.assertIn('href="//bobrick.com/cubicle-bogor/index.html"', result)
            self.assertIn('href="/cubicle-missing/index.html"', result)
            self.assertTrue(page.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_flatten_link_rewrite_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cubicle-bogor.html").write_text("destination", encoding="utf-8")
            page = root / "index.html"
            page.write_text('<a href="/cubicle-bogor/">x</a>', encoding="utf-8")
            normalize_cubicle.flatten(root)
            first = page.read_bytes()
            changed, summary = normalize_cubicle.flatten(root)
            self.assertEqual(changed, [])
            self.assertEqual(summary["rewritten"], 0)
            self.assertEqual(page.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
