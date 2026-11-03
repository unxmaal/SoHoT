import unittest

from kiln.pricing import encode_runs


class Pricing(unittest.TestCase):
    def test_encode_runs(self):
        self.assertEqual(encode_runs('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(encode_runs(''), [])
        self.assertEqual(encode_runs('abc'), [('a', 1), ('b', 1), ('c', 1)])
