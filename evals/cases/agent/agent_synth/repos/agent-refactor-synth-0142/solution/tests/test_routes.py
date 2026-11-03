import unittest

from kiln.routes import shorten
from kiln import routes


class Routes(unittest.TestCase):
    def test_shorten(self):
        self.assertEqual(shorten('the quick brown fox', 2), 'the quick...')
        self.assertEqual(shorten('tea time', 2), 'tea time')
        self.assertEqual(shorten('', 3), '')

    def test_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})
