import unittest

from depot.payroll import dedupe
from depot import payroll


class Payroll(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(dedupe([]), [])

    def test_paginate(self):
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(payroll.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
