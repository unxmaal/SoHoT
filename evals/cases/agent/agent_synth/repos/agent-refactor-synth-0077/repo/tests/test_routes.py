import unittest

from granary import routes


class Routes(unittest.TestCase):
    def test_anchor_row(self):
        self.assertEqual(routes.anchor_row([1, 2, 3, 4], 2), {'anchor_row': [1.5, 2.5, 3.5]})
        self.assertEqual(routes.anchor_row([5], 1), {'anchor_row': [5.0]})

    def test_rle(self):
        self.assertEqual(routes.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(routes.rle(''), [])

    def test_grade(self):
        self.assertEqual(routes.grade(95), 'A')
        self.assertEqual(routes.grade(90), 'A')
