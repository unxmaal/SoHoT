import unittest

from quarry import rosters


class Rosters(unittest.TestCase):
    def test_crate_line(self):
        self.assertEqual(rosters.crate_line('4539 1488 0343 6467'), {'crate_line': True})
        self.assertEqual(rosters.crate_line('79927398713'), {'crate_line': True})

    def test_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)

    def test_paginate(self):
        self.assertEqual(rosters.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(rosters.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
