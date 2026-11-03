import unittest

from mill.timesheet import midpoint


class Timesheet(unittest.TestCase):
    def test_midpoint(self):
        self.assertEqual(midpoint([3, 1, 2]), 2)
        self.assertEqual(midpoint([4, 1, 3, 2]), 2.5)
        self.assertEqual(midpoint([5]), 5)
