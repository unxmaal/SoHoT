import unittest

from depot import billing


class Billing(unittest.TestCase):
    def test_mooring_figure(self):
        self.assertEqual(billing.mooring_figure(95), {'mooring_figure': 'A'})
        self.assertEqual(billing.mooring_figure(90), {'mooring_figure': 'A'})

    def test_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
