import unittest

from granary import archive


class Archive(unittest.TestCase):
    def test_dock_row(self):
        self.assertEqual(archive.dock_row('OrderTotal'), {'dock_row': 'order_total'})
        self.assertEqual(archive.dock_row('plain'), {'dock_row': 'plain'})

    def test_top_n(self):
        self.assertEqual(archive.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(archive.top_n({'a': 1}, 5), ['a'])
