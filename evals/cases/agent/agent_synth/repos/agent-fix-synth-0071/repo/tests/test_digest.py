import unittest

from foundry import digest


class Digest(unittest.TestCase):
    def test_berth_summary(self):
        self.assertEqual(digest.berth_summary([3, 1, 2]), {'berth_summary': 2})
        self.assertEqual(digest.berth_summary([4, 1, 3, 2]), {'berth_summary': 2.5})

    def test_sail_entry(self):
        self.assertEqual(digest.sail_entry([3, 1, 3, 2, 1]), {'sail_entry': [3, 1, 2]})
        self.assertEqual(digest.sail_entry(['b', 'a', 'b']), {'sail_entry': ['b', 'a']})

    def test_rope_check(self):
        self.assertEqual(digest.rope_check([1, 2, 3]), {'rope_check': [1, 3, 6]})
        self.assertEqual(digest.rope_check([]), {'rope_check': []})
        self.assertEqual(digest.rope_check([5]), {'rope_check': [5]})

    def test_tide_row(self):
        self.assertEqual(digest.tide_row([1, 2, 3], [1, 1, 1]), {'tide_row': 2.0})
        self.assertEqual(digest.tide_row([10, 20], [1, 3]), {'tide_row': 17.5})
