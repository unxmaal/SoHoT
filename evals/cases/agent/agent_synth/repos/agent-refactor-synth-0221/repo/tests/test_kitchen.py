import unittest

from granary import kitchen


class Kitchen(unittest.TestCase):
    def test_sail_row(self):
        self.assertEqual(kitchen.sail_row(95), {'sail_row': 'A'})
        self.assertEqual(kitchen.sail_row(90), {'sail_row': 'A'})

    def test_running_total(self):
        self.assertEqual(kitchen.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(kitchen.running_total([]), [])
