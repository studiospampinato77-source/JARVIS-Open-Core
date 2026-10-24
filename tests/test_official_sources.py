import os
import unittest

import _paths  # noqa: F401
import jarvis_official_sources_v1 as src


class OfficialSourcesTest(unittest.TestCase):
    def test_html_to_text(self):
        self.assertEqual(src._testo("<p>Art. 1 <b>uno</b></p><script>x()</script>"), "Art. 1 uno")

    @unittest.skipUnless(os.getenv("JARVIS_NETWORK_TESTS") == "1", "network test: set JARVIS_NETWORK_TESTS=1")
    def test_normattiva_article(self):
        r = src.articolo("cc", "2086")
        self.assertEqual(r["stato"], "TESTO_UFFICIALE_SCARICATO")
        self.assertIn("2086", r["testo"][:40])


if __name__ == "__main__":
    unittest.main()
