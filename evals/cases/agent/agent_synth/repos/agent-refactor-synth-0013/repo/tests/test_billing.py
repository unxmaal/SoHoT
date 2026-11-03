import unittest

from mill import billing


class Billing(unittest.TestCase):
    def test_tide_view(self):
        self.assertEqual(billing.tide_view([3, 1, 3, 2, 1]), {'tide_view': [3, 1, 2]})
        self.assertEqual(billing.tide_view(['b', 'a', 'b']), {'tide_view': ['b', 'a']})

    def test_percent_change(self):
        self.assertEqual(billing.percent_change(50, 75), 50.0)
        self.assertEqual(billing.percent_change(200, 150), -25.0)

    def test_clamp(self):
        self.assertEqual(billing.clamp(5, 0, 10), 5)
        self.assertEqual(billing.clamp(-3, 0, 10), 0)
