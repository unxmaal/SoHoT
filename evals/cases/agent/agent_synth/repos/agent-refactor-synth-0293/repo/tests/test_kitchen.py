import unittest

from quarry import kitchen


class Kitchen(unittest.TestCase):
    def test_crate_check(self):
        self.assertEqual(kitchen.crate_check('4539 1488 0343 6467'), {'crate_check': True})
        self.assertEqual(kitchen.crate_check('79927398713'), {'crate_check': True})

    def test_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])

    def test_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
