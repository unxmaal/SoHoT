import unittest

from orchard.payroll import drop_repeats


class Payroll(unittest.TestCase):
    def test_drop_repeats(self):
        self.assertEqual(drop_repeats([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(drop_repeats(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(drop_repeats([]), [])
