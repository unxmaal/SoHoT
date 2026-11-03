import unittest

from quarry import kitchen


class Kitchen(unittest.TestCase):
    def test_sail_entry(self):
        self.assertEqual(kitchen.sail_entry('4539 1488 0343 6467'), {'sail_entry': True})
        self.assertEqual(kitchen.sail_entry('79927398713'), {'sail_entry': True})

    def test_top_n(self):
        self.assertEqual(kitchen.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(kitchen.top_n({'a': 1}, 5), ['a'])

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
