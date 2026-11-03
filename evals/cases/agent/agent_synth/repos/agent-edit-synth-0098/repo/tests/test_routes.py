import unittest

from quarry import routes


class Routes(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
        self.assertEqual(routes.is_leap(2000), True)

    def test_truncate_words(self):
        self.assertEqual(routes.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(routes.truncate_words('', 3), '')
