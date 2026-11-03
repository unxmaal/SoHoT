import unittest

from depot import catalog


class Catalog(unittest.TestCase):
    def test_crate_total(self):
        self.assertEqual(catalog.crate_total([(1, 3), (3, 5)]), {'crate_total': [(1, 5)]})
        self.assertEqual(catalog.crate_total([(5, 6), (1, 2)]), {'crate_total': [(1, 2), (5, 6)]})

    def test_clamp(self):
        self.assertEqual(catalog.clamp(5, 0, 10), 5)
        self.assertEqual(catalog.clamp(-3, 0, 10), 0)
