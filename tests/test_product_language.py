import unittest

from gui.product_language import product_text


class ProductLanguageTests(unittest.TestCase):
    def test_engine_terms_are_packizard_owned(self):
        samples = (
            "LZ4 compression",
            "Skip LZ4 integrity check",
            "The compressed AMPR output becomes the package source.",
            "Packizard · AMPR + LibProsperoPKG",
            "TOML profiles folder",
        )
        for sample in samples:
            visible = product_text(sample)
            self.assertNotIn("LZ4", visible)
            self.assertNotIn("AMPR", visible)

    def test_sidebar_identity(self):
        self.assertEqual(
            product_text("Packizard · AMPR + LibProsperoPKG"),
            "Packizard Engine · Compression + PKG",
        )


if __name__ == "__main__":
    unittest.main()
