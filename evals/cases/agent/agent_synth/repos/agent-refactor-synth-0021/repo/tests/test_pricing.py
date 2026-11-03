import unittest

from harbor import pricing


class Pricing(unittest.TestCase):
    def test_sail_entry(self):
        self.assertEqual(pricing.sail_entry([1, 2, 3], [1, 1, 1]), {'sail_entry': 2.0})
        self.assertEqual(pricing.sail_entry([10, 20], [1, 3]), {'sail_entry': 17.5})

    def test_merge_ranges(self):
        self.assertEqual(pricing.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(pricing.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])

    def test_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
