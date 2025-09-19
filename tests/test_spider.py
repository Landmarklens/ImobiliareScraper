"""Basic tests for ImobiliareScraper spider"""
import unittest


class TestImobiliareSpider(unittest.TestCase):
    """Basic test case for spider functionality"""

    def test_import(self):
        """Test that spider can be imported"""
        try:
            from imobiliare_spiders.scraper_core.spiders.romania.imobiliare_ro import ImobiliareRoSpider
            self.assertTrue(True)
        except ImportError:
            self.fail("Failed to import ImobiliareRoSpider")

    def test_spider_name(self):
        """Test spider name is correct"""
        from imobiliare_spiders.scraper_core.spiders.romania.imobiliare_ro import ImobiliareRoSpider
        spider = ImobiliareRoSpider()
        self.assertEqual(spider.name, "imobiliare_ro")

    def test_spider_country(self):
        """Test spider country is set correctly"""
        from imobiliare_spiders.scraper_core.spiders.romania.imobiliare_ro import ImobiliareRoSpider
        spider = ImobiliareRoSpider()
        self.assertEqual(spider.country, "romania")


if __name__ == '__main__':
    unittest.main()