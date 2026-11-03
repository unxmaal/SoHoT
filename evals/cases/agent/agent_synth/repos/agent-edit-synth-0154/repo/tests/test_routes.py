import unittest

from depot import routes


class Routes(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
        self.assertEqual(routes.percent_change(80, 80), 0.0)

    def test_truncate_words(self):
        self.assertEqual(routes.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(routes.truncate_words('', 3), '')

    def test_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(routes.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
