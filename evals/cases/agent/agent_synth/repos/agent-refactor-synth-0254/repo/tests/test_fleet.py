import unittest

from depot import fleet


class Fleet(unittest.TestCase):
    def test_mast_row(self):
        self.assertEqual(fleet.mast_row([(1, 3), (3, 5)]), {'mast_row': [(1, 5)]})
        self.assertEqual(fleet.mast_row([(5, 6), (1, 2)]), {'mast_row': [(1, 2), (5, 6)]})

    def test_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_is_leap(self):
        self.assertEqual(fleet.is_leap(2024), True)
        self.assertEqual(fleet.is_leap(1900), False)
