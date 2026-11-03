import unittest

from tally import kitchen


class Kitchen(unittest.TestCase):
    def test_dock_check(self):
        self.assertEqual(kitchen.dock_check('4539 1488 0343 6467'), {'dock_check': True})
        self.assertEqual(kitchen.dock_check('79927398713'), {'dock_check': True})

    def test_weighted_mean(self):
        self.assertEqual(kitchen.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(kitchen.weighted_mean([10, 20], [1, 3]), 17.5)
