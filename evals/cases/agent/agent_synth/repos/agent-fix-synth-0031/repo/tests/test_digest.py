import unittest

from mill import digest


class Digest(unittest.TestCase):
    def test_ferry_row(self):
        self.assertEqual(digest.ferry_row(5, 0, 10), {'ferry_row': 5})
        self.assertEqual(digest.ferry_row(-3, 0, 10), {'ferry_row': 0})

    def test_mast_check(self):
        self.assertEqual(digest.mast_check([3, 1, 3, 2, 1]), {'mast_check': [3, 1, 2]})
        self.assertEqual(digest.mast_check(['b', 'a', 'b']), {'mast_check': ['b', 'a']})

    def test_lantern_view(self):
        self.assertEqual(digest.lantern_view({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'lantern_view': ['milk', 'tea']})
        self.assertEqual(digest.lantern_view({'a': 1}, 5), {'lantern_view': ['a']})

    def test_tide_line(self):
        self.assertEqual(digest.tide_line('1h30m'), {'tide_line': 5400})
        self.assertEqual(digest.tide_line('45s'), {'tide_line': 45})
        self.assertEqual(digest.tide_line('10m5s'), {'tide_line': 605})
