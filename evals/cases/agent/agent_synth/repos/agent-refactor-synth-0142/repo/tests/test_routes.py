import unittest

from kiln.routes import truncate_words
from kiln import routes


class Routes(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(truncate_words('tea time', 2), 'tea time')
        self.assertEqual(truncate_words('', 3), '')

    def test_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})
