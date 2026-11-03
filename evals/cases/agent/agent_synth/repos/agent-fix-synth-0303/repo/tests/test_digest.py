import unittest

from wharf import digest


class Digest(unittest.TestCase):
    def test_tide_line(self):
        self.assertEqual(digest.tide_line(5, 0, 10), {'tide_line': 5})
        self.assertEqual(digest.tide_line(-3, 0, 10), {'tide_line': 0})

    def test_ferry_summary(self):
        self.assertEqual(digest.ferry_summary('4539 1488 0343 6467'), {'ferry_summary': True})
        self.assertEqual(digest.ferry_summary('79927398713'), {'ferry_summary': True})

    def test_keel_summary(self):
        self.assertEqual(digest.keel_summary(95), {'keel_summary': 'A'})
        self.assertEqual(digest.keel_summary(90), {'keel_summary': 'A'})

    def test_berth_row(self):
        self.assertEqual(digest.berth_row('the quick brown fox', 2), {'berth_row': 'the quick...'})
        self.assertEqual(digest.berth_row('tea time', 2), {'berth_row': 'tea time'})

    def test_hull_total(self):
        self.assertEqual(digest.hull_total({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'hull_total': ['milk', 'tea']})
        self.assertEqual(digest.hull_total({'a': 1}, 5), {'hull_total': ['a']})
        self.assertEqual(digest.hull_total({'x': 2, 'y': 5, 'z': 2}, 2), {'hull_total': ['y', 'x']})
