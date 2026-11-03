import unittest

from beacon import routes


class Routes(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(routes.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.truncate_words('tea time', 2), 'tea time')

    def test_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])

    def test_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
