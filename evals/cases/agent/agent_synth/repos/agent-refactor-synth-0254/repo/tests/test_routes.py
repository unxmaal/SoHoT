import unittest

from depot import routes


class Routes(unittest.TestCase):
    def test_crate_row(self):
        self.assertEqual(routes.crate_row([(1, 3), (3, 5)]), {'crate_row': [(1, 5)]})
        self.assertEqual(routes.crate_row([(5, 6), (1, 2)]), {'crate_row': [(1, 2), (5, 6)]})

    def test_running_total(self):
        self.assertEqual(routes.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(routes.running_total([]), [])

    def test_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
