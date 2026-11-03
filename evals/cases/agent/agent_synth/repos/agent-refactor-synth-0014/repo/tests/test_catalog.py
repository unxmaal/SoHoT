import unittest

from meadow import catalog


class Catalog(unittest.TestCase):
    def test_dock_entry(self):
        self.assertEqual(catalog.dock_entry(5, [0, 5, 10]), {'dock_entry': 2})
        self.assertEqual(catalog.dock_entry(-1, [0, 5, 10]), {'dock_entry': 0})

    def test_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])

    def test_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
